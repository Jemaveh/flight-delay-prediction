"""
Client Open-Meteo (séries horaires, sans clé API).

Repli : Historical Forecast, puis archive ERA5 (~5 jours de retard).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from src.ingestion.openweather_client import HUBS_AEROPORTUAIRES
from src.utils.chemins import chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

URL_HISTORICAL_FORECAST = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast"
)
URL_ARCHIVE_ERA5 = "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT_SECONDES = 60
HOURLY = (
    "temperature_2m,relative_humidity_2m,precipitation,"
    "wind_speed_10m,wind_gusts_10m,visibility"
)


class ErreurAPIOpenMeteo(Exception):
    """Échec d'un appel Open-Meteo."""


def _params_horaire(latitude: float, longitude: float, debut: date, fin: date) -> dict:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": debut.isoformat(),
        "end_date": fin.isoformat(),
        "hourly": HOURLY,
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }


class OpenMeteoClient:
    """Interroge Open-Meteo et enregistre un JSON brut par salve."""

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    def recuperer_serie_horaire(
        self,
        latitude: float,
        longitude: float,
        debut: date,
        fin: date,
    ) -> tuple[dict, str]:
        """
        Historical Forecast en priorité (jours récents).
        Repli ERA5 si l'endpoint précédent échoue.
        """
        params = _params_horaire(latitude, longitude, debut, fin)
        for url, source in (
            (URL_HISTORICAL_FORECAST, "historical-forecast"),
            (URL_ARCHIVE_ERA5, "archive-era5"),
        ):
            try:
                reponse = requests.get(url, params=params, timeout=TIMEOUT_SECONDES)
            except requests.RequestException as erreur:
                self._logger.warning("Open-Meteo %s injoignable : %s", source, erreur)
                continue
            if reponse.status_code != 200:
                self._logger.warning(
                    "Open-Meteo %s HTTP %s : %s",
                    source,
                    reponse.status_code,
                    reponse.text[:300],
                )
                continue
            try:
                payload = reponse.json()
            except ValueError as erreur:
                raise ErreurAPIOpenMeteo(
                    f"JSON Open-Meteo illisible ({source})."
                ) from erreur
            if not isinstance(payload, dict) or "hourly" not in payload:
                self._logger.warning("Open-Meteo %s : pas de clé hourly.", source)
                continue
            return payload, source
        raise ErreurAPIOpenMeteo(
            f"Aucune série horaire pour ({latitude}, {longitude}) "
            f"du {debut.isoformat()} au {fin.isoformat()}."
        )

    def recuperer_meteo_hubs(
        self,
        debut: date,
        fin: date,
    ) -> dict:
        """Un appel par hub de HUBS_AEROPORTUAIRES."""
        hubs: dict[str, dict] = {}
        source_commune: str | None = None
        for hub in HUBS_AEROPORTUAIRES:
            payload, source = self.recuperer_serie_horaire(
                hub.latitude, hub.longitude, debut, fin
            )
            if source_commune is None:
                source_commune = source
            elif source != source_commune:
                self._logger.warning(
                    "Hub %s servi par %s, les autres par %s.",
                    hub.code_icao,
                    source,
                    source_commune,
                )
            n_heures = len((payload.get("hourly") or {}).get("time") or [])
            self._logger.info(
                "Open-Meteo %s %s : %s pas horaires.",
                hub.code_icao,
                source,
                n_heures,
            )
            hubs[hub.code_icao] = {
                "nom": hub.nom,
                "latitude": hub.latitude,
                "longitude": hub.longitude,
                "source": source,
                "reponse": payload,
            }
        return {
            "horodatage_collecte": datetime.now(timezone.utc).isoformat(),
            "start_date": debut.isoformat(),
            "end_date": fin.isoformat(),
            "source_principale": source_commune,
            "hubs": hubs,
        }

    def sauvegarder_donnees_brutes(
        self, donnees: dict, dossier: str = "data/raw"
    ) -> Path:
        chemin_dossier = Path(dossier)
        chemin_dossier.mkdir(parents=True, exist_ok=True)
        horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
        chemin_fichier = chemin_dossier / f"openmeteo_{horodatage}.json"
        with chemin_fichier.open("w", encoding="utf-8") as fichier:
            json.dump(donnees, fichier, ensure_ascii=False, indent=2)
        self._logger.info(
            "Open-Meteo brut écrit dans '%s'.",
            chemin_relatif_projet(chemin_fichier),
        )
        return chemin_fichier
