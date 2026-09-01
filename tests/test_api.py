"""
Tests de l'API FastAPI (TestClient), sans appel OpenSky ni PostgreSQL.
"""

from pathlib import Path

import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sklearn.dummy import DummyRegressor

from src.api.app import (
    MESSAGE_MODELE_ABSENT,
    app,
    charger_modele,
    reinitialiser_chargement,
)
from src.api.schemas import EntreePrediction
from src.models.jeu import COLONNES_CATEGORIELLES, liste_colonnes_features


def _corps_valide() -> dict:
    return {
        "hub_origine": "LFPG",
        "jour_semaine": 2,
        "mois": 9,
        "heure_utc": 9.5,
        "temperature_origine": 18.0,
        "vent_origine": 4.0,
        "rafale_origine": 6.0,
        "pluie_origine": 0.0,
        "visibilite_origine": 10000.0,
        "humidite_origine": 60.0,
        "temperature_dest": None,
        "vent_dest": None,
        "rafale_dest": None,
        "pluie_dest": None,
        "visibilite_dest": None,
        "nb_articles_actu": 0.0,
        "proxy_perturbation_actu": 0.0,
    }


def _joblib_factice(chemin: Path, constante: float = 87.5) -> Path:
    colonnes = list(liste_colonnes_features(True))
    modele = DummyRegressor(strategy="constant", constant=constante)
    n = max(2, len(colonnes))
    X = np.zeros((n, len(colonnes)))
    y = np.full(n, constante)
    modele.fit(X, y)
    joblib.dump(
        {
            "modele": modele,
            "colonnes_features": colonnes,
            "colonnes_categorielles": list(COLONNES_CATEGORIELLES),
            "cible": "duree_minutes",
            "code_cible": "B",
        },
        chemin,
    )
    return chemin


@pytest.fixture
def client_sans_modele(monkeypatch, tmp_path: Path) -> TestClient:
    reinitialiser_chargement()
    monkeypatch.setattr(
        "src.api.app.CHEMIN_MODELE", tmp_path / "absent.joblib"
    )
    return TestClient(app)


@pytest.fixture
def client_avec_modele(monkeypatch, tmp_path: Path) -> TestClient:
    reinitialiser_chargement()
    chemin = _joblib_factice(tmp_path / "modele_vol_meteo.joblib")
    monkeypatch.setattr("src.api.app.CHEMIN_MODELE", chemin)
    charger_modele(chemin)
    return TestClient(app)


def test_app_n_importe_pas_le_module_entrainer() -> None:
    """L'API ne charge pas l'entraînement (évite requests/ETL dans l'image)."""
    from src.utils.chemins import RACINE_PROJET

    texte = (RACINE_PROJET / "src" / "api" / "app.py").read_text(encoding="utf-8")
    assert "from src.models.entrainer" not in texte
    """Vérifie que le BaseModel couvre exactement les colonnes d'entraînement."""
    assert set(EntreePrediction.model_fields) == set(liste_colonnes_features(True))
    assert "last_seen" not in EntreePrediction.model_fields
    assert "duree_minutes" not in EntreePrediction.model_fields
    assert "retard_minutes" not in EntreePrediction.model_fields


def test_health_sans_modele_reste_200(client_sans_modele: TestClient) -> None:
    """Vérifie que GET /health répond même si le joblib manque."""
    reponse = client_sans_modele.get("/health")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["statut"] == "ok"
    assert corps["modele_charge"] is False


def test_docs_openapi_natif(client_sans_modele: TestClient) -> None:
    """Vérifie la doc Swagger native FastAPI."""
    reponse = client_sans_modele.get("/docs")
    assert reponse.status_code == 200


def test_predict_sans_modele_renvoie_503(client_sans_modele: TestClient) -> None:
    """Vérifie le 503 explicite quand le joblib est absent."""
    reponse = client_sans_modele.post("/predict", json=_corps_valide())
    assert reponse.status_code == 503
    assert MESSAGE_MODELE_ABSENT in reponse.json()["detail"]


def test_predict_avec_modele_renvoie_la_duree(client_avec_modele: TestClient) -> None:
    """Vérifie POST /predict : durée observée, pas un champ retard."""
    reponse = client_avec_modele.post("/predict", json=_corps_valide())
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["cible"] == "duree_minutes"
    assert "retard" not in corps
    assert corps["duree_minutes_predite"] == pytest.approx(87.5)


def test_predict_corps_invalide_renvoie_422(client_avec_modele: TestClient) -> None:
    """Vérifie le 422 Pydantic si une feature obligatoire manque."""
    corps = _corps_valide()
    del corps["hub_origine"]
    reponse = client_avec_modele.post("/predict", json=corps)
    assert reponse.status_code == 422


def test_predict_ignore_last_seen_s_il_est_envoye(
    client_avec_modele: TestClient,
) -> None:
    """Vérifie qu'un last_seen superflu dans le JSON n'empêche pas la prédiction."""
    corps = _corps_valide()
    corps["last_seen"] = "2026-09-01T12:00:00Z"
    reponse = client_avec_modele.post("/predict", json=corps)
    assert reponse.status_code == 200
    assert reponse.json()["duree_minutes_predite"] == pytest.approx(87.5)
