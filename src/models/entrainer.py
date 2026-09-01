"""
Entraînement LightGBM (régression de la durée observée) et sauvegarde joblib.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sqlalchemy import Engine

from src.models.jeu import (
    CODE_CIBLE,
    COLONNES_CATEGORIELLES,
    FRACTION_TRAIN_DEFAUT,
    NOM_CIBLE,
    SEUIL_DUREE_MAX_MINUTES,
    SEUIL_MIN_OBS_HEURE,
    charger_vols_meteo,
    diagnostiquer_volumetrie,
    liste_colonnes_features,
    preparer_train_test,
    retenir_cible,
)
from src.utils.chemins import RACINE_PROJET, chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

DOSSIER_MODELES = RACINE_PROJET / "models"
CHEMIN_MODELE_DEFAUT = DOSSIER_MODELES / "modele_vol_meteo.joblib"

PARAMS_LIGHTGBM = {
    "n_estimators": 200,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 20,
    "max_depth": 4,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "verbose": -1,
}


def predire_baseline_mediane(y_train: pd.Series, n_test: int) -> np.ndarray:
    """
    Retourne n_test fois la médiane de y_train.
    """
    return np.full(n_test, float(y_train.median()), dtype="float64")


def _heure_entiere(heures: pd.Series) -> np.ndarray:
    """Tronque heure_utc (heure + minutes / 60) à l'heure entière 0–23."""
    numerique = pd.to_numeric(heures, errors="coerce")
    return numerique.fillna(-1).to_numpy(dtype="float64").astype(int)


def predire_baseline_mediane_horaire(
    y_train: pd.Series,
    heures_train: pd.Series,
    heures_test: pd.Series,
    seuil_min_obs: int = SEUIL_MIN_OBS_HEURE,
) -> np.ndarray:
    """
    Médiane de y_train par heure UTC entière.

    Si une heure a moins de ``seuil_min_obs`` observations en train, ou si
    elle est absente du train, on recopie la médiane globale du train.
    """
    globale = float(y_train.median())
    h_train = _heure_entiere(heures_train)
    h_test = _heure_entiere(heures_test)
    stats = (
        pd.DataFrame({"y": y_train.to_numpy(), "h": h_train})
        .groupby("h")["y"]
        .agg(["median", "size"])
    )
    lookup: dict[int, float] = {}
    for heure, ligne in stats.iterrows():
        lookup[int(heure)] = (
            float(ligne["median"]) if int(ligne["size"]) >= seuil_min_obs else globale
        )
    return np.array(
        [lookup.get(int(heure), globale) for heure in h_test],
        dtype="float64",
    )


def evaluer_regression(y_vrai, y_pred) -> dict[str, float]:
    """
    Calcule RMSE et MAE d'une prédiction de régression.
    """
    return {
        "rmse": float(root_mean_squared_error(y_vrai, y_pred)),
        "mae": float(mean_absolute_error(y_vrai, y_pred)),
    }


def entrainer_lightgbm(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    params: dict | None = None,
) -> lgb.LGBMRegressor:
    """
    Ajuste un LGBMRegressor sur X_train, y_train.
    """
    reglages = dict(PARAMS_LIGHTGBM if params is None else params)
    modele = lgb.LGBMRegressor(**reglages)
    categorielle = [c for c in COLONNES_CATEGORIELLES if c in X_train.columns]
    modele.fit(
        X_train,
        y_train,
        categorical_feature=categorielle or "auto",
    )
    return modele


def comparer_a_la_baseline(metriques_modele: dict, metriques_baseline: dict) -> bool:
    """
    Indique si le RMSE du modèle est strictement inférieur à celui de la baseline.
    """
    return metriques_modele["rmse"] < metriques_baseline["rmse"]


def sauvegarder_modele(payload: dict, chemin: Path | None = None) -> Path:
    """
    Sérialise le payload (modèle, colonnes, métriques) en joblib.
    """
    destination = chemin if chemin is not None else CHEMIN_MODELE_DEFAUT
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, destination)
    logger.info("Modèle sauvegardé dans '%s'.", chemin_relatif_projet(destination))
    return destination


def executer_pipeline(
    engine: Engine | None = None,
    jeu: pd.DataFrame | None = None,
    fraction_train: float = FRACTION_TRAIN_DEFAUT,
    chemin_modele: Path | None = None,
    sauvegarder: bool = True,
    avec_actu: bool = True,
) -> dict:
    """
    Enchaîne diagnostic, split temporel, LightGBM, baseline et sauvegarde optionnelle.
    """
    cadre = jeu if jeu is not None else charger_vols_meteo(engine)
    diag = diagnostiquer_volumetrie(cadre)
    code = retenir_cible(diag)
    if code != CODE_CIBLE:
        raise ValueError(
            f"Cible retenue par le diagnostic : {code}, ce module entraîne {CODE_CIBLE}."
        )
    colonnes = liste_colonnes_features(avec_actu)
    (
        X_train,
        y_train,
        X_test,
        y_test,
        fin_train,
        debut_test,
        n_exclues_duree,
    ) = preparer_train_test(
        cadre, fraction_train=fraction_train, avec_actu=avec_actu
    )
    modele = entrainer_lightgbm(X_train, y_train)
    pred_modele = modele.predict(X_test)
    pred_base = predire_baseline_mediane(y_train, len(y_test))
    pred_base_horaire = predire_baseline_mediane_horaire(
        y_train, X_train["heure_utc"], X_test["heure_utc"]
    )
    metriques_modele = evaluer_regression(y_test, pred_modele)
    metriques_baseline = evaluer_regression(y_test, pred_base)
    metriques_baseline_horaire = evaluer_regression(y_test, pred_base_horaire)
    bat_baseline = comparer_a_la_baseline(metriques_modele, metriques_baseline)
    bat_baseline_horaire = comparer_a_la_baseline(
        metriques_modele, metriques_baseline_horaire
    )
    importances = {}
    if hasattr(modele, "feature_importances_"):
        importances = {
            nom: int(score)
            for nom, score in zip(X_train.columns, modele.feature_importances_)
        }
    rapport = {
        "cible": NOM_CIBLE,
        "code_cible": code,
        "diagnostic": diag,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "n_exclues_duree": int(n_exclues_duree),
        "seuil_duree_max_minutes": SEUIL_DUREE_MAX_MINUTES,
        "fin_train": fin_train.isoformat(),
        "debut_test": debut_test.isoformat(),
        "colonnes_features": list(colonnes),
        "avec_actu": bool(avec_actu),
        "metriques_modele": metriques_modele,
        "metriques_baseline": metriques_baseline,
        "metriques_baseline_horaire": metriques_baseline_horaire,
        "bat_la_baseline": bat_baseline,
        "bat_la_baseline_horaire": bat_baseline_horaire,
        "importance_features": importances,
        "date_entrainement": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        "Cible %s (%s). Train=%s, test=%s, durées > %s min exclues=%s. "
        "Actualités : %s. "
        "LightGBM RMSE=%.2f MAE=%.2f. "
        "Baseline médiane globale RMSE=%.2f MAE=%.2f. "
        "Baseline médiane par heure UTC RMSE=%.2f MAE=%.2f. "
        "Bat la globale : %s. Bat l'horaire : %s.",
        NOM_CIBLE,
        code,
        rapport["n_train"],
        rapport["n_test"],
        SEUIL_DUREE_MAX_MINUTES,
        n_exclues_duree,
        "oui" if avec_actu else "non",
        metriques_modele["rmse"],
        metriques_modele["mae"],
        metriques_baseline["rmse"],
        metriques_baseline["mae"],
        metriques_baseline_horaire["rmse"],
        metriques_baseline_horaire["mae"],
        bat_baseline,
        bat_baseline_horaire,
    )
    if sauvegarder:
        payload = {
            "modele": modele,
            "colonnes_features": list(colonnes),
            "colonnes_categorielles": list(COLONNES_CATEGORIELLES),
            "cible": NOM_CIBLE,
            "code_cible": code,
            "rapport": {k: v for k, v in rapport.items() if k != "diagnostic"},
        }
        rapport["chemin_modele"] = str(
            chemin_relatif_projet(sauvegarder_modele(payload, chemin_modele))
        )
    return rapport


def construire_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Entraîne un LightGBM de régression sur la durée observée "
            "des vols (météo origine obligatoire). Aucun appel d'API. "
            "Jointure actualités par date UTC de first_seen, sans NewsAPI."
        )
    )
    parser.add_argument(
        "--fraction-train",
        type=float,
        default=FRACTION_TRAIN_DEFAUT,
        help="Part des instants first_seen réservée au train (split temporel).",
    )
    parser.add_argument(
        "--sortie",
        default=str(CHEMIN_MODELE_DEFAUT),
        help="Chemin du fichier joblib (dossier models/, ignoré par Git).",
    )
    parser.add_argument(
        "--sans-sauvegarde",
        action="store_true",
        help="Évalue sans écrire de fichier joblib.",
    )
    parser.add_argument(
        "--sans-actu",
        action="store_true",
        help="Entraîne sans nb_articles_actu ni proxy_perturbation_actu.",
    )
    return parser


def main(argv: list[str] | None = None) -> dict:
    """Point d'entrée CLI : ``python -m src.models.entrainer``."""
    args = construire_parser().parse_args(argv)
    try:
        return executer_pipeline(
            fraction_train=args.fraction_train,
            chemin_modele=Path(args.sortie),
            sauvegarder=not args.sans_sauvegarde,
            avec_actu=not args.sans_actu,
        )
    except RuntimeError as erreur:
        logger.error("%s", erreur)
        raise SystemExit(1) from erreur
    except ValueError as erreur:
        logger.error("%s", erreur)
        raise SystemExit(1) from erreur


if __name__ == "__main__":
    main()
