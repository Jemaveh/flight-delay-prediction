"""
Client d'ingestion pour l'API publique OpenSky Network.

Ligne de raisonnement
----------------------
OpenSky Network expose une API REST publique qui retourne, pour l'ensemble
des aéronefs suivis par le réseau de récepteurs ADS-B, leur position et leur
état à un instant donné (endpoint /states/all). Cette API est accessible en
mode anonyme avec un quota d'appels restreint, ou avec une authentification
Basic Auth qui augmente ce quota.

On implémente ici un appel HTTP direct via la librairie `requests` plutôt que
d'utiliser une librairie cliente tierce dédiée à OpenSky : l'API REST est
simple (un seul endpoint utile pour ce projet, des paramètres de requête
basiques), et un appel direct rend explicite et contrôlable chaque aspect de
la requête (timeout, gestion des erreurs, authentification), sans dépendre
d'une librairie externe supplémentaire à maintenir.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import requests

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

URL_BASE_OPENSKY = "https://opensky-network.org/api"
TIMEOUT_SECONDES = 10

# Valeurs placeholder présentes dans le fichier .env.example : si les identifiants
# de l'utilisateur correspondent encore à ces valeurs, cela signifie qu'ils n'ont
# pas été renseignés, et le client doit basculer en mode anonyme plutôt que
# d'envoyer des identifiants invalides à l'API.
IDENTIFIANTS_NON_RENSEIGNES = {"", "ton_identifiant_opensky", "ton_mot_de_passe_opensky"}


class ErreurAPIOpenSky(Exception):
    """
    Exception levée lorsque l'appel à l'API OpenSky Network échoue.

    Utiliser une exception dédiée plutôt que de laisser remonter les
    exceptions brutes de `requests` permet aux modules appelants (pipeline
    d'ingestion, orchestrateur) d'attraper une seule et même famille
    d'erreurs, sans avoir à connaître le détail des exceptions internes de la
    librairie HTTP utilisée.
    """


class OpenSkyClient:
    """
    Client permettant d'interroger l'API OpenSky Network et de sauvegarder les
    données brutes récupérées.
    """

    def __init__(self) -> None:
        """
        Initialise le client : prépare l'URL de base de l'API et les
        identifiants d'authentification (s'ils sont disponibles).
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

        Pourquoi ne pas lever une exception si les identifiants sont absents ?
        ----------------------------------------------------------------------
        L'authentification est OPTIONNELLE pour cette API : un usage anonyme
        reste possible, avec un quota d'appels plus restreint. Bloquer tout le
        pipeline parce qu'un identifiant optionnel est absent serait une
        gestion d'erreur disproportionnée. On journalise un avertissement
        pour que ce choix reste visible et traçable, sans interrompre
        l'exécution.
        """
        if (
            settings.opensky_username in IDENTIFIANTS_NON_RENSEIGNES
            or settings.opensky_password in IDENTIFIANTS_NON_RENSEIGNES
        ):
            self._logger.warning(
                "Identifiants OpenSky non renseignés : le client fonctionnera "
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

        # On distingue les codes d'erreur les plus fréquents pour journaliser
        # un message explicite, plutôt qu'un message générique peu utile pour
        # diagnostiquer le problème a posteriori.
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

    def sauvegarder_donnees_brutes(self, donnees: dict, dossier: str = "data/raw") -> str:
        """
        Sauvegarde les données brutes récupérées dans un fichier JSON horodaté.

        Parameters
        ----------
        donnees : dict
            Le contenu JSON à sauvegarder (typiquement le résultat de
            `recuperer_vols_en_temps_reel`).
        dossier : str
            Le dossier de destination. Créé automatiquement s'il n'existe pas.

        Returns
        -------
        str
            Le chemin complet du fichier créé.

        Pourquoi un fichier horodaté plutôt qu'un seul fichier réécrit à
        chaque appel ?
        ----------------------------------------------------------------------
        Conserver un historique de chaque extraction (plutôt que d'écraser la
        précédente) permet de rejouer les étapes de transformation en aval
        sans avoir à réinterroger l'API, et de conserver une trace brute en
        cas d'anomalie détectée plus tard dans le pipeline. C'est le principe
        de la zone "raw" d'un pipeline de données : les données n'y sont
        jamais modifiées ni supprimées après écriture.
        """
        chemin_dossier = Path(dossier)
        chemin_dossier.mkdir(parents=True, exist_ok=True)

        horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
        chemin_fichier = chemin_dossier / f"opensky_{horodatage}.json"

        try:
            with chemin_fichier.open("w", encoding="utf-8") as fichier:
                json.dump(donnees, fichier, ensure_ascii=False, indent=2)
        except OSError as erreur:
            self._logger.error(
                "Impossible d'écrire le fichier de données brutes '%s' : %s",
                chemin_fichier,
                erreur,
            )
            raise

        self._logger.info("Données brutes sauvegardées dans '%s'.", chemin_fichier)
        return str(chemin_fichier)


if __name__ == "__main__":
    # Exemple d'utilisation manuelle : récupération des vols au-dessus de la
    # France métropolitaine (bounding box approximative), puis sauvegarde du
    # résultat brut dans data/raw/. Utile pour une vérification rapide du
    # client sans passer par les tests automatisés.
    client = OpenSkyClient()
    BBOX_FRANCE = (41.0, -5.0, 51.5, 10.0)  # lamin, lomin, lamax, lomax

    donnees_vols = client.recuperer_vols_en_temps_reel(bbox=BBOX_FRANCE)
    chemin_sauvegarde = client.sauvegarder_donnees_brutes(donnees_vols)
    logger.info("Exécution manuelle terminée, fichier généré : '%s'.", chemin_sauvegarde)
