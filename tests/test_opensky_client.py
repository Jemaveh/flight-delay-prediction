"""
Tests unitaires du module d'ingestion OpenSky Network
(src/ingestion/opensky_client.py).

Ligne de raisonnement
----------------------
Aucun de ces tests ne doit effectuer de véritable appel réseau : on simule
(mock) systématiquement `requests.get` pour que les tests restent rapides,
déterministes et exécutables sans connexion internet ni dépendance à la
disponibilité de l'API OpenSky Network.
"""

import json
from pathlib import Path

import pytest
import requests

from src.ingestion.opensky_client import (
    ErreurAPIOpenSky,
    OpenSkyClient,
    construire_enveloppe_vols,
)


def _construire_reponse_mock(mocker, status_code: int, contenu_json: dict | None = None):
    """Construit un objet réponse HTTP simulé avec le code et le JSON donnés."""
    reponse_mock = mocker.Mock()
    reponse_mock.status_code = status_code
    reponse_mock.json.return_value = contenu_json if contenu_json is not None else {}
    return reponse_mock


def test_recuperer_vols_appelle_url_et_parametres_attendus(mocker) -> None:
    """
    Vérifie que l'appel HTTP cible bien l'endpoint /states/all, avec les
    paramètres de bounding box correctement transmis et le timeout appliqué.
    """
    reponse_mock = _construire_reponse_mock(mocker, 200, {"states": []})
    mock_get = mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_mock
    )

    client = OpenSkyClient()
    bbox = (41.0, -5.0, 51.5, 10.0)
    resultat = client.recuperer_vols_en_temps_reel(bbox=bbox)

    mock_get.assert_called_once()
    args_appel, kwargs_appel = mock_get.call_args

    assert args_appel[0] == "https://opensky-network.org/api/states/all"
    assert kwargs_appel["params"] == {
        "lamin": 41.0,
        "lomin": -5.0,
        "lamax": 51.5,
        "lomax": 10.0,
    }
    assert kwargs_appel["timeout"] == 10
    assert resultat == {"states": []}


def test_recuperer_vols_leve_exception_sur_timeout(mocker) -> None:
    """Vérifie qu'un Timeout réseau est bien transformé en ErreurAPIOpenSky."""
    mocker.patch(
        "src.ingestion.opensky_client.requests.get",
        side_effect=requests.exceptions.Timeout,
    )

    client = OpenSkyClient()

    with pytest.raises(ErreurAPIOpenSky):
        client.recuperer_vols_en_temps_reel()


def test_recuperer_vols_leve_exception_sur_quota_depasse(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 429 (quota d'appels dépassé) est bien
    transformée en ErreurAPIOpenSky, plutôt que de retourner un JSON invalide.
    """
    reponse_mock = _construire_reponse_mock(mocker, 429)
    mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_mock
    )

    client = OpenSkyClient()

    with pytest.raises(ErreurAPIOpenSky):
        client.recuperer_vols_en_temps_reel()


def test_recuperer_vols_depart_appelle_url_et_parametres_attendus(mocker) -> None:
    """
    Vérifie que l'appel HTTP cible bien l'endpoint /flights/departure, avec
    le code ICAO, les timestamps et le timeout correctement transmis, et que
    le paramètre Python `fin` est bien mappé sur le paramètre HTTP `end`.
    """
    vols_mock = [{"icao24": "abc123", "estDepartureAirport": "LFPG"}]
    reponse_mock = _construire_reponse_mock(mocker, 200, vols_mock)
    mock_get = mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_mock
    )

    client = OpenSkyClient()
    resultat = client.recuperer_vols_depart(icao_aeroport="LFPG", debut=1000, fin=2000)

    mock_get.assert_called_once()
    args_appel, kwargs_appel = mock_get.call_args

    assert args_appel[0] == "https://opensky-network.org/api/flights/departure"
    assert kwargs_appel["params"] == {"airport": "LFPG", "begin": 1000, "end": 2000}
    assert kwargs_appel["timeout"] == 10
    assert resultat == vols_mock


def test_recuperer_vols_arrivee_appelle_url_et_parametres_attendus(mocker) -> None:
    """
    Vérifie que l'appel HTTP cible bien l'endpoint /flights/arrival, avec le
    code ICAO, les timestamps et le timeout correctement transmis.
    """
    vols_mock = [{"icao24": "def456", "estArrivalAirport": "LFPG"}]
    reponse_mock = _construire_reponse_mock(mocker, 200, vols_mock)
    mock_get = mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_mock
    )

    client = OpenSkyClient()
    resultat = client.recuperer_vols_arrivee(icao_aeroport="LFPG", debut=1000, fin=2000)

    mock_get.assert_called_once()
    args_appel, kwargs_appel = mock_get.call_args

    assert args_appel[0] == "https://opensky-network.org/api/flights/arrival"
    assert kwargs_appel["params"] == {"airport": "LFPG", "begin": 1000, "end": 2000}
    assert kwargs_appel["timeout"] == 10
    assert resultat == vols_mock


def test_recuperer_vols_depart_leve_exception_sur_quota_depasse(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 429 (quota d'appels dépassé) sur l'endpoint
    /flights/departure est bien transformée en ErreurAPIOpenSky.
    """
    reponse_mock = _construire_reponse_mock(mocker, 429)
    mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_mock
    )

    client = OpenSkyClient()

    with pytest.raises(ErreurAPIOpenSky):
        client.recuperer_vols_depart(icao_aeroport="LFPG", debut=1000, fin=2000)


def test_recuperer_vols_arrivee_leve_exception_sur_timeout(mocker) -> None:
    """Vérifie qu'un Timeout réseau sur /flights/arrival lève ErreurAPIOpenSky."""
    mocker.patch(
        "src.ingestion.opensky_client.requests.get",
        side_effect=requests.exceptions.Timeout,
    )

    client = OpenSkyClient()

    with pytest.raises(ErreurAPIOpenSky):
        client.recuperer_vols_arrivee(icao_aeroport="LFPG", debut=1000, fin=2000)


def test_recuperer_vols_depart_leve_value_error_si_intervalle_trop_long(mocker) -> None:
    """
    Vérifie que dépasser l'intervalle maximal de 7 jours (604800 secondes)
    entre `debut` et `fin` lève une ValueError sans effectuer d'appel réseau.
    """
    mock_get = mocker.patch("src.ingestion.opensky_client.requests.get")

    client = OpenSkyClient()
    debut = 0
    fin = 604800 + 1

    with pytest.raises(ValueError):
        client.recuperer_vols_depart(icao_aeroport="LFPG", debut=debut, fin=fin)

    mock_get.assert_not_called()


def test_recuperer_vols_arrivee_leve_value_error_si_intervalle_trop_long(mocker) -> None:
    """
    Vérifie que la même contrainte de 7 jours maximum s'applique à
    /flights/arrival, sans effectuer d'appel réseau.
    """
    mock_get = mocker.patch("src.ingestion.opensky_client.requests.get")

    client = OpenSkyClient()
    debut = 0
    fin = 604800 + 1

    with pytest.raises(ValueError):
        client.recuperer_vols_arrivee(icao_aeroport="LFPG", debut=debut, fin=fin)

    mock_get.assert_not_called()


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
    client = OpenSkyClient()
    donnees = {"states": [["abc123", "AF1234", "France"]]}

    chemin_fichier_str = client.sauvegarder_donnees_brutes(donnees, dossier=str(tmp_path))
    chemin_fichier = Path(chemin_fichier_str)

    assert chemin_fichier.exists()
    assert chemin_fichier.parent == tmp_path
    assert chemin_fichier.name.startswith("opensky_")
    assert chemin_fichier.suffix == ".json"

    contenu_relu = json.loads(chemin_fichier.read_text(encoding="utf-8"))
    assert contenu_relu == donnees


def test_recuperer_vols_depart_retourne_liste_vide_sur_404(mocker) -> None:
    """
    Vérifie qu'un HTTP 404 sur /flights/departure est traité comme une liste
    vide, et non comme une erreur.
    """
    reponse_mock = _construire_reponse_mock(mocker, 404)
    mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_mock
    )

    client = OpenSkyClient()
    resultat = client.recuperer_vols_depart(
        icao_aeroport="LFPG", debut=1000, fin=2000
    )

    assert resultat == []


def test_construire_enveloppe_vols_porte_la_liste_et_les_metadonnees() -> None:
    """
    Vérifie l'enveloppe JSON des vols : endpoint, aéroport, bornes, effectif.
    """
    vols = [{"icao24": "abc123"}]
    enveloppe = construire_enveloppe_vols(
        vols, endpoint="departure", icao_aeroport="LFPG", debut=10, fin=20
    )

    assert enveloppe["endpoint"] == "departure"
    assert enveloppe["airport"] == "LFPG"
    assert enveloppe["begin"] == 10
    assert enveloppe["end"] == 20
    assert enveloppe["nb_vols"] == 1
    assert enveloppe["vols"] == vols
    assert enveloppe["horodatage_collecte"].endswith("+00:00") or "Z" in enveloppe[
        "horodatage_collecte"
    ]


def test_sauvegarder_vols_utilise_le_prefixe_flights(tmp_path: Path) -> None:
    """
    Vérifie que sauvegarder_vols écrit un fichier opensky_flights_* contenant
    l'enveloppe, pas un snapshot /states/all.
    """
    client = OpenSkyClient()
    chemin = client.sauvegarder_vols(
        [{"icao24": "abc123"}],
        endpoint="arrival",
        icao_aeroport="EGLL",
        debut=1,
        fin=2,
        dossier=str(tmp_path),
    )
    fichier = Path(chemin)
    assert fichier.name.startswith("opensky_flights_arrival_EGLL_")
    contenu = json.loads(fichier.read_text(encoding="utf-8"))
    assert contenu["airport"] == "EGLL"
    assert contenu["endpoint"] == "arrival"
    assert contenu["nb_vols"] == 1
