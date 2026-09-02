"""
Module d'ingestion pour l'API NewsAPI (endpoint /v2/everything).

Ligne de raisonnement
----------------------
NewsAPI expose deux endpoints principaux : /v2/top-headlines, qui retourne
les gros titres du moment filtrés par pays, catégorie ou source, et
/v2/everything, qui permet une recherche par mots-clés arbitraires sur
l'ensemble des articles indexés. Seul /v2/everything répond au besoin de ce
projet : rechercher des actualités liées à des événements précis (grèves,
conditions météo extrêmes, perturbations du contrôle aérien, incidents
aéroportuaires) susceptibles d'impacter les vols, ce que /v2/top-headlines,
limité à un tri par catégorie/pays, ne permet pas.

Les appels sont effectués directement via la librairie `requests`, ce qui
rend explicite chaque aspect de la requête (timeout, gestion des erreurs,
authentification). La clé API est transmise en paramètre de requête
(`apiKey`), comme documenté par NewsAPI.

Le plan gratuit de NewsAPI impose deux contraintes qui structurent ce
module : les résultats sont limités aux articles publiés dans les
approximativement 30 derniers jours (toute requête portant sur une période
antérieure est rejetée par l'API avec un code 426), et le nombre d'appels est
plafonné à 100 requêtes par jour. Le module ne boucle donc que sur un petit
nombre de combinaisons mots-clés/langue prédéfinies (constante
REQUETES_ACTUALITES), plutôt que d'explorer exhaustivement toutes les langues
et tous les hubs aéroportuaires du projet.

L'endpoint /v2/everything ne retourne aucun champ indiquant la langue
détectée de chaque article : le paramètre `language` de la requête filtre les
résultats côté serveur, en amont, sur la base de la langue déclarée par
NewsAPI pour la source interrogée. Pour mesurer la répartition par langue du
corpus récupéré, chaque article est donc associé, lors de la collecte, à la
langue effectivement demandée par la requête qui l'a renvoyé, plutôt que
détecté a posteriori sur le contenu du texte.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from config.settings import settings
from src.utils.chemins import chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

URL_BASE_NEWSAPI = "https://newsapi.org/v2/everything"
TIMEOUT_SECONDES = 60

TAILLE_PAGE_DEFAUT = 100


@dataclass(frozen=True)
class RequeteActualites:
    """
    Représente une requête de recherche d'articles pour une combinaison
    mots-clés/langue donnée.

    Attributes
    ----------
    mots_cles : str
        Expression de recherche transmise au paramètre `q` de l'API (peut
        combiner plusieurs termes avec les opérateurs AND/OR/NOT).
    langue : str
        Code de langue ISO-639-1 à deux lettres attendu par le paramètre
        `language` de l'API (ex : "fr", "en").
    code_icao : str | None
        Hub ciblé (collecte ``--par-hub``). None pour les cinq requêtes
        génériques par langue.
    """

    mots_cles: str
    langue: str
    code_icao: str | None = None


# Petite liste de requêtes mots-clés/langue couvrant les événements les plus
# susceptibles d'impacter les vols (grèves, conditions météo extrêmes,
# perturbations du contrôle aérien, incidents aéroportuaires), dans les
# langues des principaux hubs aéroportuaires européens du projet (voir
# HUBS_AEROPORTUAIRES dans openweather_client.py). Une liste volontairement
# courte (cinq requêtes), compatible avec le quota de 100 requêtes/jour du
# plan gratuit NewsAPI.
REQUETES_ACTUALITES: tuple[RequeteActualites, ...] = (
    RequeteActualites(
        '"grève aéroport" OR "grève transport aérien" OR "contrôle aérien" OR "trafic aérien perturbé"',
        "fr",
    ),
    RequeteActualites(
        '"airport strike" OR "flight delay" OR "air traffic control" OR "airspace closure"',
        "en",
    ),
    RequeteActualites(
        '"Flughafen Streik" OR "Flugverspätung" OR "Fluglotsen Streik"',
        "de",
    ),
    RequeteActualites(
        '"huelga aeropuerto" OR "retraso vuelo" OR "control aéreo huelga"',
        "es",
    ),
    RequeteActualites(
        '"sciopero aeroporto" OR "ritardo volo" OR "controllo del traffico aereo"',
        "it",
    ),
)

# Une requête par hub (10 appels), pas 10 × 5 langues. AND aéroport/grève/vol
# pour limiter le bruit (Dublin, Istanbul, Madrid).
REQUETES_ACTUALITES_PAR_HUB: tuple[RequeteActualites, ...] = (
    RequeteActualites(
        '(CDG OR "Charles de Gaulle" OR Roissy) AND (aéroport OR grève OR vol OR retard)',
        "fr",
        "LFPG",
    ),
    RequeteActualites(
        "(LHR OR Heathrow) AND (airport OR strike OR delay OR flight)",
        "en",
        "EGLL",
    ),
    RequeteActualites(
        "(Frankfurt OR Francfort OR EDDF) AND (Flughafen OR Streik OR Flug)",
        "de",
        "EDDF",
    ),
    RequeteActualites(
        "(Schiphol OR EHAM) AND (airport OR strike OR delay OR flight OR luchthaven)",
        "en",
        "EHAM",
    ),
    RequeteActualites(
        "(Barajas OR LEMD) AND (aeropuerto OR huelga OR retraso OR vuelo)",
        "es",
        "LEMD",
    ),
    RequeteActualites(
        "(Fiumicino OR FCO OR LIRF) AND (aeroporto OR sciopero OR ritardo OR volo)",
        "it",
        "LIRF",
    ),
    RequeteActualites(
        '("Istanbul Airport" OR LTFM OR "Istanbul Havalimani") AND (strike OR delay OR flight OR airport)',
        "en",
        "LTFM",
    ),
    RequeteActualites(
        '("Dublin Airport" OR EIDW) AND (strike OR delay OR flight OR airport)',
        "en",
        "EIDW",
    ),
    RequeteActualites(
        "(München OR Munich OR EDDM) AND (Flughafen OR Streik OR Flug)",
        "de",
        "EDDM",
    ),
    RequeteActualites(
        '("El Prat" OR LEBL OR "aeroport Barcelona") AND (aeropuerto OR huelga OR retraso OR vuelo)',
        "es",
        "LEBL",
    ),
)


class ErreurAPINewsAPI(Exception):
    """
    Exception levée lorsque l'appel à l'API NewsAPI échoue.
    """


class NewsApiClient:
    """
    Module permettant d'interroger l'API NewsAPI et de sauvegarder les
    données brutes récupérées.
    """

    def __init__(self) -> None:
        """
        Initialise le module d'ingestion : prépare l'URL de base de l'API et
        la clé d'authentification lue depuis la configuration.
        """
        self._logger = get_logger(__name__)
        self._url_base = URL_BASE_NEWSAPI
        self._cle_api = settings.newsapi_key

    def rechercher_articles(
        self,
        mots_cles: str,
        langue: str | None = None,
        date_depuis: str | None = None,
        date_jusqua: str | None = None,
        taille_page: int = TAILLE_PAGE_DEFAUT,
    ) -> dict:
        """
        Interroge l'endpoint /v2/everything de l'API NewsAPI pour une
        expression de recherche donnée.

        Parameters
        ----------
        mots_cles : str
            Expression de recherche transmise au paramètre `q` de l'API.
            Peut combiner plusieurs termes avec les opérateurs AND/OR/NOT et
            des parenthèses de regroupement.
        langue : str | None
            Code de langue ISO-639-1 à deux lettres (ex : "fr", "en") pour
            restreindre les résultats à cette langue. Si None, l'API renvoie
            des articles dans toutes les langues qu'elle indexe.
        date_depuis : str | None
            Date la plus ancienne des articles recherchés, au format ISO 8601
            (ex : "2026-08-01"). Si None, l'API applique sa fenêtre par
            défaut. Sur le plan gratuit, toute date antérieure à environ 30
            jours dans le passé est rejetée (code 426).
        date_jusqua : str | None
            Date la plus récente des articles recherchés, au format ISO 8601
            (paramètre `to` de l'API). Si None, l'API s'arrête à l'instant
            présent.
        taille_page : int
            Nombre d'articles à récupérer en un seul appel (maximum 100
            imposé par l'API).

        Returns
        -------
        dict
            Le contenu JSON de la réponse, tel que retourné par l'API.

        Raises
        ------
        ErreurAPINewsAPI
            Si la requête échoue (timeout, erreur de connexion, ou code HTTP
            d'erreur retourné par l'API).
        """
        parametres: dict[str, str | int] = {
            "q": mots_cles,
            "apiKey": self._cle_api,
            "pageSize": taille_page,
            "sortBy": "publishedAt",
        }
        if langue is not None:
            parametres["language"] = langue
        if date_depuis is not None:
            parametres["from"] = date_depuis
        if date_jusqua is not None:
            parametres["to"] = date_jusqua

        try:
            reponse = requests.get(
                self._url_base,
                params=parametres,
                timeout=TIMEOUT_SECONDES,
            )
        except requests.exceptions.Timeout as erreur:
            self._logger.error(
                "Délai d'attente dépassé (%s secondes) lors de l'appel à l'API NewsAPI.",
                TIMEOUT_SECONDES,
            )
            raise ErreurAPINewsAPI(
                "Timeout lors de l'appel à l'API NewsAPI."
            ) from erreur
        except requests.exceptions.ConnectionError as erreur:
            self._logger.error(
                "Impossible de se connecter à l'API NewsAPI : %s", erreur
            )
            raise ErreurAPINewsAPI(
                "Erreur de connexion à l'API NewsAPI."
            ) from erreur

        if reponse.status_code == 401:
            self._logger.error(
                "Authentification refusée par l'API NewsAPI (code 401) : "
                "vérifier la clé API renseignée dans le fichier .env."
            )
            raise ErreurAPINewsAPI("Authentification refusée (401) par l'API NewsAPI.")

        if reponse.status_code == 400:
            self._logger.error(
                "Requête mal formée (code 400) envoyée à l'API NewsAPI : "
                "vérifier les paramètres transmis (mots-clés, langue, date)."
            )
            raise ErreurAPINewsAPI("Requête mal formée (400) envoyée à l'API NewsAPI.")

        if reponse.status_code == 426:
            self._logger.error(
                "Requête refusée (code 426) par l'API NewsAPI : la date "
                "demandée dépasse la fenêtre autorisée par le plan gratuit "
                "(environ 30 jours dans le passé)."
            )
            raise ErreurAPINewsAPI(
                "Requête trop ancienne (426) pour le plan gratuit de l'API NewsAPI."
            )

        if reponse.status_code == 429:
            self._logger.error(
                "Quota d'appels dépassé (code 429) sur l'API NewsAPI."
            )
            raise ErreurAPINewsAPI("Quota d'appels dépassé (429) sur l'API NewsAPI.")

        if reponse.status_code >= 500:
            self._logger.error(
                "Erreur serveur côté NewsAPI (code %s).", reponse.status_code
            )
            raise ErreurAPINewsAPI(
                f"Erreur serveur ({reponse.status_code}) sur l'API NewsAPI."
            )

        if reponse.status_code != 200:
            self._logger.error(
                "Réponse HTTP inattendue (code %s) de l'API NewsAPI.",
                reponse.status_code,
            )
            raise ErreurAPINewsAPI(
                f"Réponse HTTP inattendue ({reponse.status_code}) de l'API NewsAPI."
            )

        self._logger.info("Appel à l'API NewsAPI réussi (code 200).")
        return reponse.json()

    def recuperer_actualites_aeroportuaires(
        self,
        requetes: tuple[RequeteActualites, ...] = REQUETES_ACTUALITES,
        date_depuis: str | None = None,
        date_jusqua: str | None = None,
        taille_page: int = TAILLE_PAGE_DEFAUT,
    ) -> dict:
        """
        Interroge l'API NewsAPI pour chacune des requêtes mots-clés/langue
        données, et regroupe les résultats dans un seul jeu de données.

        Parameters
        ----------
        requetes : tuple[RequeteActualites, ...]
            La liste des requêtes à effectuer. Par défaut, les cinq requêtes
            mots-clés/langue définies dans REQUETES_ACTUALITES.
        date_depuis : str | None
            Date la plus ancienne des articles recherchés (voir
            `rechercher_articles`), appliquée à toutes les requêtes.
        date_jusqua : str | None
            Date la plus récente des articles recherchés (voir
            `rechercher_articles`), appliquée à toutes les requêtes.
        taille_page : int
            Nombre d'articles à récupérer par requête (voir
            `rechercher_articles`).

        Returns
        -------
        dict
            Un dictionnaire contenant un horodatage global UTC de la collecte
            et la liste des résultats par requête, chaque résultat étant
            enrichi des mots-clés et de la langue de la requête
            correspondante.

        Raises
        ------
        ErreurAPINewsAPI
            Si l'appel échoue pour une requête donnée, l'exception se
            propage immédiatement et interrompt la boucle.
        """
        resultats: list[dict] = []

        for requete in requetes:
            self._logger.info(
                "Récupération des actualités pour la requête '%s' (langue : %s).",
                requete.mots_cles,
                requete.langue,
            )
            resultat_requete = self.rechercher_articles(
                mots_cles=requete.mots_cles,
                langue=requete.langue,
                date_depuis=date_depuis,
                date_jusqua=date_jusqua,
                taille_page=taille_page,
            )
            resultats.append(
                {
                    "mots_cles": requete.mots_cles,
                    "langue_requete": requete.langue,
                    "code_icao": requete.code_icao,
                    "resultat": resultat_requete,
                }
            )

        return {
            "horodatage_collecte": datetime.now(timezone.utc).isoformat(),
            "requetes": resultats,
        }

    def sauvegarder_donnees_brutes(self, donnees: dict, dossier: str = "data/raw") -> str:
        """
        Sauvegarde les données brutes récupérées dans un fichier JSON horodaté.

        Parameters
        ----------
        donnees : dict
            Le contenu JSON à sauvegarder (typiquement le résultat de
            `recuperer_actualites_aeroportuaires`).
        dossier : str
            Le dossier de destination. Créé automatiquement s'il n'existe pas.

        Returns
        -------
        str
            Le chemin complet du fichier créé.
        """
        chemin_dossier = Path(dossier)
        chemin_dossier.mkdir(parents=True, exist_ok=True)

        horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
        chemin_fichier = chemin_dossier / f"newsapi_{horodatage}.json"

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
            "Passe NewsAPI : cinq requêtes par langue, ou --par-hub "
            "(10 requêtes, un hub chacune). Pas de pagination, pas de "
            "boucle par jour (quota 100 req/jour)."
        )
    )
    parser.add_argument(
        "--depuis",
        default=None,
        help="Date ISO la plus ancienne (paramètre from). Ex. : 2026-08-25.",
    )
    parser.add_argument(
        "--jusqua",
        default=None,
        help="Date ISO la plus récente (paramètre to). Ex. : 2026-09-01.",
    )
    parser.add_argument(
        "--par-hub",
        action="store_true",
        help="Dix requêtes (un hub, une langue). Ne pas croiser 10×5 langues.",
    )
    args = parser.parse_args()

    requetes = (
        REQUETES_ACTUALITES_PAR_HUB if args.par_hub else REQUETES_ACTUALITES
    )
    client = NewsApiClient()
    logger.info(
        "Collecte NewsAPI : %s requête(s), par_hub=%s, depuis=%s, jusqua=%s. "
        "Clé non loguée.",
        len(requetes),
        args.par_hub,
        args.depuis,
        args.jusqua,
    )
    donnees_actualites = client.recuperer_actualites_aeroportuaires(
        requetes=requetes,
        date_depuis=args.depuis,
        date_jusqua=args.jusqua,
    )
    chemin_sauvegarde = client.sauvegarder_donnees_brutes(donnees_actualites)
    logger.info(
        "Exécution manuelle terminée, fichier généré : '%s'.",
        chemin_relatif_projet(chemin_sauvegarde),
    )
