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
    predire_baseline_mediane_horaire,
)
from src.models.jeu import (
    COLONNES_FEATURES,
    COLONNES_INTERDITES_FEATURES,
    NOM_CIBLE,
    SEUIL_DUREE_MAX_MINUTES,
    SEUIL_MIN_LIGNES_ENTRAINEMENT,
    ajouter_cible_duree,
    ajouter_features_actu,
    aligner_categories,
    construire_features,
    diagnostiquer_volumetrie,
    exclure_durees_aberrantes,
    filtrer_jeu_modele,
    liste_colonnes_features,
    proxy_perturbation_ligne,
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
        "nb_articles_actu": 2 + (jour % 4),
        "mots_cles_actu": '"airport strike" OR "flight delay"',
        "score_sentiment_actu": None,
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
    assert diag["retard_non_null_avec_meteo"] == 0
    assert diag["durees_gt_seuil_8h"] == 0
    assert diag["seuil_duree_max_minutes"] == SEUIL_DUREE_MAX_MINUTES


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
                "retard_non_null_avec_meteo": 2,
                "vols_meteo_sur_routes_ge5": 0,
                "meteo_et_duree": 11,
            }
        )


def test_retenir_cible_reste_b_si_proxy_avec_meteo_sous_le_seuil() -> None:
    """Vérifie qu'on ne bascule pas vers retard_minutes sous 50 lignes avec météo."""
    diag = {
        "retard_non_null": 49,
        "retard_non_null_avec_meteo": 49,
        "vols_meteo_sur_routes_ge5": 0,
        "meteo_et_duree": 200,
    }
    assert retenir_cible(diag) == "B"


def test_retenir_cible_choisit_c_si_proxy_et_meteo_suffisants() -> None:
    """Vérifie que C n'est retenue que si le proxy joint à la météo atteint 50."""
    diag = {
        "retard_non_null": 60,
        "retard_non_null_avec_meteo": 50,
        "vols_meteo_sur_routes_ge5": 0,
        "meteo_et_duree": 200,
    }
    assert retenir_cible(diag) == "C"


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
    attendues = list(liste_colonnes_features(True))
    assert list(X.columns) == attendues
    assert set(X.columns).isdisjoint(COLONNES_INTERDITES_FEATURES)
    assert "nb_articles_actu" in X.columns
    assert "proxy_perturbation_actu" in X.columns
    assert "mots_cles_actu" not in X.columns
    assert "score_sentiment_actu" not in X.columns
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


def test_baseline_horaire_utilise_la_mediane_de_lheure() -> None:
    """Vérifie la médiane locale par heure UTC quand l'heure est assez peuplée."""
    y_train = pd.Series(
        [10.0, 12.0, 14.0, 16.0, 18.0, 100.0, 102.0, 104.0, 106.0, 108.0]
    )
    h_train = pd.Series([8.1, 8.4, 8.7, 8.0, 8.9, 14.0, 14.2, 14.5, 14.8, 14.9])
    h_test = pd.Series([8.3, 14.1, 8.9])
    pred = predire_baseline_mediane_horaire(y_train, h_train, h_test, seuil_min_obs=5)
    assert np.allclose(pred, [14.0, 104.0, 14.0])


def test_baseline_horaire_fallback_si_heure_rare() -> None:
    """Vérifie le repli sur la médiane globale si l'heure a trop peu d'exemples."""
    y_train = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0, 999.0])
    h_train = pd.Series([8.0, 8.2, 8.4, 8.6, 8.8, 3.0])
    h_test = pd.Series([3.2, 8.1])
    pred = predire_baseline_mediane_horaire(y_train, h_train, h_test, seuil_min_obs=5)
    assert pred[0] == pytest.approx(35.0)
    assert pred[1] == pytest.approx(30.0)


def test_exclure_durees_aberrantes_coupe_au_dela_de_8h() -> None:
    """Vérifie qu'une durée de 23 h sort du jeu, sans winsorisation."""
    df = ajouter_cible_duree(cadre_synthetique(n=20, sans_meteo=0))
    df.loc[df.index[0], NOM_CIBLE] = 23 * 60
    filtre = exclure_durees_aberrantes(df)
    assert len(filtre) == 19
    assert (filtre[NOM_CIBLE] <= SEUIL_DUREE_MAX_MINUTES).all()
    assert (filtre[NOM_CIBLE] > 0).all()
    assert 23 * 60 not in set(filtre[NOM_CIBLE])


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
    assert rapport["n_exclues_duree"] == 0
    assert "rmse" in rapport["metriques_modele"]
    assert "mae" in rapport["metriques_baseline"]
    assert "rmse" in rapport["metriques_baseline_horaire"]
    assert "bat_la_baseline_horaire" in rapport
    assert (tmp_path / "modele.joblib").is_file()
    charge = joblib.load(tmp_path / "modele.joblib")
    assert charge["cible"] == NOM_CIBLE
    assert charge["colonnes_features"] == list(liste_colonnes_features(True))
    assert rapport["avec_actu"] is True


def test_pipeline_sans_actu_omet_les_colonnes_news(tmp_path: Path) -> None:
    """Vérifie le flag --sans-actu : mêmes lignes, pas de features actualités."""
    df = cadre_synthetique(n=max(80, SEUIL_MIN_LIGNES_ENTRAINEMENT + 10), sans_meteo=0)
    rapport = executer_pipeline(
        jeu=df,
        fraction_train=0.7,
        sauvegarder=False,
        avec_actu=False,
    )
    assert rapport["avec_actu"] is False
    assert rapport["colonnes_features"] == list(COLONNES_FEATURES)
    assert "nb_articles_actu" not in rapport["colonnes_features"]


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


def test_pipeline_exclut_une_duree_de_23h() -> None:
    """Vérifie que le pipeline retire un vol dont last_seen est 23 h après first_seen."""
    df = cadre_synthetique(n=max(80, SEUIL_MIN_LIGNES_ENTRAINEMENT + 10), sans_meteo=0)
    n_meteo = int((df["weather_origin_id"].notna() & df["last_seen"].notna()).sum())
    df.loc[df.index[0], "last_seen"] = df.loc[df.index[0], "first_seen"] + timedelta(
        hours=23
    )
    rapport = executer_pipeline(jeu=df, fraction_train=0.7, sauvegarder=False)
    assert rapport["n_exclues_duree"] == 1
    assert rapport["n_train"] + rapport["n_test"] == n_meteo - 1
    assert rapport["seuil_duree_max_minutes"] == SEUIL_DUREE_MAX_MINUTES


def test_proxy_perturbation_utilise_le_score_s_il_existe() -> None:
    """Vérifie qu'on ne fabrique pas un lexique si score_sentiment est déjà là."""
    assert proxy_perturbation_ligne(10, "airport strike", 0.42) == pytest.approx(0.42)


def test_proxy_perturbation_lexique_si_score_null() -> None:
    """Vérifie le proxy lexical sur les mots-clés déjà stockés, sans BERT."""
    score = proxy_perturbation_ligne(4, '"airport strike" OR "flight delay"', None)
    assert 0.0 < score <= 1.0


def test_ajouter_features_actu_remplit_zero_si_pas_de_news() -> None:
    """Vérifie le repli à 0 articles / proxy 0 quand la jointure est vide."""
    df = pd.DataFrame({"date_id": [20260825]})
    enrichi = ajouter_features_actu(df)
    assert enrichi["nb_articles_actu"].iloc[0] == 0
    assert enrichi["proxy_perturbation_actu"].iloc[0] == 0.0


def test_construire_features_sans_actu_reste_meteo() -> None:
    """Vérifie que avec_actu=False n'ajoute pas les colonnes actualités."""
    df = ajouter_cible_duree(cadre_synthetique(n=20, sans_meteo=0))
    X, _ = construire_features(df, avec_actu=False)
    assert list(X.columns) == list(COLONNES_FEATURES)
    assert "nb_articles_actu" not in X.columns
