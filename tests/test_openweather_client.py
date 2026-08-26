"""
Tests unitaires du module d'ingestion OpenWeather
(src/ingestion/openweather_client.py).

Ligne de raisonnement
----------------------
Aucun de ces tests ne doit effectuer de véritable appel réseau : on simule
(mock) systématiquement `requests.get` pour que les tests restent rapides,
déterministes et exécutables sans connexion internet ni dépendance à la
disponibilité de l'API OpenWeather.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import requests

from src.ingestion.openweather_client import (
    ErreurAPIOpenWeather,
    HubAeroportuaire,
    OpenWeatherClient,
)


def _construire_reponse_mock(mocker, status_code: int, contenu_json: dict | None = None):
    """Construit un objet réponse HTTP simulé avec le code et le JSON donnés."""
    reponse_mock = mocker.Mock()
    reponse_mock.status_code = status_code
    reponse_mock.json.return_value = contenu_json if contenu_json is not None else {}
    return reponse_mock


def test_recuperer_meteo_actuelle_appelle_url_et_parametres_attendus(mocker) -> None:
    """
    Vérifie que l'appel HTTP cible bien l'endpoint /weather, avec la
    latitude, la longitude et la clé API correctement transmises, ainsi que
    le timeout appliqué.
    """
    reponse_mock = _construire_reponse_mock(mocker, 200, {"main": {"temp": 18.5}})
    mock_get = mocker.patch(
        "src.ingestion.openweather_client.requests.get", return_value=reponse_mock
    )

    client = OpenWeatherClient()
    resultat = client.recuperer_meteo_actuelle(latitude=49.0097, longitude=2.5479)

    mock_get.assert_called_once()
    args_appel, kwargs_appel = mock_get.call_args

    assert args_appel[0] == "https://api.openweathermap.org/data/2.5/weather"
    assert kwargs_appel["params"]["lat"] == 49.0097
    assert kwargs_appel["params"]["lon"] == 2.5479
    assert kwargs_appel["params"]["units"] == "metric"
    assert kwargs_appel["timeout"] == 10
    assert resultat == {"main": {"temp": 18.5}}


def test_recuperer_meteo_actuelle_leve_exception_sur_timeout(mocker) -> None:
    """Vérifie qu'un Timeout réseau est bien transformé en ErreurAPIOpenWeather."""
    mocker.patch(
        "src.ingestion.openweather_client.requests.get",
        side_effect=requests.exceptions.Timeout,
    )

    client = OpenWeatherClient()

    with pytest.raises(ErreurAPIOpenWeather):
        client.recuperer_meteo_actuelle(latitude=49.0097, longitude=2.5479)


def test_recuperer_meteo_actuelle_leve_exception_sur_authentification_refusee(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 401 (clé API invalide ou non encore active)
    est bien transformée en ErreurAPIOpenWeather.
    """
    reponse_mock = _construire_reponse_mock(mocker, 401)
    mocker.patch(
        "src.ingestion.openweather_client.requests.get", return_value=reponse_mock
    )

    client = OpenWeatherClient()

    with pytest.raises(ErreurAPIOpenWeather):
        client.recuperer_meteo_actuelle(latitude=49.0097, longitude=2.5479)


def test_recuperer_meteo_actuelle_leve_exception_sur_quota_depasse(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 429 (quota d'appels dépassé) est bien
    transformée en ErreurAPIOpenWeather, plutôt que de retourner un JSON
    invalide.
    """
    reponse_mock = _construire_reponse_mock(mocker, 429)
    mocker.patch(
        "src.ingestion.openweather_client.requests.get", return_value=reponse_mock
    )

    client = OpenWeatherClient()

    with pytest.raises(ErreurAPIOpenWeather):
        client.recuperer_meteo_actuelle(latitude=49.0097, longitude=2.5479)


def test_recuperer_meteo_hubs_aeroportuaires_boucle_sur_chaque_hub(mocker) -> None:
    """
    Vérifie que la récupération multi-hubs effectue bien un appel par hub et
    associe correctement chaque résultat au nom et au code IATA attendus.
    """
    reponse_mock = _construire_reponse_mock(mocker, 200, {"main": {"temp": 15.0}})
    mock_get = mocker.patch(
        "src.ingestion.openweather_client.requests.get", return_value=reponse_mock
    )

    hubs_test = (
        HubAeroportuaire("Paris Charles-de-Gaulle", "CDG", 49.0097, 2.5479),
        HubAeroportuaire("Londres Heathrow", "LHR", 51.4700, -0.4543),
    )

    client = OpenWeatherClient()
    resultat = client.recuperer_meteo_hubs_aeroportuaires(hubs=hubs_test)

    assert mock_get.call_count == 2
    assert "horodatage_collecte" in resultat
    assert len(resultat["hubs"]) == 2
    assert resultat["hubs"][0]["code_iata"] == "CDG"
    assert resultat["hubs"][1]["code_iata"] == "LHR"
    assert resultat["hubs"][0]["meteo"] == {"main": {"temp": 15.0}}


def test_recuperer_meteo_hubs_aeroportuaires_horodatage_collecte_est_utc(mocker) -> None:
    """
    Vérifie que l'horodatage de collecte est un horodatage UTC (suffixe
    `+00:00` ou `Z`), et non une heure locale naïve.
    """
    reponse_mock = _construire_reponse_mock(mocker, 200, {"main": {"temp": 15.0}})
    mocker.patch(
        "src.ingestion.openweather_client.requests.get", return_value=reponse_mock
    )

    hubs_test = (
        HubAeroportuaire("Paris Charles-de-Gaulle", "CDG", 49.0097, 2.5479),
    )
    client = OpenWeatherClient()
    resultat = client.recuperer_meteo_hubs_aeroportuaires(hubs=hubs_test)

    horodatage = resultat["horodatage_collecte"]
    assert horodatage.endswith("+00:00") or horodatage.endswith("Z")

    normalise = horodatage.replace("Z", "+00:00")
    instant = datetime.fromisoformat(normalise)
    assert instant.tzinfo is not None
    assert instant.utcoffset() == timedelta(0)


def test_sauvegarder_donnees_brutes_cree_un_fichier_avec_le_bon_contenu(
    tmp_path: Path,
) -> None:
    """
    Vérifie que sauvegarder_donnees_brutes crée bien un fichier JSON, dans le
    dossier attendu, contenant exactement les données passées en argument.

    On utilise `tmp_path` (dossier temporaire fourni par pytest) plutôt que le
    vrai dossier data/raw du projet, afin de ne jamais polluer les données
    réelles pendant l'exécution des tests.
    """
    client = OpenWeatherClient()
    donnees = {"horodatage_collecte": "2026-08-25T10:00:00", "hubs": []}

    chemin_fichier_str = client.sauvegarder_donnees_brutes(donnees, dossier=str(tmp_path))
    chemin_fichier = Path(chemin_fichier_str)

    assert chemin_fichier.exists()
    assert chemin_fichier.parent == tmp_path
    assert chemin_fichier.name.startswith("openweather_")
    assert chemin_fichier.suffix == ".json"

    contenu_relu = json.loads(chemin_fichier.read_text(encoding="utf-8"))
    assert contenu_relu == donnees
