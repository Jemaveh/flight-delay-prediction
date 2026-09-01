"""
Module d'ingestion pour l'API publique OpenSky Network.

Ligne de raisonnement
----------------------
OpenSky Network expose une API REST publique qui retourne, pour l'ensemble
des aéronefs suivis par le réseau de récepteurs ADS-B, leur position et leur
état à un instant donné (endpoint /states/all). Depuis mars 2026, l'API
n'accepte plus l'identifiant/mot de passe du compte (Basic Auth) : il faut
un **API Client** OAuth2 (client_id + secret → jeton Bearer). Sans ces
identifiants, les appels partent en anonyme (crédits très bas). Trino n'est
pas requis pour `/flights/departure` ni `/flights/arrival`. Le nom du
compte feeder (récepteur ADS-B) ne s'utilise pas comme Client ID.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from config.settings import settings
from src.utils.chemins import chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

URL_BASE_OPENSKY = "https://opensky-network.org/api"
URL_JETON_OPENSKY = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)
TIMEOUT_SECONDES = 60
MARGE_RAFRAICHISSEMENT_JETON_SECONDES = 30

# Intervalle maximal autorisé entre `debut` et `fin` sur les endpoints
# /flights/departure et /flights/arrival, imposé par l'API OpenSky Network
DUREE_MAX_INTERVALLE_SECONDES = 7 * 24 * 60 * 60

# Placeholders .env.example : absents = pas d'OAuth (mode anonyme).
IDENTIFIANTS_OAUTH_NON_RENSEIGNES = {
    "",
    "identifiant_client_opensky",
    "secret_client_opensky",
}


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


def extraire_retry_after_secondes(reponse: object) -> float | None:
    """
    Lit l'en-tête Retry-After d'une réponse HTTP, en secondes.

    Returns
    -------
    float | None
        Délai indiqué par l'API, ou None s'il est absent ou non numérique.
    """
    headers = getattr(reponse, "headers", None)
    getter = getattr(headers, "get", None) if headers is not None else None
    if not callable(getter):
        return None
    brut = getter("Retry-After")
    if brut is None:
        brut = getter("retry-after")
    if not isinstance(brut, (str, int, float)):
        return None
    try:
        valeur = float(str(brut).strip())
    except ValueError:
        return None
    if valeur <= 0:
        return None
    return valeur


def extraire_credits_restants(reponse: object) -> int | None:
    """
    Lit l'en-tête X-Rate-Limit-Remaining (crédits encore disponibles).
    """
    headers = getattr(reponse, "headers", None)
    getter = getattr(headers, "get", None) if headers is not None else None
    if not callable(getter):
        return None
    brut = getter("X-Rate-Limit-Remaining")
    if brut is None:
        brut = getter("x-rate-limit-remaining")
    if not isinstance(brut, (str, int, float)):
        return None
    try:
        return int(float(str(brut).strip()))
    except ValueError:
        return None


def oauth_est_configure(
    client_id: str | None,
    client_secret: str | None,
) -> bool:
    """Indique si un couple client_id / secret API Client est réellement renseigné."""
    return (
        client_id not in IDENTIFIANTS_OAUTH_NON_RENSEIGNES
        and client_secret not in IDENTIFIANTS_OAUTH_NON_RENSEIGNES
        and client_id is not None
        and client_secret is not None
    )


class ErreurAPIOpenSky(Exception):
    """
    Exception levée lorsque l'appel à l'API OpenSky Network échoue.
    """

    def __init__(
        self,
        message: str,
        retry_after_secondes: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_secondes = retry_after_secondes


class OpenSkyClient:
    """
    Module permettant d'interroger l'API OpenSky Network et de sauvegarder les
    données brutes récupérées.
    """

    def __init__(self) -> None:
        """
        Initialise le module d'ingestion : URL de base et identifiants OAuth
        API Client (s'ils sont disponibles). Le compte feeder n'est pas utilisé.
        """
        self._logger = get_logger(__name__)
        self._url_base = URL_BASE_OPENSKY
        self._client_id, self._client_secret = self._preparer_oauth()
        self._jeton: str | None = None
        self._jeton_expire_a: datetime | None = None

    def _preparer_oauth(self) -> tuple[str, str] | tuple[None, None]:
        """
        Lit OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET. Sans couple réel :
        mode anonyme. Ne logue jamais le secret.
        """
        client_id = settings.opensky_client_id
        client_secret = settings.opensky_client_secret
        if not oauth_est_configure(client_id, client_secret):
            self._logger.warning(
                "API Client OpenSky non renseigné (OPENSKY_CLIENT_ID / "
                "OPENSKY_CLIENT_SECRET) : appels anonymes, crédits très "
                "limités. /flights exige un API Client activé sur le compte, "
                "pas le nom d'utilisateur feeder, pas Trino."
            )
            return None, None
        return client_id, client_secret

    def _obtenir_jeton(self) -> str | None:
        """
        Retourne un jeton Bearer, en le renouvelant si besoin. None si anonyme.
        """
        if self._client_id is None or self._client_secret is None:
            return None
        maintenant = datetime.now(timezone.utc)
        if (
            self._jeton
            and self._jeton_expire_a is not None
            and maintenant < self._jeton_expire_a
        ):
            return self._jeton

        try:
            reponse = requests.post(
                URL_JETON_OPENSKY,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=TIMEOUT_SECONDES,
            )
        except requests.exceptions.Timeout as erreur:
            self._logger.error(
                "Délai d'attente dépassé lors de la demande de jeton OpenSky."
            )
            raise ErreurAPIOpenSky(
                "Timeout lors de la demande de jeton OAuth OpenSky."
            ) from erreur
        except requests.exceptions.ConnectionError as erreur:
            self._logger.error(
                "Impossible de joindre le serveur d'authentification OpenSky."
            )
            raise ErreurAPIOpenSky(
                "Erreur de connexion au serveur d'authentification OpenSky."
            ) from erreur

        if reponse.status_code in (401, 403):
            self._logger.error(
                "Jeton OAuth OpenSky refusé (HTTP %s) : vérifier que l'API "
                "Client est activé et que OPENSKY_CLIENT_ID / "
                "OPENSKY_CLIENT_SECRET correspondent au client (pas au "
                "compte feeder).",
                reponse.status_code,
            )
            raise ErreurAPIOpenSky(
                f"Authentification OAuth refusée ({reponse.status_code}) "
                "par OpenSky Network."
            )
        if reponse.status_code != 200:
            self._logger.error(
                "Échec de la demande de jeton OpenSky (HTTP %s).",
                reponse.status_code,
            )
            raise ErreurAPIOpenSky(
                f"Échec de la demande de jeton OAuth OpenSky "
                f"({reponse.status_code})."
            )

        payload = reponse.json()
        jeton = payload.get("access_token")
        if not isinstance(jeton, str) or not jeton:
            raise ErreurAPIOpenSky(
                "Réponse jeton OpenSky inattendue : access_token manquant."
            )
        expires_in = int(payload.get("expires_in") or 1800)
        marge = min(MARGE_RAFRAICHISSEMENT_JETON_SECONDES, max(expires_in - 1, 0))
        self._jeton = jeton
        self._jeton_expire_a = maintenant + timedelta(seconds=expires_in - marge)
        self._logger.info(
            "Jeton OAuth OpenSky obtenu (expire dans %s s, non logué).",
            expires_in,
        )
        return self._jeton

    def _entetes_requete(self) -> dict[str, str]:
        """En-têtes HTTP : Bearer si un API Client est configuré."""
        jeton = self._obtenir_jeton()
        if not jeton:
            return {}
        return {"Authorization": f"Bearer {jeton}"}

    def _journaliser_credits(self, reponse: object) -> None:
        restants = extraire_credits_restants(reponse)
        if restants is not None:
            self._logger.info(
                "OpenSky X-Rate-Limit-Remaining : %s crédit(s).",
                restants,
            )

    def _interpreter_statut_http(
        self,
        reponse: object,
        *,
        accepter_404_vide: bool = False,
    ) -> None:
        """
        Interprète le code HTTP. Lève ErreurAPIOpenSky si l'appel a échoué.
        Un 404 n'est pas traité ici : l'appelant le convertit en liste vide.
        """
        statut = getattr(reponse, "status_code", None)
        self._journaliser_credits(reponse)
        if statut == 401:
            self._logger.error(
                "Authentification refusée par l'API OpenSky (code 401) : "
                "jeton OAuth absent, expiré ou API Client invalide "
                "(OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET)."
            )
            raise ErreurAPIOpenSky(
                "Authentification refusée (401) par l'API OpenSky Network."
            )
        if statut == 403:
            self._logger.error(
                "API OpenSky refuse l'accès (HTTP 403) : le mode d'auth "
                "n'est pas accepté. Activer un API Client sur le compte, "
                "puis un jeton Bearer (client id + secret). Le compte "
                "feeder et Trino ne débloquent pas /flights."
            )
            raise ErreurAPIOpenSky(
                "Accès refusé (403) par l'API OpenSky Network."
            )
        if statut == 429:
            attente = extraire_retry_after_secondes(reponse)
            if attente is not None:
                self._logger.error(
                    "Quota d'appels dépassé (code 429) sur l'API OpenSky Network "
                    "(Retry-After : %.0f s).",
                    attente,
                )
            else:
                self._logger.error(
                    "Quota d'appels dépassé (code 429) sur l'API OpenSky Network."
                )
            raise ErreurAPIOpenSky(
                "Quota d'appels dépassé (429) sur l'API OpenSky Network.",
                retry_after_secondes=attente,
            )
        if isinstance(statut, int) and statut >= 500:
            self._logger.error(
                "Erreur serveur côté OpenSky Network (code %s).", statut
            )
            raise ErreurAPIOpenSky(
                f"Erreur serveur ({statut}) sur l'API OpenSky Network."
            )
        if accepter_404_vide and statut == 404:
            return
        if statut != 200:
            self._logger.error(
                "Réponse HTTP inattendue (code %s) de l'API OpenSky Network.",
                statut,
            )
            raise ErreurAPIOpenSky(
                f"Réponse HTTP inattendue ({statut}) de l'API OpenSky Network."
            )

    def _requete_get(
        self,
        url: str,
        params: dict,
        *,
        accepter_404_vide: bool = False,
    ) -> object:
        """GET avec jeton Bearer (si configuré). Ne logue pas le jeton."""
        try:
            reponse = requests.get(
                url,
                params=params,
                headers=self._entetes_requete(),
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
        self._interpreter_statut_http(
            reponse, accepter_404_vide=accepter_404_vide
        )
        return reponse

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
        reponse = self._requete_get(url, parametres)
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

        reponse = self._requete_get(
            url, parametres, accepter_404_vide=True
        )

        if reponse.status_code == 404:
            self._logger.info(
                "Aucun vol sur /flights/%s pour %s (HTTP 404) : liste vide.",
                endpoint,
                icao_aeroport,
            )
            return []

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
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Client OpenSky OAuth2. Un seul appel smoke /flights/departure "
            "(un hub), pour ne pas brûler les 4000 crédits Standard."
        )
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Un GET /flights/departure (LFPG, ~2 h). N'affiche pas le secret.",
    )
    parser.add_argument("--hub", default="LFPG", help="Code ICAO du smoke test.")
    args = parser.parse_args()
    if not args.smoke:
        logger.info(
            "Aucun appel réseau. Pour un smoke unique : "
            "python -m src.ingestion.opensky_client --smoke"
        )
    else:
        client = OpenSkyClient()
        if client._client_id is None:
            logger.error(
                "OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET absents du .env : "
                "0 appel live. Remplir le .env (ne pas coller le secret ici), "
                "puis relancer --smoke."
            )
        else:
            fin = int(datetime.now(timezone.utc).timestamp())
            debut = fin - 2 * 60 * 60
            vols = client.recuperer_vols_depart(
                icao_aeroport=args.hub, debut=debut, fin=fin
            )
            logger.info(
                "Smoke /flights/departure %s : %s vol(s). Jeton non logué.",
                args.hub,
                len(vols),
            )
