"""
Expérience Open-Meteo horaire et proxy d'écart à la médiane de route.

N'écrit pas models/modele_vol_meteo.joblib. La météo de production
reste OpenWeather Current.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    roc_auc_score,
)

from src.ingestion.openmeteo_client import OpenMeteoClient
from src.models.entrainer import (
    comparer_a_la_baseline,
    entrainer_lightgbm,
    evaluer_regression,
    predire_baseline_mediane,
    predire_baseline_mediane_horaire,
)
from src.models.jeu import (
    COLONNES_CATEGORIELLES,
    SEUIL_MIN_LIGNES_ENTRAINEMENT,
    ajouter_cible_duree,
    aligner_categories,
    charger_vols_meteo,
    exclure_durees_aberrantes,
    split_temporel,
)
from src.processing.etl import DOSSIER_RAW_DEFAUT
from src.processing.meteo_archive import (
    charger_series_hubs,
    dates_fenetre_vols,
    dernier_json_openmeteo,
    joindre_meteo_horaire,
    retard_sans_fuite,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

SEUIL_RETARD_CLASSE_MINUTES = 15.0

COLONNES_FEATURES_OM = (
    "hub_origine",
    "jour_semaine",
    "mois",
    "heure_utc",
    "temperature_origine",
    "vent_origine",
    "rafale_origine",
    "pluie_origine",
    "visibilite_origine",
    "humidite_origine",
    "temperature_dest",
    "vent_dest",
    "rafale_dest",
    "pluie_dest",
    "visibilite_dest",
    "humidite_dest",
)


def _heure_utc(serie: pd.Series) -> pd.Series:
    instants = pd.to_datetime(serie, utc=True)
    return instants.dt.hour + instants.dt.minute / 60.0


def construire_features_om(
    df: pd.DataFrame, colonne_cible: str
) -> tuple[pd.DataFrame, pd.Series]:
    """X calendrier + météo Open-Meteo, y = colonne_cible (durée ou proxy)."""
    travail = df.copy()
    travail["hub_origine"] = travail["est_departure_airport"]
    travail["heure_utc"] = _heure_utc(travail["first_seen"])
    manquantes = [c for c in COLONNES_FEATURES_OM if c not in travail.columns]
    if manquantes:
        raise KeyError(f"Colonnes Open-Meteo absentes : {manquantes}.")
    X = travail.loc[:, list(COLONNES_FEATURES_OM)].copy()
    for colonne in COLONNES_FEATURES_OM:
        if colonne in COLONNES_CATEGORIELLES:
            continue
        X[colonne] = pd.to_numeric(X[colonne], errors="coerce")
    y = pd.to_numeric(travail[colonne_cible], errors="coerce").astype("float64")
    masque = y.notna()
    return X.loc[masque], y.loc[masque]


def evaluer_regression_om(
    train: pd.DataFrame, test: pd.DataFrame, colonne_cible: str
) -> dict:
    X_train, y_train = construire_features_om(train, colonne_cible)
    X_test, y_test = construire_features_om(test, colonne_cible)
    X_train, X_test = aligner_categories(X_train, X_test)
    modele = entrainer_lightgbm(X_train, y_train)
    pred = modele.predict(X_test)
    zero = np.zeros(len(y_test), dtype="float64")
    importances = dict(
        zip(X_train.columns.tolist(), [int(v) for v in modele.feature_importances_])
    )
    metriques = evaluer_regression(y_test, pred)
    return {
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "metriques_modele": metriques,
        "metriques_baseline": evaluer_regression(
            y_test, predire_baseline_mediane(y_train, len(y_test))
        ),
        "metriques_baseline_horaire": evaluer_regression(
            y_test,
            predire_baseline_mediane_horaire(
                y_train, X_train["heure_utc"], X_test["heure_utc"]
            ),
        ),
        "metriques_baseline_zero": evaluer_regression(y_test, zero),
        "bat_la_baseline": comparer_a_la_baseline(
            metriques,
            evaluer_regression(
                y_test, predire_baseline_mediane(y_train, len(y_test))
            ),
        ),
        "bat_la_baseline_horaire": comparer_a_la_baseline(
            metriques,
            evaluer_regression(
                y_test,
                predire_baseline_mediane_horaire(
                    y_train, X_train["heure_utc"], X_test["heure_utc"]
                ),
            ),
        ),
        "bat_la_baseline_zero": metriques["rmse"]
        < evaluer_regression(y_test, zero)["rmse"],
        "importance_features": importances,
        "couverture_meteo_origine_test": float(
            test["temperature_origine"].notna().mean()
        )
        if "temperature_origine" in test.columns and len(test)
        else 0.0,
    }


def evaluer_classe_15min(train: pd.DataFrame, test: pd.DataFrame) -> dict:
    """
    Classe binaire : proxy > 15 min (seuil BTS / Kaggle DEP_DEL15).
    Baseline : toujours la classe majoritaire du train.
    """
    X_train, y_reg_train = construire_features_om(train, "retard_sans_fuite")
    X_test, y_reg_test = construire_features_om(test, "retard_sans_fuite")
    y_train = (y_reg_train > SEUIL_RETARD_CLASSE_MINUTES).astype(int)
    y_test = (y_reg_test > SEUIL_RETARD_CLASSE_MINUTES).astype(int)
    X_train, X_test = aligner_categories(X_train, X_test)
    majoritaire = int(y_train.mode().iloc[0]) if len(y_train) else 0
    pred_base = np.full(len(y_test), majoritaire, dtype=int)
    if y_train.nunique() < 2:
        return {
            "n_train": int(len(X_train)),
            "n_test": int(len(X_test)),
            "seuil_minutes": SEUIL_RETARD_CLASSE_MINUTES,
            "taux_positif_train": float(y_train.mean()) if len(y_train) else None,
            "taux_positif_test": float(y_test.mean()) if len(y_test) else None,
            "classe_majoritaire_train": majoritaire,
            "accuracy_modele": None,
            "f1_positif_modele": None,
            "auc_modele": None,
            "accuracy_baseline": float(accuracy_score(y_test, pred_base))
            if len(y_test)
            else None,
            "f1_positif_baseline": None,
            "motif": "une seule classe en train, pas de classifieur.",
        }
    modele = lgb.LGBMClassifier(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=20,
        max_depth=4,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    categorielle = [c for c in COLONNES_CATEGORIELLES if c in X_train.columns]
    modele.fit(X_train, y_train, categorical_feature=categorielle or "auto")
    pred = modele.predict(X_test)
    proba = modele.predict_proba(X_test)[:, 1]
    auc = None
    if y_test.nunique() == 2:
        auc = float(roc_auc_score(y_test, proba))
    return {
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "seuil_minutes": SEUIL_RETARD_CLASSE_MINUTES,
        "taux_positif_train": float(y_train.mean()),
        "taux_positif_test": float(y_test.mean()),
        "classe_majoritaire_train": majoritaire,
        "accuracy_modele": float(accuracy_score(y_test, pred)),
        "f1_positif_modele": float(f1_score(y_test, pred, zero_division=0)),
        "auc_modele": auc,
        "accuracy_baseline": float(accuracy_score(y_test, pred_base)),
        "f1_positif_baseline": float(f1_score(y_test, pred_base, zero_division=0)),
    }


def assurer_json_openmeteo(
    vols: pd.DataFrame,
    dossier_raw: Path,
    sans_collecte: bool,
) -> Path:
    existant = dernier_json_openmeteo(dossier_raw)
    if sans_collecte:
        if existant is None:
            raise FileNotFoundError(
                "Aucun openmeteo_*.json dans data/raw/. "
                "Relancer sans --sans-collecte."
            )
        logger.info("Rejeu JSON Open-Meteo : %s", existant.name)
        return existant
    debut, fin = dates_fenetre_vols(vols)
    client = OpenMeteoClient()
    brut = client.recuperer_meteo_hubs(debut, fin)
    return client.sauvegarder_donnees_brutes(brut, dossier=str(dossier_raw))


def preparer_jeu_om(
    vols: pd.DataFrame, chemin_json: Path
) -> pd.DataFrame:
    series = charger_series_hubs(chemin_json)
    if series.empty:
        raise ValueError(f"Série Open-Meteo vide : {chemin_json}")
    enrichi = joindre_meteo_horaire(ajouter_cible_duree(vols), series)
    filtre = exclure_durees_aberrantes(enrichi)
    n_meteo = int(filtre["temperature_origine"].notna().sum()) if len(filtre) else 0
    logger.info(
        "Après plafond 8 h : %s vols, météo origine Open-Meteo sur %s (%.1f %%).",
        len(filtre),
        n_meteo,
        100.0 * n_meteo / len(filtre) if len(filtre) else 0.0,
    )
    return filtre


def executer_experience(
    sans_collecte: bool = False,
    dossier_raw: Path | None = None,
    jeu: pd.DataFrame | None = None,
) -> dict:
    """
    Charge l'entrepôt, joint Open-Meteo, compare durée puis proxy OD.
    """
    racine_raw = dossier_raw if dossier_raw is not None else DOSSIER_RAW_DEFAUT
    vols = jeu if jeu is not None else charger_vols_meteo()
    chemin_json = assurer_json_openmeteo(vols, racine_raw, sans_collecte)
    filtre = preparer_jeu_om(vols, chemin_json)
    if len(filtre) < SEUIL_MIN_LIGNES_ENTRAINEMENT:
        raise ValueError(
            f"Jeu trop petit après Open-Meteo ({len(filtre)} lignes)."
        )
    train_d, test_d = split_temporel(filtre)
    duree = evaluer_regression_om(train_d, test_d, "duree_minutes")
    train_p, test_p = retard_sans_fuite(train_d, test_d)
    logger.info(
        "Proxy sans fuite : train %s → %s, test %s → %s "
        "(OD ≥ 5 en train seulement).",
        len(train_d),
        len(train_p),
        len(test_d),
        len(test_p),
    )
    if len(train_p) < SEUIL_MIN_LIGNES_ENTRAINEMENT or len(test_p) == 0:
        proxy = None
        classe = None
        logger.warning("Pas assez de lignes pour le proxy OD / la classe 15 min.")
    else:
        proxy = evaluer_regression_om(train_p, test_p, "retard_sans_fuite")
        classe = evaluer_classe_15min(train_p, test_p)
    rapport = {
        "json_openmeteo": chemin_json.name,
        "n_vols_plafond": int(len(filtre)),
        "fin_train": pd.to_datetime(train_d["first_seen"], utc=True).max().isoformat(),
        "debut_test": pd.to_datetime(test_d["first_seen"], utc=True).min().isoformat(),
        "regression_duree": duree,
        "regression_proxy": proxy,
        "classification_15min": classe,
        "date_experience": datetime.now().astimezone().isoformat(),
    }
    logger.info(
        "Durée Open-Meteo : RMSE LGBM=%.2f vs médiane=%.2f / horaire=%.2f "
        "(n_test=%s, météo origine test=%.0f %%).",
        duree["metriques_modele"]["rmse"],
        duree["metriques_baseline"]["rmse"],
        duree["metriques_baseline_horaire"]["rmse"],
        duree["n_test"],
        100.0 * duree["couverture_meteo_origine_test"],
    )
    if proxy is not None:
        logger.info(
            "Proxy OD (train seul) : RMSE LGBM=%.2f vs médiane=%.2f / "
            "horaire=%.2f / zéro=%.2f.",
            proxy["metriques_modele"]["rmse"],
            proxy["metriques_baseline"]["rmse"],
            proxy["metriques_baseline_horaire"]["rmse"],
            proxy["metriques_baseline_zero"]["rmse"],
        )
    if classe is not None and classe.get("accuracy_modele") is not None:
        logger.info(
            "Classe > %.0f min : acc modèle=%.3f vs baseline=%.3f, "
            "F1+=%.3f vs %.3f, AUC=%s, taux test=%.1f %%.",
            SEUIL_RETARD_CLASSE_MINUTES,
            classe["accuracy_modele"],
            classe["accuracy_baseline"],
            classe["f1_positif_modele"],
            classe["f1_positif_baseline"],
            classe["auc_modele"],
            100.0 * (classe["taux_positif_test"] or 0.0),
        )
    return rapport


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(
        description=(
            "Expérience Open-Meteo + proxy de retard. "
            "N'écrase pas le joblib de production."
        )
    )
    parser.add_argument(
        "--sans-collecte",
        action="store_true",
        help="Relire le dernier openmeteo_*.json, sans appel HTTP.",
    )
    args = parser.parse_args(argv)
    return executer_experience(sans_collecte=args.sans_collecte)


if __name__ == "__main__":
    main()
