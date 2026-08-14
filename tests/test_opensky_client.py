"""
Tests unitaires du client d'ingestion OpenSky Network
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

from src.ingestion.opensky_client import ErreurAPIOpenSky, OpenSkyClient


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
