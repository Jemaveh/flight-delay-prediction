"""
Tests unitaires du module d'ingestion NewsAPI
(src/ingestion/newsapi_client.py).

Ligne de raisonnement
----------------------
Aucun de ces tests ne doit effectuer de véritable appel réseau : on simule
(mock) systématiquement `requests.get` pour que les tests restent rapides,
déterministes et exécutables sans connexion internet ni dépendance à la
disponibilité ou au quota de l'API NewsAPI.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import requests

from src.ingestion.newsapi_client import (
    ErreurAPINewsAPI,
    NewsApiClient,
    RequeteActualites,
)


def _construire_reponse_mock(mocker, status_code: int, contenu_json: dict | None = None):
    """Construit un objet réponse HTTP simulé avec le code et le JSON donnés."""
    reponse_mock = mocker.Mock()
    reponse_mock.status_code = status_code
    reponse_mock.json.return_value = contenu_json if contenu_json is not None else {}
    return reponse_mock


def test_rechercher_articles_appelle_url_et_parametres_attendus(mocker) -> None:
    """
    Vérifie que l'appel HTTP cible bien l'endpoint /v2/everything, avec les
    mots-clés, la langue, la date et la taille de page correctement
    transmis, ainsi que le timeout appliqué.
    """
    reponse_mock = _construire_reponse_mock(mocker, 200, {"status": "ok", "articles": []})
    mock_get = mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    client = NewsApiClient()
    resultat = client.rechercher_articles(
        mots_cles='"airport strike"',
        langue="en",
        date_depuis="2026-08-01",
        taille_page=50,
    )

    mock_get.assert_called_once()
    args_appel, kwargs_appel = mock_get.call_args

    assert args_appel[0] == "https://newsapi.org/v2/everything"
    assert kwargs_appel["params"]["q"] == '"airport strike"'
    assert kwargs_appel["params"]["language"] == "en"
    assert kwargs_appel["params"]["from"] == "2026-08-01"
    assert "to" not in kwargs_appel["params"]
    assert kwargs_appel["params"]["pageSize"] == 50
    assert kwargs_appel["timeout"] == 60
    assert resultat == {"status": "ok", "articles": []}


def test_rechercher_articles_transmet_date_jusqua_en_parametre_to(mocker) -> None:
    """Vérifie que date_jusqua est envoyée comme paramètre `to` de l'API."""
    reponse_mock = _construire_reponse_mock(mocker, 200, {"status": "ok", "articles": []})
    mock_get = mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    client = NewsApiClient()
    client.rechercher_articles(
        mots_cles='"flight delay"',
        langue="en",
        date_depuis="2026-08-25",
        date_jusqua="2026-09-01",
    )

    _, kwargs_appel = mock_get.call_args
    assert kwargs_appel["params"]["from"] == "2026-08-25"
    assert kwargs_appel["params"]["to"] == "2026-09-01"


def test_rechercher_articles_sans_langue_ni_date_omet_ces_parametres(mocker) -> None:
    """
    Vérifie que les paramètres `language` et `from` ne sont pas transmis à
    l'API lorsqu'ils ne sont pas fournis, plutôt que d'envoyer une valeur
    None qui serait interprétée à tort par l'API.
    """
    reponse_mock = _construire_reponse_mock(mocker, 200, {"status": "ok", "articles": []})
    mock_get = mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    client = NewsApiClient()
    client.rechercher_articles(mots_cles="flight delay")

    _, kwargs_appel = mock_get.call_args
    assert "to" not in kwargs_appel["params"]
    assert "language" not in kwargs_appel["params"]
    assert "from" not in kwargs_appel["params"]


def test_rechercher_articles_leve_exception_sur_timeout(mocker) -> None:
    """Vérifie qu'un Timeout réseau est bien transformé en ErreurAPINewsAPI."""
    mocker.patch(
        "src.ingestion.newsapi_client.requests.get",
        side_effect=requests.exceptions.Timeout,
    )

    client = NewsApiClient()

    with pytest.raises(ErreurAPINewsAPI):
        client.rechercher_articles(mots_cles="flight delay")


def test_rechercher_articles_leve_exception_sur_authentification_refusee(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 401 (clé API invalide ou manquante) est bien
    transformée en ErreurAPINewsAPI.
    """
    reponse_mock = _construire_reponse_mock(mocker, 401)
    mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    client = NewsApiClient()

    with pytest.raises(ErreurAPINewsAPI):
        client.rechercher_articles(mots_cles="flight delay")


def test_rechercher_articles_leve_exception_sur_quota_depasse(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 429 (quota d'appels dépassé) est bien
    transformée en ErreurAPINewsAPI, plutôt que de retourner un JSON invalide.
    """
    reponse_mock = _construire_reponse_mock(mocker, 429)
    mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    client = NewsApiClient()

    with pytest.raises(ErreurAPINewsAPI):
        client.rechercher_articles(mots_cles="flight delay")


def test_rechercher_articles_leve_exception_sur_requete_trop_ancienne(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 426 (date demandée trop ancienne pour le plan
    gratuit) est bien transformée en ErreurAPINewsAPI.
    """
    reponse_mock = _construire_reponse_mock(mocker, 426)
    mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    client = NewsApiClient()

    with pytest.raises(ErreurAPINewsAPI):
        client.rechercher_articles(mots_cles="flight delay", date_depuis="2020-01-01")


def test_rechercher_articles_leve_exception_sur_requete_mal_formee(mocker) -> None:
    """
    Vérifie qu'une réponse HTTP 400 (requête mal formée) est bien transformée
    en ErreurAPINewsAPI.
    """
    reponse_mock = _construire_reponse_mock(mocker, 400)
    mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    client = NewsApiClient()

    with pytest.raises(ErreurAPINewsAPI):
        client.rechercher_articles(mots_cles="flight delay")


def test_recuperer_actualites_aeroportuaires_boucle_sur_chaque_requete(mocker) -> None:
    """
    Vérifie que la récupération multi-requêtes effectue bien un appel par
    requête et associe correctement chaque résultat aux mots-clés et à la
    langue attendus.
    """
    reponse_mock = _construire_reponse_mock(
        mocker, 200, {"status": "ok", "articles": [{"title": "Un article"}]}
    )
    mock_get = mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    requetes_test = (
        RequeteActualites('"airport strike"', "en"),
        RequeteActualites('"grève aéroport"', "fr"),
    )

    client = NewsApiClient()
    resultat = client.recuperer_actualites_aeroportuaires(requetes=requetes_test)

    assert mock_get.call_count == 2
    assert "horodatage_collecte" in resultat
    assert len(resultat["requetes"]) == 2
    assert resultat["requetes"][0]["langue_requete"] == "en"
    assert resultat["requetes"][0]["mots_cles"] == '"airport strike"'
    assert resultat["requetes"][1]["langue_requete"] == "fr"
    assert resultat["requetes"][0]["resultat"] == {
        "status": "ok",
        "articles": [{"title": "Un article"}],
    }


def test_recuperer_actualites_aeroportuaires_horodatage_collecte_est_utc(mocker) -> None:
    """
    Vérifie que l'horodatage de collecte est un horodatage UTC (suffixe
    `+00:00` ou `Z`), et non une heure locale naïve.
    """
    reponse_mock = _construire_reponse_mock(mocker, 200, {"status": "ok", "articles": []})
    mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    requetes_test = (RequeteActualites('"airport strike"', "en"),)
    client = NewsApiClient()
    resultat = client.recuperer_actualites_aeroportuaires(requetes=requetes_test)

    horodatage = resultat["horodatage_collecte"]
    assert horodatage.endswith("+00:00") or horodatage.endswith("Z")

    normalise = horodatage.replace("Z", "+00:00")
    instant = datetime.fromisoformat(normalise)
    assert instant.tzinfo is not None
    assert instant.utcoffset() == timedelta(0)


def test_recuperer_actualites_aeroportuaires_propage_erreur_immediatement(mocker) -> None:
    """
    Vérifie qu'une erreur sur une requête interrompt immédiatement la boucle,
    plutôt que de produire un jeu de données silencieusement incomplet.
    """
    reponse_mock = _construire_reponse_mock(mocker, 429)
    mock_get = mocker.patch(
        "src.ingestion.newsapi_client.requests.get", return_value=reponse_mock
    )

    requetes_test = (
        RequeteActualites('"airport strike"', "en"),
        RequeteActualites('"grève aéroport"', "fr"),
    )

    client = NewsApiClient()

    with pytest.raises(ErreurAPINewsAPI):
        client.recuperer_actualites_aeroportuaires(requetes=requetes_test)

    assert mock_get.call_count == 1


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
    client = NewsApiClient()
    donnees = {"horodatage_collecte": "2026-08-25T10:00:00", "requetes": []}

    chemin_fichier_str = client.sauvegarder_donnees_brutes(donnees, dossier=str(tmp_path))
    chemin_fichier = Path(chemin_fichier_str)

    assert chemin_fichier.exists()
    assert chemin_fichier.parent == tmp_path
    assert chemin_fichier.name.startswith("newsapi_")
    assert chemin_fichier.suffix == ".json"

    contenu_relu = json.loads(chemin_fichier.read_text(encoding="utf-8"))
    assert contenu_relu == donnees
