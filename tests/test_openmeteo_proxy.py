"""
Tests Open-Meteo (mock HTTP) et proxy de retard sans fuite train→test.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
import requests

from src.ingestion.openmeteo_client import (
    URL_HISTORICAL_FORECAST,
    ErreurAPIOpenMeteo,
    OpenMeteoClient,
)
from src.processing.meteo_archive import (
    hourly_vers_dataframe,
    joindre_meteo_horaire,
    retard_sans_fuite,
)


def _reponse_horaire() -> dict:
    return {
        "hourly": {
            "time": ["2026-08-25T10:00", "2026-08-25T11:00"],
            "temperature_2m": [18.0, 19.5],
            "relative_humidity_2m": [70, 68],
            "precipitation": [0.0, 1.2],
            "wind_speed_10m": [3.0, 5.0],
            "wind_gusts_10m": [5.0, 8.0],
            "visibility": [10000, 8000],
        }
    }


def test_recuperer_serie_horaire_cible_historical_forecast(mocker) -> None:
    """Vérifie l'URL Open-Meteo, les dates et l'unité de vent en m/s."""
    reponse = mocker.Mock()
    reponse.status_code = 200
    reponse.json.return_value = _reponse_horaire()
    mock_get = mocker.patch(
        "src.ingestion.openmeteo_client.requests.get", return_value=reponse
    )
    payload, source = OpenMeteoClient().recuperer_serie_horaire(
        49.0097, 2.5479, date(2026, 8, 25), date(2026, 9, 2)
    )
    mock_get.assert_called()
    args, kwargs = mock_get.call_args
    assert args[0] == URL_HISTORICAL_FORECAST
    assert kwargs["params"]["start_date"] == "2026-08-25"
    assert kwargs["params"]["end_date"] == "2026-09-02"
    assert kwargs["params"]["wind_speed_unit"] == "ms"
    assert kwargs["params"]["timezone"] == "UTC"
    assert source == "historical-forecast"
    assert payload["hourly"]["temperature_2m"][0] == 18.0


def test_recuperer_serie_horaire_replie_vers_era5(mocker) -> None:
    """Si Historical Forecast échoue, l'archive ERA5 est interrogée."""
    ko = mocker.Mock()
    ko.status_code = 400
    ko.text = "unavailable"
    ok = mocker.Mock()
    ok.status_code = 200
    ok.json.return_value = _reponse_horaire()
    mocker.patch(
        "src.ingestion.openmeteo_client.requests.get", side_effect=[ko, ok]
    )
    _payload, source = OpenMeteoClient().recuperer_serie_horaire(
        49.0, 2.5, date(2026, 8, 25), date(2026, 8, 26)
    )
    assert source == "archive-era5"


def test_recuperer_serie_horaire_timeout(mocker) -> None:
    mocker.patch(
        "src.ingestion.openmeteo_client.requests.get",
        side_effect=requests.exceptions.Timeout,
    )
    with pytest.raises(ErreurAPIOpenMeteo):
        OpenMeteoClient().recuperer_serie_horaire(
            49.0, 2.5, date(2026, 8, 25), date(2026, 8, 26)
        )


def test_hourly_vers_dataframe_aligne_les_heures() -> None:
    cadre = hourly_vers_dataframe("LFPG", _reponse_horaire())
    assert len(cadre) == 2
    assert cadre.iloc[0]["icao"] == "LFPG"
    assert cadre.iloc[0]["temperature_celsius"] == pytest.approx(18.0)
    assert cadre.iloc[1]["rain_1h"] == pytest.approx(1.2)


def test_joindre_ecrase_la_meteo_openweather() -> None:
    """La série Open-Meteo remplace les colonnes OpenWeather déjà présentes."""
    vols = pd.DataFrame(
        [
            {
                "est_departure_airport": "LFPG",
                "est_arrival_airport": "EGLL",
                "first_seen": datetime(2026, 8, 25, 10, 20, tzinfo=timezone.utc),
                "last_seen": datetime(2026, 8, 25, 11, 40, tzinfo=timezone.utc),
                "temperature_origine": 99.0,
            }
        ]
    )
    series = hourly_vers_dataframe("LFPG", _reponse_horaire())
    series = pd.concat(
        [series, hourly_vers_dataframe("EGLL", _reponse_horaire())],
        ignore_index=True,
    )
    out = joindre_meteo_horaire(vols, series)
    assert out.iloc[0]["temperature_origine"] == pytest.approx(18.0)
    assert out.iloc[0]["temperature_dest"] == pytest.approx(19.5)


def test_retard_sans_fuite_ignore_le_test_dans_la_mediane() -> None:
    """Un vol test très long ne doit pas tirer la médiane de route."""
    def _vol(jour: int, heure: int, duree: float, ident: int) -> dict:
        debut = datetime(2026, 8, jour, heure, tzinfo=timezone.utc)
        return {
            "est_departure_airport": "LFPG",
            "est_arrival_airport": "EGLL",
            "first_seen": debut,
            "duree_minutes": duree,
            "flight_id": ident,
        }

    train = pd.DataFrame([_vol(25, 8 + i, 80.0, i) for i in range(6)])
    test = pd.DataFrame([_vol(26, 10, 200.0, 99)])
    train_p, test_p = retard_sans_fuite(train, test, seuil_min=5)
    assert train_p["mediane_route_train"].iloc[0] == pytest.approx(80.0)
    assert test_p["retard_sans_fuite"].iloc[0] == pytest.approx(120.0)


def test_retard_sans_fuite_ecarte_les_od_trop_rares() -> None:
    train = pd.DataFrame(
        {
            "est_departure_airport": ["LFPG", "LFPG"],
            "est_arrival_airport": ["EGLL", "LEMD"],
            "duree_minutes": [80.0, 90.0],
        }
    )
    test = train.copy()
    with pytest.raises(ValueError, match="assez de vols"):
        retard_sans_fuite(train, test, seuil_min=5)


def test_sauvegarde_json_openmeteo(tmp_path: Path, mocker) -> None:
    reponse = mocker.Mock()
    reponse.status_code = 200
    reponse.json.return_value = _reponse_horaire()
    mocker.patch(
        "src.ingestion.openmeteo_client.requests.get", return_value=reponse
    )
    client = OpenMeteoClient()
    payload, _source = client.recuperer_serie_horaire(
        49.0, 2.5, date(2026, 8, 25), date(2026, 8, 26)
    )
    chemin = client.sauvegarder_donnees_brutes(
        {"hubs": {"LFPG": {"reponse": payload}}}, dossier=str(tmp_path)
    )
    assert chemin.name.startswith("openmeteo_")
    assert chemin.is_file()
