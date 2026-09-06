"""
Module d'ingestion pour l'API OpenWeather (Current Weather Data).

Ligne de raisonnement
----------------------
OpenWeather expose une API REST publique qui retourne, pour un point
géographique donné (latitude/longitude), les conditions météorologiques
actuelles (température, vent, pluie, visibilité, pression...). Contrairement
à OpenSky, qui interroge une zone géographique (bounding box) en un seul
appel, OpenWeather fonctionne par point : il faut donc effectuer un appel par
lieu que l'on souhaite documenter.

Pour ce projet, on s'intéresse à la météo au niveau des principaux hubs
aériens européens plutôt qu'à une zone géographique continue : la météo
pertinente pour la prédiction de retard est celle des aéroports de
départ/arrivée.
On définit donc une liste fixe de hubs (constante HUBS_AEROPORTUAIRES), et le
module boucle sur cette liste pour construire un jeu de données multi-
aéroports en plusieurs appels API.

Les appels sont effectués directement via la librairie `requests`, ce qui
rend explicite chaque aspect de la requête (timeout, gestion des erreurs,
authentification).
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

URL_BASE_OPENWEATHER = "https://api.openweathermap.org/data/2.5/weather"
TIMEOUT_SECONDES = 10

# Unités "metric" : température en degrés Celsius, vitesse du vent en mètres
# par seconde.
UNITES = "metric"
LANGUE = "fr"


@dataclass(frozen=True)
class HubAeroportuaire:
    """
    Représente un aéroport hub pour lequel on récupère la météo actuelle.

    Attributes
    ----------
    nom : str
        Nom usuel de l'aéroport.
    code_iata : str
        Code IATA à trois lettres de l'aéroport.
    code_icao : str
        Code ICAO à quatre lettres de l'aéroport.
    latitude : float
        Latitude du point de mesure météo.
    longitude : float
        Longitude du point de mesure météo.
    """

    nom: str
    code_iata: str
    code_icao: str
    latitude: float
    longitude: float


# Liste fixe des hubs aéroportuaires européens couverts par le projet.
HUBS_AEROPORTUAIRES: tuple[HubAeroportuaire, ...] = (
    HubAeroportuaire("Paris Charles-de-Gaulle", "CDG", "LFPG", 49.0097, 2.5479),
    HubAeroportuaire("Londres Heathrow", "LHR", "EGLL", 51.4700, -0.4543),
    HubAeroportuaire("Francfort", "FRA", "EDDF", 50.0379, 8.5622),
    HubAeroportuaire("Amsterdam Schiphol", "AMS", "EHAM", 52.3086, 4.7639),
    HubAeroportuaire("Madrid Barajas", "MAD", "LEMD", 40.4983, -3.5676),
    HubAeroportuaire("Rome Fiumicino", "FCO", "LIRF", 41.8003, 12.2389),
    HubAeroportuaire("Istanbul", "IST", "LTFM", 41.2753, 28.7519),
    HubAeroportuaire("Dublin", "DUB", "EIDW", 53.4213, -6.2701),
    HubAeroportuaire("Munich", "MUC", "EDDM", 48.3538, 11.7861),
    HubAeroportuaire("Barcelone", "BCN", "LEBL", 41.2974, 2.0833),
)


class ErreurAPIOpenWeather(Exception):
    """
    Exception levée lorsque l'appel à l'API OpenWeather échoue.
    """


class OpenWeatherClient:
    """
    Module permettant d'interroger l'API OpenWeather et de sauvegarder les
    données brutes récupérées.
    """

    def __init__(self) -> None:
        """
        Initialise le module d'ingestion : prépare l'URL de base de l'API et
        la clé d'authentification lue depuis la configuration.
        """
        self._logger = get_logger(__name__)
        self._url_base = URL_BASE_OPENWEATHER
        self._cle_api = settings.openweather_api_key

    def recuperer_meteo_actuelle(self, latitude: float, longitude: float) -> dict:
        """
        Interroge l'API OpenWeather pour un point géographique donné.

        Parameters
        ----------
        latitude : float
            Latitude du point de mesure.
        longitude : float
            Longitude du point de mesure.

        Returns
        -------
        dict
            Le contenu JSON de la réponse, tel que retourné par l'API.

        Raises
        ------
        ErreurAPIOpenWeather
            Si la requête échoue (timeout, erreur de connexion, ou code HTTP
            d'erreur retourné par l'API).
        """
        parametres = {
            "lat": latitude,
            "lon": longitude,
            "appid": self._cle_api,
            "units": UNITES,
            "lang": LANGUE,
        }

        try:
            reponse = requests.get(
                self._url_base,
                params=parametres,
                timeout=TIMEOUT_SECONDES,
            )
        except requests.exceptions.Timeout as erreur:
            self._logger.error(
                "Délai d'attente dépassé (%s secondes) lors de l'appel à l'API OpenWeather.",
                TIMEOUT_SECONDES,
            )
            raise ErreurAPIOpenWeather(
                "Timeout lors de l'appel à l'API OpenWeather."
            ) from erreur
        except requests.exceptions.ConnectionError as erreur:
            self._logger.error(
                "Impossible de se connecter à l'API OpenWeather : %s", erreur
            )
            raise ErreurAPIOpenWeather(
                "Erreur de connexion à l'API OpenWeather."
            ) from erreur

        if reponse.status_code == 401:
            self._logger.error(
                "Authentification refusée par l'API OpenWeather (code 401) : "
                "vérifier la clé API renseignée dans le fichier .env."
            )
            raise ErreurAPIOpenWeather("Authentification refusée (401) par l'API OpenWeather.")

        if reponse.status_code == 429:
            self._logger.error(
                "Quota d'appels dépassé (code 429) sur l'API OpenWeather."
            )
            raise ErreurAPIOpenWeather("Quota d'appels dépassé (429) sur l'API OpenWeather.")

        if reponse.status_code >= 500:
            self._logger.error(
                "Erreur serveur côté OpenWeather (code %s).", reponse.status_code
            )
            raise ErreurAPIOpenWeather(
                f"Erreur serveur ({reponse.status_code}) sur l'API OpenWeather."
            )

        if reponse.status_code != 200:
            self._logger.error(
                "Réponse HTTP inattendue (code %s) de l'API OpenWeather.",
                reponse.status_code,
            )
            raise ErreurAPIOpenWeather(
                f"Réponse HTTP inattendue ({reponse.status_code}) de l'API OpenWeather."
            )

        self._logger.info("Appel à l'API OpenWeather réussi (code 200).")
        return reponse.json()

    def recuperer_meteo_hubs_aeroportuaires(
        self, hubs: tuple[HubAeroportuaire, ...] = HUBS_AEROPORTUAIRES
    ) -> dict:
        """
        Interroge l'API OpenWeather pour chacun des hubs aéroportuaires
        donnés, et regroupe les résultats dans un seul jeu de données.

        Parameters
        ----------
        hubs : tuple[HubAeroportuaire, ...]
            La liste des hubs à interroger. Par défaut, les dix hubs
            aéroportuaires européens définis dans HUBS_AEROPORTUAIRES.

        Returns
        -------
        dict
            Un dictionnaire contenant un horodatage global UTC de la collecte
            et la liste des résultats par hub, chaque résultat étant enrichi
            du nom, du code IATA et du code ICAO de l'aéroport correspondant.

        Raises
        ------
        ErreurAPIOpenWeather
            Si l'appel échoue pour un hub donné, l'exception se propage
            immédiatement et interrompt la boucle.
        """
        resultats: list[dict] = []

        for hub in hubs:
            self._logger.info(
                "Récupération de la météo pour %s (%s).", hub.nom, hub.code_iata
            )
            meteo_hub = self.recuperer_meteo_actuelle(hub.latitude, hub.longitude)
            resultats.append(
                {
                    "nom_aeroport": hub.nom,
                    "code_iata": hub.code_iata,
                    "code_icao": hub.code_icao,
                    "meteo": meteo_hub,
                }
            )

        return {
            "horodatage_collecte": datetime.now(timezone.utc).isoformat(),
            "hubs": resultats,
        }

    def sauvegarder_donnees_brutes(self, donnees: dict, dossier: str = "data/raw") -> str:
        """
        Sauvegarde les données brutes récupérées dans un fichier JSON horodaté.

        Parameters
        ----------
        donnees : dict
            Le contenu JSON à sauvegarder (typiquement le résultat de
            `recuperer_meteo_hubs_aeroportuaires`).
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
        chemin_fichier = chemin_dossier / f"openweather_{horodatage}.json"

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
    # Exemple d'utilisation : récupération de la météo actuelle pour
    # les dix hubs aéroportuaires européens, puis sauvegarde du résultat brut
    # dans data/raw/. Utile pour une vérification rapide du module sans
    # passer par les tests automatisés.
    client = OpenWeatherClient()

    donnees_meteo = client.recuperer_meteo_hubs_aeroportuaires()
    chemin_sauvegarde = client.sauvegarder_donnees_brutes(donnees_meteo)
    logger.info(
        "Exécution manuelle terminée, fichier généré : '%s'.",
        chemin_relatif_projet(chemin_sauvegarde),
    )
