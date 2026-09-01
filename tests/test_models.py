"""
Tests du jeu vol + météo et de l'entraînement LightGBM (DataFrames mockés).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from src.models.entrainer import (
    comparer_a_la_baseline,
    entrainer_lightgbm,
    evaluer_regression,
    executer_pipeline,
    predire_baseline_mediane,
)
from src.models.jeu import (
    COLONNES_FEATURES,
    COLONNES_INTERDITES_FEATURES,
    NOM_CIBLE,
    SEUIL_MIN_LIGNES_ENTRAINEMENT,
    ajouter_cible_duree,
    aligner_categories,
    construire_features,
    diagnostiquer_volumetrie,
    filtrer_jeu_modele,
    retenir_cible,
    split_temporel,
)


def _instant(jour: int, heure: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, jour, heure, minute, tzinfo=timezone.utc)


def _ligne(
    *,
    jour: int,
    heure: int,
    minute: int = 0,
    duree_min: float = 50.0,
    hub: str = "LFPG",
    dest: str | None = "EGLL",
    weather_origin: int | None = 1,
    weather_dest: int | None = None,
    retard: float | None = None,
    vent: float = 3.0,
    pluie: float = 0.0,
    temp: float = 20.0,
    flight_id: int = 1,
) -> dict:
    debut = _instant(jour, heure, minute)
    fin = debut + timedelta(minutes=duree_min)
    return {
        "flight_id": flight_id,
        "icao24": f"abc{flight_id:03d}",
        "callsign": "AFR",
        "first_seen": debut,
        "last_seen": fin,
        "est_departure_airport": hub,
        "est_arrival_airport": dest,
        "date_id": int(debut.strftime("%Y%m%d")),
        "retard_minutes": retard,
        "weather_origin_id": weather_origin,
        "weather_dest_id": weather_dest,
        "jour_semaine": debut.isoweekday(),
        "mois": debut.month,
        "temperature_origine": temp if weather_origin is not None else None,
        "vent_origine": vent if weather_origin is not None else None,
        "rafale_origine": 0.0 if weather_origin is not None else None,
        "pluie_origine": pluie if weather_origin is not None else None,
        "visibilite_origine": 10000 if weather_origin is not None else None,
        "humidite_origine": 60 if weather_origin is not None else None,
        "temperature_dest": None,
        "vent_dest": None,
        "rafale_dest": None,
        "pluie_dest": None,
        "visibilite_dest": None,
    }


def cadre_synthetique(n: int = 80, sans_meteo: int = 10) -> pd.DataFrame:
    """Jeu synthétique étalé sur deux jours, durée liée au vent."""
    lignes = []
    for i in range(n):
        jour = 25 if i < n // 4 else 26
        heure = 8 + (i % 10)
        minute = (i * 3) % 60
        vent = 1.0 + (i % 8)
        weather = None if i < sans_meteo else 10 + i
        lignes.append(
            _ligne(
                jour=jour,
                heure=heure,
                minute=minute,
                duree_min=40.0 + 8.0 * vent,
                hub="LFPG" if i % 3 else "EGLL",
                dest=None,
                weather_origin=weather,
                retard=5.0 if i < 3 else None,
                vent=vent,
                pluie=0.2 if i % 11 == 0 else 0.0,
                temp=18.0 + (i % 5),
                flight_id=i + 1,
            )
        )
    return pd.DataFrame(lignes)


def test_diagnostiquer_compte_les_null_du_proxy() -> None:
    """Vérifie les effectifs retard / météo / routes sur un cadre connu."""
    df = cadre_synthetique(n=80, sans_meteo=10)
    diag = diagnostiquer_volumetrie(df)
    assert diag["nb_vols"] == 80
    assert diag["retard_non_null"] == 3
    assert diag["weather_origin"] == 70
    assert diag["pct_retard_null"] == 96.2
    assert diag["meteo_et_duree"] == 70


def test_retenir_cible_choisit_b_si_proxy_creux_et_duree_disponible() -> None:
    """Vérifie que la cible B est retenue quand le proxy et les routes OD sont trop rares."""
    diag = {
        "retard_non_null": 11,
        "vols_meteo_sur_routes_ge5": 0,
        "meteo_et_duree": 546,
    }
    assert retenir_cible(diag) == "B"


def test_retenir_cible_refuse_si_tout_est_trop_creux() -> None:
    """Vérifie l'échec explicite sous le seuil d'entraînement."""
    with pytest.raises(ValueError, match="Aucune cible entraînable"):
        retenir_cible(
            {
                "retard_non_null": 11,
                "vols_meteo_sur_routes_ge5": 0,
                "meteo_et_duree": 11,
            }
        )


def test_filtrer_jeu_modele_exige_meteo_origine() -> None:
    """Vérifie que les vols sans météo origine sortent du jeu d'entraînement."""
    df = cadre_synthetique(n=40, sans_meteo=8)
    filtre = filtrer_jeu_modele(df)
    assert filtre["weather_origin_id"].notna().all()
    assert len(filtre) == 32


def test_construire_features_sans_leakage() -> None:
    """Vérifie que X n'embarque ni last_seen, ni la cible, ni le proxy de retard."""
    df = ajouter_cible_duree(cadre_synthetique(n=40, sans_meteo=0))
    X, y = construire_features(df)
    assert list(X.columns) == list(COLONNES_FEATURES)
    assert set(X.columns).isdisjoint(COLONNES_INTERDITES_FEATURES)
    assert "last_seen" not in X.columns
    assert "first_seen" not in X.columns
    assert NOM_CIBLE not in X.columns
    assert "retard_minutes" not in X.columns
    assert y.name == NOM_CIBLE
    assert len(X) == len(y) == 40


def test_split_temporel_range_le_train_avant_le_test() -> None:
    """Vérifie qu'aucun instant de test n'apparaît dans le train."""
    df = cadre_synthetique(n=60, sans_meteo=0)
    train, test = split_temporel(df, fraction_train=0.7)
    assert train["first_seen"].max() < test["first_seen"].min()
    assert len(train) + len(test) == 60
    assert len(train) > 0 and len(test) > 0


def test_split_temporel_refuse_un_jeu_vide() -> None:
    """Vérifie l'échec sur un DataFrame vide."""
    with pytest.raises(ValueError, match="vide"):
        split_temporel(pd.DataFrame())


def test_baseline_mediane_constante() -> None:
    """Vérifie que la baseline recopie la médiane du train."""
    y_train = pd.Series([10.0, 20.0, 30.0, 40.0])
    pred = predire_baseline_mediane(y_train, n_test=5)
    assert pred.shape == (5,)
    assert np.allclose(pred, 25.0)


def test_evaluer_regression_rmse_mae() -> None:
    """Vérifie RMSE et MAE sur un écart connu."""
    vrai = np.array([0.0, 10.0])
    pred = np.array([0.0, 6.0])
    scores = evaluer_regression(vrai, pred)
    assert scores["mae"] == pytest.approx(2.0)
    assert scores["rmse"] == pytest.approx(np.sqrt(8.0))


def test_comparer_a_la_baseline() -> None:
    """Vérifie le test strict de RMSE contre la baseline."""
    assert comparer_a_la_baseline({"rmse": 9.0}, {"rmse": 10.0}) is True
    assert comparer_a_la_baseline({"rmse": 10.0}, {"rmse": 10.0}) is False


def test_pipeline_mocke_entraine_sans_postgres(tmp_path: Path) -> None:
    """
    Vérifie l'enchaînement diagnostic → split → LightGBM → joblib sur un
    DataFrame mocké, sans connexion PostgreSQL.
    """
    df = cadre_synthetique(n=max(80, SEUIL_MIN_LIGNES_ENTRAINEMENT + 10), sans_meteo=5)
    rapport = executer_pipeline(
        jeu=df,
        fraction_train=0.7,
        chemin_modele=tmp_path / "modele.joblib",
        sauvegarder=True,
    )
    assert rapport["code_cible"] == "B"
    assert rapport["cible"] == NOM_CIBLE
    assert rapport["n_train"] + rapport["n_test"] == int(
        (df["weather_origin_id"].notna() & df["last_seen"].notna()).sum()
    )
    assert "rmse" in rapport["metriques_modele"]
    assert "mae" in rapport["metriques_baseline"]
    assert (tmp_path / "modele.joblib").is_file()
    charge = joblib.load(tmp_path / "modele.joblib")
    assert charge["cible"] == NOM_CIBLE
    assert charge["colonnes_features"] == list(COLONNES_FEATURES)


def test_lightgbm_predit_sans_colonne_interdite() -> None:
    """Vérifie qu'un modèle ajusté n'expose pas last_seen dans ses features."""
    df = ajouter_cible_duree(filtrer_jeu_modele(cadre_synthetique(n=50, sans_meteo=0)))
    train, test = split_temporel(df, fraction_train=0.7)
    X_train, y_train = construire_features(train)
    X_test, y_test = construire_features(test)
    X_train, X_test = aligner_categories(X_train, X_test)
    modele = entrainer_lightgbm(X_train, y_train)
    pred = modele.predict(X_test)
    assert pred.shape == (len(y_test),)
    assert "last_seen" not in list(modele.feature_name_)
