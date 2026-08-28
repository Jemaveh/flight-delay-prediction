"""
Module d'ingestion pour l'API publique OpenSky Network.

Ligne de raisonnement
----------------------
OpenSky Network expose une API REST publique qui retourne, pour l'ensemble
des aéronefs suivis par le réseau de récepteurs ADS-B, leur position et leur
état à un instant donné (endpoint /states/all). Cette API est accessible en
mode anonyme avec un quota d'appels restreint, ou avec une authentification
Basic Auth qui augmente ce quota.

Les appels sont effectués directement via la librairie `requests`, ce qui
rend explicite chaque aspect de la requête (timeout, gestion des erreurs,
authentification).

L'endpoint /states/all fournit uniquement des positions instantanées : pour
chaque aéronef suivi, sa localisation et son état à l'instant de la requête,
sans aucune information sur son aéroport d'origine ni sur son aéroport de
destination. Les endpoints /flights/departure et /flights/arrival
répondent à ce besoin : interrogés par aéroport (code ICAO) et par fenêtre
temporelle, ils retournent la liste des vols ayant décollé ou atterri à cet
aéroport durant la période demandée, avec pour chacun l'aéroport d'origine
et l'aéroport de destination.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from config.settings import settings
from src.utils.chemins import chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

URL_BASE_OPENSKY = "https://opensky-network.org/api"
TIMEOUT_SECONDES = 10

# Intervalle maximal autorisé entre `debut` et `fin` sur les endpoints
# /flights/departure et /flights/arrival, imposé par l'API OpenSky Network
DUREE_MAX_INTERVALLE_SECONDES = 7 * 24 * 60 * 60

# Valeurs placeholder présentes dans le fichier .env.example : si les identifiants
# de l'utilisateur correspondent encore à ces valeurs, cela signifie qu'ils n'ont
# pas été renseignés.
IDENTIFIANTS_NON_RENSEIGNES = {"", "identifiant_opensky", "mot_de_passe_opensky"}


def construire_enveloppe_vols(
    vols: list[dict],
    endpoint: str,
    icao_aeroport: str,
    debut: int,
    fin: int,
) -> dict:
    """
    Assemble le JSON brut d'un appel /flights/departure ou /flights/arrival.

    Parameters
    ----------
    vols : list[dict]
        Liste retournée par l'API OpenSky Network.
    endpoint : str
        Segment d'URL interrogé, "departure" ou "arrival".
    icao_aeroport : str
        Code ICAO de l'aéroport interrogé.
    debut, fin : int
        Bornes Unix (secondes) de la fenêtre demandée.

    Returns
    -------
    dict
        Enveloppe avec horodatage UTC, métadonnées d'appel et liste `vols`.
    """
    return {
        "horodatage_collecte": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "airport": icao_aeroport,
        "begin": debut,
        "end": fin,
        "nb_vols": len(vols),
        "vols": vols,
    }


class ErreurAPIOpenSky(Exception):
    """
    Exception levée lorsque l'appel à l'API OpenSky Network échoue.
    """


class OpenSkyClient:
    """
    Module permettant d'interroger l'API OpenSky Network et de sauvegarder les
    données brutes récupérées.
    """

    def __init__(self) -> None:
        """
        Initialise le module d'ingestion : prépare l'URL de base de l'API et
        les identifiants d'authentification (s'ils sont disponibles).
        """
        self._logger = get_logger(__name__)
        self._url_base = URL_BASE_OPENSKY
        self._auth = self._preparer_authentification()

    def _preparer_authentification(self) -> tuple[str, str] | None:
        """
        Prépare les identifiants Basic Auth à partir de la configuration.

        Returns
        -------
        tuple[str, str] | None
            Le couple (identifiant, mot de passe) si des identifiants réels
            ont été renseignés dans le fichier .env, sinon None.
        """
        if (
            settings.opensky_username in IDENTIFIANTS_NON_RENSEIGNES
            or settings.opensky_password in IDENTIFIANTS_NON_RENSEIGNES
        ):
            self._logger.warning(
                "Identifiants OpenSky non renseignés : le module fonctionnera "
                "en mode anonyme, avec un quota d'appels API plus restreint."
            )
            return None

        return (settings.opensky_username, settings.opensky_password)

    def recuperer_vols_en_temps_reel(
        self, bbox: tuple[float, float, float, float] | None = None
    ) -> dict:
        """
        Interroge l'endpoint /states/all de l'API OpenSky Network.

        Parameters
        ----------
        bbox : tuple[float, float, float, float] | None
            Bounding box géographique optionnelle sous la forme
            (lamin, lomin, lamax, lomax), c'est-à-dire (latitude minimale,
            longitude minimale, latitude maximale, longitude maximale). Si
            None, l'API retourne l'état de tous les aéronefs suivis dans le
            monde, ce qui représente un volume de données beaucoup plus
            important.

        Returns
        -------
        dict
            Le contenu JSON de la réponse, tel que retourné par l'API.

        Raises
        ------
        ErreurAPIOpenSky
            Si la requête échoue (timeout, erreur de connexion, ou code HTTP
            d'erreur retourné par l'API).
        """
        parametres: dict[str, float] = {}
        if bbox is not None:
            lamin, lomin, lamax, lomax = bbox
            parametres = {
                "lamin": lamin,
                "lomin": lomin,
                "lamax": lamax,
                "lomax": lomax,
            }

        url = f"{self._url_base}/states/all"

        try:
            reponse = requests.get(
                url,
                params=parametres,
                auth=self._auth,
                timeout=TIMEOUT_SECONDES,
            )
        except requests.exceptions.Timeout as erreur:
            self._logger.error(
                "Délai d'attente dépassé (%s secondes) lors de l'appel à l'API OpenSky.",
                TIMEOUT_SECONDES,
            )
            raise ErreurAPIOpenSky(
                "Timeout lors de l'appel à l'API OpenSky Network."
            ) from erreur
        except requests.exceptions.ConnectionError as erreur:
            self._logger.error(
                "Impossible de se connecter à l'API OpenSky Network : %s", erreur
            )
            raise ErreurAPIOpenSky(
                "Erreur de connexion à l'API OpenSky Network."
            ) from erreur

        if reponse.status_code == 401:
            self._logger.error(
                "Authentification refusée par l'API OpenSky (code 401) : "
                "vérifier les identifiants renseignés dans le fichier .env."
            )
            raise ErreurAPIOpenSky("Authentification refusée (401) par l'API OpenSky Network.")

        if reponse.status_code == 429:
            self._logger.error(
                "Quota d'appels dépassé (code 429) sur l'API OpenSky Network."
            )
            raise ErreurAPIOpenSky("Quota d'appels dépassé (429) sur l'API OpenSky Network.")

        if reponse.status_code >= 500:
            self._logger.error(
                "Erreur serveur côté OpenSky Network (code %s).", reponse.status_code
            )
            raise ErreurAPIOpenSky(
                f"Erreur serveur ({reponse.status_code}) sur l'API OpenSky Network."
            )

        if reponse.status_code != 200:
            self._logger.error(
                "Réponse HTTP inattendue (code %s) de l'API OpenSky Network.",
                reponse.status_code,
            )
            raise ErreurAPIOpenSky(
                f"Réponse HTTP inattendue ({reponse.status_code}) de l'API OpenSky Network."
            )

        self._logger.info("Appel à l'API OpenSky Network réussi (code 200).")
        return reponse.json()

    def _recuperer_vols(
        self, endpoint: str, icao_aeroport: str, debut: int, fin: int
    ) -> list[dict]:
        """
        Interroge un endpoint /flights/{departure,arrival} de l'API OpenSky
        Network et retourne la liste des vols correspondants.

        Cette méthode privée factorise la logique commune aux méthodes
        publiques `recuperer_vols_depart` et `recuperer_vols_arrivee`, qui ne
        diffèrent que par le endpoint interrogé.

        Parameters
        ----------
        endpoint : str
            Le segment d'URL à interroger, "departure" ou "arrival".
        icao_aeroport : str
            Code ICAO de l'aéroport concerné (ex : "LFPG" pour Paris-Charles-
            de-Gaulle).
        debut : int
            Timestamp Unix (en secondes) marquant le début de la fenêtre
            temporelle recherchée.
        fin : int
            Timestamp Unix (en secondes) marquant la fin de la fenêtre
            temporelle recherchée.

        Returns
        -------
        list[dict]
            La liste des vols retournés par l'API, chacun sous la forme d'un
            dictionnaire contenant notamment les aéroports d'origine et de
            destination, les horaires programmés et réels, ainsi que
            l'indicatif du vol.

        Raises
        ------
        ValueError
            Si l'intervalle entre `debut` et `fin` dépasse 604800 secondes
            (7 jours), limite maximale imposée par l'API OpenSky Network sur
            ces deux endpoints.
        ErreurAPIOpenSky
            Si la requête échoue (timeout, erreur de connexion, ou code HTTP
            d'erreur retourné par l'API).
        """
        if fin - debut > DUREE_MAX_INTERVALLE_SECONDES:
            raise ValueError(
                "L'intervalle entre 'debut' et 'fin' ne peut pas dépasser "
                f"{DUREE_MAX_INTERVALLE_SECONDES} secondes (7 jours) sur "
                "les endpoints /flights/departure et /flights/arrival de "
                "l'API OpenSky Network."
            )

        url = f"{self._url_base}/flights/{endpoint}"
        # Le paramètre HTTP attendu par l'API s'appelle "end", pas "fin"
        parametres = {
            "airport": icao_aeroport,
            "begin": debut,
            "end": fin,
        }

        try:
            reponse = requests.get(
                url,
                params=parametres,
                auth=self._auth,
                timeout=TIMEOUT_SECONDES,
            )
        except requests.exceptions.Timeout as erreur:
            self._logger.error(
                "Délai d'attente dépassé (%s secondes) lors de l'appel à l'API OpenSky.",
                TIMEOUT_SECONDES,
            )
            raise ErreurAPIOpenSky(
                "Timeout lors de l'appel à l'API OpenSky Network."
            ) from erreur
        except requests.exceptions.ConnectionError as erreur:
            self._logger.error(
                "Impossible de se connecter à l'API OpenSky Network : %s", erreur
            )
            raise ErreurAPIOpenSky(
                "Erreur de connexion à l'API OpenSky Network."
            ) from erreur

        if reponse.status_code == 401:
            self._logger.error(
                "Authentification refusée par l'API OpenSky (code 401) : "
                "vérifier les identifiants renseignés dans le fichier .env."
            )
            raise ErreurAPIOpenSky("Authentification refusée (401) par l'API OpenSky Network.")

        if reponse.status_code == 429:
            self._logger.error(
                "Quota d'appels dépassé (code 429) sur l'API OpenSky Network."
            )
            raise ErreurAPIOpenSky("Quota d'appels dépassé (429) sur l'API OpenSky Network.")

        if reponse.status_code >= 500:
            self._logger.error(
                "Erreur serveur côté OpenSky Network (code %s).", reponse.status_code
            )
            raise ErreurAPIOpenSky(
                f"Erreur serveur ({reponse.status_code}) sur l'API OpenSky Network."
            )

        if reponse.status_code == 404:
            self._logger.info(
                "Aucun vol sur /flights/%s pour %s (HTTP 404) : liste vide.",
                endpoint,
                icao_aeroport,
            )
            return []

        if reponse.status_code != 200:
            self._logger.error(
                "Réponse HTTP inattendue (code %s) de l'API OpenSky Network.",
                reponse.status_code,
            )
            raise ErreurAPIOpenSky(
                f"Réponse HTTP inattendue ({reponse.status_code}) de l'API OpenSky Network."
            )

        self._logger.info("Appel à l'API OpenSky Network réussi (code 200).")
        payload = reponse.json()
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise ErreurAPIOpenSky(
                "Réponse /flights/* inattendue : une liste de vols était attendue."
            )
        return payload

    def recuperer_vols_depart(self, icao_aeroport: str, debut: int, fin: int) -> list[dict]:
        """
        Interroge l'endpoint /flights/departure de l'API OpenSky Network.

        Retourne la liste des vols ayant décollé de l'aéroport donné pendant
        la fenêtre temporelle demandée, avec pour chacun l'aéroport
        d'origine et l'aéroport de destination.

        Parameters
        ----------
        icao_aeroport : str
            Code ICAO de l'aéroport de départ (ex : "LFPG" pour Paris-CDG).
        debut : int
            Timestamp Unix (en secondes) marquant le début de la fenêtre
            temporelle recherchée.
        fin : int
            Timestamp Unix (en secondes) marquant la fin de la fenêtre
            temporelle recherchée.

        Returns
        -------
        list[dict]
            La liste des vols au départ de l'aéroport, tels que retournés
            par l'API.

        Raises
        ------
        ValueError
            Si l'intervalle entre `debut` et `fin` dépasse 604800 secondes
            (7 jours), limite maximale imposée par l'API OpenSky Network sur
            cet endpoint.
        ErreurAPIOpenSky
            Si la requête échoue (timeout, erreur de connexion, ou code HTTP
            d'erreur retourné par l'API).
        """
        return self._recuperer_vols("departure", icao_aeroport, debut, fin)

    def recuperer_vols_arrivee(self, icao_aeroport: str, debut: int, fin: int) -> list[dict]:
        """
        Interroge l'endpoint /flights/arrival de l'API OpenSky Network.

        Retourne la liste des vols ayant atterri à l'aéroport donné pendant
        la fenêtre temporelle demandée, avec pour chacun l'aéroport
        d'origine et l'aéroport de destination. Mêmes paramètres, même
        contrainte d'intervalle et mêmes exceptions que
        `recuperer_vols_depart` : voir son docstring pour le détail.

        Parameters
        ----------
        icao_aeroport : str
            Code ICAO de l'aéroport d'arrivée (ex : "LFPG" pour Paris-CDG).
        debut : int
            Timestamp Unix (en secondes) marquant le début de la fenêtre
            temporelle recherchée.
        fin : int
            Timestamp Unix (en secondes) marquant la fin de la fenêtre
            temporelle recherchée.

        Returns
        -------
        list[dict]
            La liste des vols à l'arrivée de l'aéroport, tels que retournés
            par l'API.

        Raises
        ------
        ValueError
            Si l'intervalle entre `debut` et `fin` dépasse 604800 secondes
            (7 jours), limite maximale imposée par l'API OpenSky Network sur
            cet endpoint.
        ErreurAPIOpenSky
            Si la requête échoue (timeout, erreur de connexion, ou code HTTP
            d'erreur retourné par l'API).
        """
        return self._recuperer_vols("arrival", icao_aeroport, debut, fin)

    def sauvegarder_vols(
        self,
        vols: list[dict],
        endpoint: str,
        icao_aeroport: str,
        debut: int,
        fin: int,
        dossier: str = "data/raw",
    ) -> str:
        """
        Enveloppe une réponse /flights/* et l'écrit dans data/raw/.

        Parameters
        ----------
        vols : list[dict]
            Liste retournée par `recuperer_vols_depart` ou `recuperer_vols_arrivee`.
        endpoint : str
            "departure" ou "arrival".
        icao_aeroport : str
            Code ICAO de l'aéroport interrogé.
        debut, fin : int
            Bornes Unix (secondes) de la fenêtre demandée.
        dossier : str
            Dossier de destination.

        Returns
        -------
        str
            Chemin du fichier créé (`opensky_flights_{endpoint}_{icao}_UTC.json`).
        """
        enveloppe = construire_enveloppe_vols(
            vols, endpoint, icao_aeroport, debut, fin
        )
        prefixe = f"opensky_flights_{endpoint}_{icao_aeroport}"
        return self.sauvegarder_donnees_brutes(
            enveloppe, dossier=dossier, prefixe_fichier=prefixe
        )

    def sauvegarder_donnees_brutes(
        self,
        donnees: dict,
        dossier: str = "data/raw",
        prefixe_fichier: str = "opensky",
    ) -> str:
        """
        Sauvegarde les données brutes récupérées dans un fichier JSON horodaté UTC.

        Parameters
        ----------
        donnees : dict
            Le contenu JSON à sauvegarder (typiquement le résultat de
            `recuperer_vols_en_temps_reel` ou l'enveloppe /flights/*).
        dossier : str
            Le dossier de destination. Créé automatiquement s'il n'existe pas.
        prefixe_fichier : str
            Préfixe du nom de fichier, avant l'horodatage UTC.

        Returns
        -------
        str
            Le chemin complet du fichier créé.
        """
        chemin_dossier = Path(dossier)
        chemin_dossier.mkdir(parents=True, exist_ok=True)

        horodatage = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        chemin_fichier = chemin_dossier / f"{prefixe_fichier}_{horodatage}.json"

        try:
            with chemin_fichier.open("w", encoding="utf-8") as fichier:
                json.dump(donnees, fichier, ensure_ascii=False, indent=2)
        except OSError as erreur:
            self._logger.error(
                "Impossible d'écrire le fichier de données brutes '%s' : %s",
                chemin_relatif_projet(chemin_fichier),
                erreur,
            )
            raise

        self._logger.info(
            "Données brutes sauvegardées dans '%s'.",
            chemin_relatif_projet(chemin_fichier),
        )
        return str(chemin_fichier)


if __name__ == "__main__":
    # Exemple d'utilisation manuelle : récupération des vols au-dessus de la
    # France métropolitaine (bounding box approximative), puis sauvegarde du
    # résultat brut dans data/raw/. Utile pour une vérification rapide du
    # module sans passer par les tests automatisés.
    client = OpenSkyClient()
    BBOX_FRANCE = (41.0, -5.0, 51.5, 10.0)  # lamin, lomin, lamax, lomax

    donnees_vols = client.recuperer_vols_en_temps_reel(bbox=BBOX_FRANCE)
    chemin_sauvegarde = client.sauvegarder_donnees_brutes(donnees_vols)
    logger.info(
        "Exécution manuelle terminée, fichier généré : '%s'.",
        chemin_relatif_projet(chemin_sauvegarde),
    )

    # Exemple d'utilisation des vols programmés : vols au départ de Paris-CDG
    # sur les dernières 24 heures
    instant_present = int(datetime.now().timestamp())
    instant_hier = instant_present - 24 * 60 * 60

    vols_depart_cdg = client.recuperer_vols_depart(
        icao_aeroport="LFPG", debut=instant_hier, fin=instant_present
    )
    logger.info(
        "Vols au départ de LFPG sur les dernières 24h : %s vol(s) trouvé(s).",
        len(vols_depart_cdg),
    )
