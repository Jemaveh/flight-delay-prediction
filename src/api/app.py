"""
API FastAPI de consommation du LightGBM vol + météo.

GET /health : le processus répond, avec un booléen si le joblib est chargé.
GET /metrics : scrape Prometheus (latence HTTP, jauge joblib, compteur /predict).
POST /predict : une ligne de features → durée observée prédite (minutes).
Le modèle est lu dans models/modele_vol_meteo.joblib ; s'il manque, POST
renvoie 503. Aucun appel OpenSky ni NewsAPI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException

from src.api.metrics import (
    brancher_prometheus,
    compter_prediction,
    rafraichir_jauge_modele,
)
from src.api.schemas import EntreePrediction, SortiePrediction, SortieSante
from src.utils.chemins import RACINE_PROJET, chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Même chemin que src.models.entrainer.CHEMIN_MODELE_DEFAUT, sans importer
# l'entraînement (LightGBM + entrepôt + requests) au démarrage de l'API.
CHEMIN_MODELE: Path = RACINE_PROJET / "models" / "modele_vol_meteo.joblib"
MESSAGE_MODELE_ABSENT = (
    "Modèle introuvable. Entraîner d'abord avec "
    "`python -m src.models.entrainer` "
    "(fichier models/modele_vol_meteo.joblib)."
)

_etat: dict[str, Any] = {"tente": False, "payload": None}

app = FastAPI(
    title="Airlines Duration API",
    description=(
        "Prédiction de la durée observée OpenSky (last_seen − first_seen), "
        "pas d'un retard par rapport à un horaire programmé."
    ),
    version="0.1.0",
    openapi_tags=[
        {"name": "sante", "description": "Disponibilité du service."},
        {"name": "prediction", "description": "Consommation du modèle joblib."},
    ],
)
brancher_prometheus(app)


def reinitialiser_chargement() -> None:
    """Oublie le payload en mémoire (tests)."""
    _etat["tente"] = False
    _etat["payload"] = None
    rafraichir_jauge_modele(False)


def charger_modele(chemin: Path | None = None) -> None:
    """
    Charge le joblib depuis ``chemin`` ou ``CHEMIN_MODELE``.

    Absence ou lecture impossible : payload laissé à None (POST /predict → 503).
    """
    cible = Path(chemin) if chemin is not None else Path(CHEMIN_MODELE)
    _etat["tente"] = True
    try:
        if not cible.is_file():
            _etat["payload"] = None
            logger.warning("Modèle introuvable : %s.", chemin_relatif_projet(cible))
            return
        try:
            payload = joblib.load(cible)
        except Exception:
            logger.exception("Lecture du joblib impossible : %s.", cible)
            _etat["payload"] = None
            return
        if not isinstance(payload, dict) or "modele" not in payload:
            logger.error("Joblib sans clé 'modele' : %s.", cible)
            _etat["payload"] = None
            return
        if "colonnes_features" not in payload:
            logger.error("Joblib sans clé 'colonnes_features' : %s.", cible)
            _etat["payload"] = None
            return
        _etat["payload"] = payload
        logger.info("Modèle chargé depuis '%s'.", chemin_relatif_projet(cible))
    finally:
        rafraichir_jauge_modele(_etat["payload"] is not None)


def _payload_ou_aucun() -> dict | None:
    if not _etat["tente"]:
        charger_modele()
    return _etat["payload"]


def _ligne_modele(entree: EntreePrediction, colonnes: list[str]) -> pd.DataFrame:
    """Construit une matrice d'une ligne dans l'ordre des colonnes du joblib."""
    brut = entree.model_dump()
    valeurs: dict[str, object] = {}
    for colonne in colonnes:
        if colonne not in brut:
            raise HTTPException(
                status_code=422,
                detail=f"Feature manquante pour ce modèle : {colonne}.",
            )
        valeur = brut[colonne]
        valeurs[colonne] = np.nan if valeur is None else valeur
    return pd.DataFrame([valeurs], columns=colonnes)


@app.get(
    "/health",
    response_model=SortieSante,
    tags=["sante"],
    summary="Santé du service",
)
def get_sante() -> SortieSante:
    """Indique si le processus répond et si le fichier joblib est chargé."""
    payload = _payload_ou_aucun()
    return SortieSante(
        statut="ok",
        modele_charge=payload is not None,
    )


@app.post(
    "/predict",
    response_model=SortiePrediction,
    tags=["prediction"],
    summary="Prédiction de durée observée",
    responses={
        200: {"description": "Durée prédite en minutes."},
        422: {"description": "Corps JSON hors schéma Pydantic."},
        503: {"description": "Fichier joblib absent ou illisible."},
    },
)
def post_prediction(entree: EntreePrediction) -> SortiePrediction:
    """Retourne la durée observée prédite ; 503 si le modèle n'est pas chargé."""
    payload = _payload_ou_aucun()
    if payload is None:
        compter_prediction("absent")
        raise HTTPException(status_code=503, detail=MESSAGE_MODELE_ABSENT)
    colonnes = list(payload["colonnes_features"])
    X = _ligne_modele(entree, colonnes)
    for nom in payload.get("colonnes_categorielles") or []:
        if nom in X.columns:
            X[nom] = X[nom].astype("category")
    try:
        predit = float(payload["modele"].predict(X)[0])
    except Exception as erreur:
        compter_prediction("erreur")
        logger.exception("Échec de prédiction.")
        raise HTTPException(
            status_code=500,
            detail="Prédiction impossible sur ce corps JSON.",
        ) from erreur
    compter_prediction("ok")
    cible = str(payload.get("cible") or "duree_minutes")
    return SortiePrediction(duree_minutes_predite=predit, cible=cible)
