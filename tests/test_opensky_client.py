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
    TIMEOUT_SECONDES,
    URL_JETON_OPENSKY,
    construire_enveloppe_vols,
    extraire_credits_restants,
    extraire_retry_after_secondes,
    oauth_est_configure,
)


def _construire_reponse_mock(mocker, status_code: int, contenu_json: dict | None = None):
    """Construit un objet réponse HTTP simulé avec le code et le JSON donnés."""
    reponse_mock = mocker.Mock()
    reponse_mock.status_code = status_code
    reponse_mock.json.return_value = contenu_json if contenu_json is not None else {}
    reponse_mock.headers = {}
    return reponse_mock


@pytest.fixture(autouse=True)
def _oauth_inactif_dans_les_tests(mocker):
    """Les tests restent anonymes, indépendamment du .env local."""
    mocker.patch("src.ingestion.opensky_client.settings.opensky_client_id", "")
    mocker.patch("src.ingestion.opensky_client.settings.opensky_client_secret", "")


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
    assert kwargs_appel["timeout"] == TIMEOUT_SECONDES
    assert "auth" not in kwargs_appel
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
    assert kwargs_appel["timeout"] == TIMEOUT_SECONDES
    assert "auth" not in kwargs_appel
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
    assert kwargs_appel["timeout"] == TIMEOUT_SECONDES
    assert resultat == vols_mock


def test_recuperer_vols_depart_leve_exception_sur_quota_depasse(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 429 (quota d'appels dépassé) sur l'endpoint
    /flights/departure est bien transformée en ErreurAPIOpenSky.
    """
    reponse_mock = _construire_reponse_mock(mocker, 429)
    reponse_mock.headers = {"Retry-After": "45"}
    mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_mock
    )

    client = OpenSkyClient()

    with pytest.raises(ErreurAPIOpenSky) as captured:
        client.recuperer_vols_depart(icao_aeroport="LFPG", debut=1000, fin=2000)
    assert captured.value.retry_after_secondes == 45.0


def test_extraire_retry_after_secondes_absent_ou_invalide(mocker) -> None:
    """Vérifie que Retry-After absent ou non numérique donne None."""
    sans_entete = _construire_reponse_mock(mocker, 429)
    sans_entete.headers = {}
    assert extraire_retry_after_secondes(sans_entete) is None

    http_date = _construire_reponse_mock(mocker, 429)
    http_date.headers = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
    assert extraire_retry_after_secondes(http_date) is None


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


def test_oauth_client_credentials_puis_bearer(mocker) -> None:
    """Vérifie le POST token puis le GET avec Authorization Bearer."""
    mocker.patch(
        "src.ingestion.opensky_client.settings.opensky_client_id",
        "demo-api-client",
    )
    mocker.patch(
        "src.ingestion.opensky_client.settings.opensky_client_secret",
        "demo-secret",
    )
    reponse_token = mocker.Mock()
    reponse_token.status_code = 200
    reponse_token.json.return_value = {
        "access_token": "jeton-test",
        "expires_in": 1800,
    }
    reponse_token.headers = {}
    mock_post = mocker.patch(
        "src.ingestion.opensky_client.requests.post", return_value=reponse_token
    )
    reponse_get = _construire_reponse_mock(mocker, 200, {"states": []})
    reponse_get.headers = {"X-Rate-Limit-Remaining": "3999"}
    mock_get = mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_get
    )

    client = OpenSkyClient()
    client.recuperer_vols_en_temps_reel()
    client.recuperer_vols_en_temps_reel()

    mock_post.assert_called_once()
    assert mock_post.call_args[0][0] == URL_JETON_OPENSKY
    assert mock_post.call_args[1]["data"]["grant_type"] == "client_credentials"
    assert mock_post.call_args[1]["data"]["client_id"] == "demo-api-client"
    assert mock_get.call_count == 2
    assert mock_get.call_args[1]["headers"]["Authorization"] == "Bearer jeton-test"
    assert "auth" not in mock_get.call_args[1]


def test_flights_leve_exception_sur_403(mocker) -> None:
    """Vérifie qu'un HTTP 403 sur /flights/departure lève ErreurAPIOpenSky."""
    reponse_mock = _construire_reponse_mock(mocker, 403)
    mocker.patch(
        "src.ingestion.opensky_client.requests.get", return_value=reponse_mock
    )
    client = OpenSkyClient()
    with pytest.raises(ErreurAPIOpenSky, match="403"):
        client.recuperer_vols_depart(icao_aeroport="LFPG", debut=1000, fin=2000)


def test_extraire_credits_restants_et_oauth_est_configure() -> None:
    """Vérifie l'en-tête de crédits et le filtre des placeholders OAuth."""
    reponse = type("R", (), {"headers": {"X-Rate-Limit-Remaining": "4000"}})()
    assert extraire_credits_restants(reponse) == 4000
    assert oauth_est_configure("id-reel", "secret-reel") is True
    assert oauth_est_configure("identifiant_client_opensky", "secret-reel") is False
    assert oauth_est_configure("", "") is False
