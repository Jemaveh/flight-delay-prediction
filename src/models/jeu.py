"""
Construction du jeu vol + météo depuis l'entrepôt PostgreSQL.

Cible : duree_minutes = last_seen − first_seen.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from src.database.db_connector import creer_engine
from src.processing.etl import SEUIL_MIN_VOLS_ROUTE
from src.utils.logger import get_logger

logger = get_logger(__name__)

NOM_CIBLE = "duree_minutes"
CODE_CIBLE = "B"
SEUIL_MIN_LIGNES_ENTRAINEMENT = 50
FRACTION_TRAIN_DEFAUT = 0.70

COLONNES_FEATURES = (
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
)
COLONNES_CATEGORIELLES = ("hub_origine",)
COLONNES_INTERDITES_FEATURES = frozenset(
    {
        "last_seen",
        "first_seen",
        "duree_minutes",
        "retard_minutes",
        "flight_id",
        "icao24",
        "callsign",
        "est_arrival_airport",
        "weather_origin_id",
        "weather_dest_id",
        "date_id",
    }
)

SQL_CHARGER_VOLS_METEO = """
SELECT
    f.flight_id,
    f.icao24,
    f.callsign,
    f.first_seen,
    f.last_seen,
    f.est_departure_airport,
    f.est_arrival_airport,
    f.date_id,
    f.retard_minutes,
    f.weather_origin_id,
    f.weather_dest_id,
    d.jour_semaine,
    d.mois,
    wo.temperature_celsius AS temperature_origine,
    wo.wind_speed AS vent_origine,
    wo.wind_gust AS rafale_origine,
    wo.rain_1h AS pluie_origine,
    wo.visibility AS visibilite_origine,
    wo.humidity AS humidite_origine,
    wd.temperature_celsius AS temperature_dest,
    wd.wind_speed AS vent_dest,
    wd.wind_gust AS rafale_dest,
    wd.rain_1h AS pluie_dest,
    wd.visibility AS visibilite_dest
FROM fact_flights f
JOIN dim_date d ON d.date_id = f.date_id
LEFT JOIN dim_weather wo ON wo.weather_id = f.weather_origin_id
LEFT JOIN dim_weather wd ON wd.weather_id = f.weather_dest_id
"""

MESSAGE_POSTGRES_INJOIGNABLE = (
    "PostgreSQL n'est pas joignable avec DATABASE_URL. "
    "Vérifier que l'instance locale tourne, puis relancer "
    "`python -m src.models.entrainer`."
)


def ouvrir_engine_ou_echec(engine: Engine | None = None) -> Engine:
    """
    Retourne un engine PostgreSQL, ou lève RuntimeError si la base est injoignable.
    """
    try:
        moteur = engine if engine is not None else creer_engine()
        with moteur.connect() as connexion:
            connexion.execute(text("SELECT 1"))
        return moteur
    except (OperationalError, OSError, ValueError) as erreur:
        raise RuntimeError(MESSAGE_POSTGRES_INJOIGNABLE) from erreur


def charger_vols_meteo(engine: Engine | None = None) -> pd.DataFrame:
    """
    Charge les vols de fact_flights joints à dim_date et dim_weather.
    """
    moteur = ouvrir_engine_ou_echec(engine)
    with moteur.connect() as connexion:
        jeu = pd.read_sql(text(SQL_CHARGER_VOLS_METEO), connexion)
    if "first_seen" in jeu.columns:
        jeu["first_seen"] = pd.to_datetime(jeu["first_seen"], utc=True)
    if "last_seen" in jeu.columns:
        jeu["last_seen"] = pd.to_datetime(jeu["last_seen"], utc=True)
    logger.info("Jeu brut chargé : %s ligne(s), %s colonne(s).", *jeu.shape)
    return jeu


def diagnostiquer_volumetrie(df: pd.DataFrame) -> dict:
    """
    Compte les vols, le proxy retard, la météo et les routes assez peuplées.
    """
    nb_vols = int(len(df))
    retard_non_null = int(df["retard_minutes"].notna().sum()) if nb_vols else 0
    weather_origin = int(df["weather_origin_id"].notna().sum()) if nb_vols else 0
    weather_dest = int(df["weather_dest_id"].notna().sum()) if nb_vols else 0
    dest_ok = int(df["est_arrival_airport"].notna().sum()) if nb_vols else 0
    duree_ok = (
        int(df["last_seen"].notna().sum()) if nb_vols and "last_seen" in df.columns else 0
    )

    routes = pd.DataFrame()
    if nb_vols:
        avec_od = df.dropna(subset=["est_departure_airport", "est_arrival_airport"])
        if not avec_od.empty:
            routes = (
                avec_od.groupby(["est_departure_airport", "est_arrival_airport"])
                .size()
                .reset_index(name="n")
            )

    avec_meteo = df.loc[df["weather_origin_id"].notna()] if nb_vols else df
    routes_meteo = pd.DataFrame()
    if not avec_meteo.empty:
        od_meteo = avec_meteo.dropna(
            subset=["est_departure_airport", "est_arrival_airport"]
        )
        if not od_meteo.empty:
            routes_meteo = (
                od_meteo.groupby(["est_departure_airport", "est_arrival_airport"])
                .size()
                .reset_index(name="n")
            )

    def _routes_ge(cadre: pd.DataFrame, seuil: int) -> tuple[int, int]:
        if cadre.empty:
            return 0, 0
        mask = cadre["n"] >= seuil
        return int(mask.sum()), int(cadre.loc[mask, "n"].sum()) if mask.any() else 0

    routes_ge5, vols_routes_ge5 = _routes_ge(routes, SEUIL_MIN_VOLS_ROUTE)
    routes_meteo_ge5, vols_meteo_ge5 = _routes_ge(routes_meteo, SEUIL_MIN_VOLS_ROUTE)
    meteo_et_duree = (
        int((df["weather_origin_id"].notna() & df["last_seen"].notna()).sum())
        if nb_vols
        else 0
    )
    first_min = None
    first_max = None
    if nb_vols and df["first_seen"].notna().any():
        first_min = pd.to_datetime(df["first_seen"], utc=True).min()
        first_max = pd.to_datetime(df["first_seen"], utc=True).max()
        if hasattr(first_min, "isoformat"):
            first_min = first_min.isoformat()
            first_max = first_max.isoformat()

    return {
        "nb_vols": nb_vols,
        "retard_non_null": retard_non_null,
        "pct_retard_null": round(100.0 * (nb_vols - retard_non_null) / nb_vols, 1)
        if nb_vols
        else None,
        "weather_origin": weather_origin,
        "pct_weather_origin": round(100.0 * weather_origin / nb_vols, 1)
        if nb_vols
        else None,
        "weather_dest": weather_dest,
        "pct_weather_dest": round(100.0 * weather_dest / nb_vols, 1) if nb_vols else None,
        "dest_renseignee": dest_ok,
        "last_seen_ok": duree_ok,
        "meteo_et_duree": meteo_et_duree,
        "routes_ge5": routes_ge5,
        "vols_sur_routes_ge5": vols_routes_ge5,
        "routes_meteo_ge5": routes_meteo_ge5,
        "vols_meteo_sur_routes_ge5": vols_meteo_ge5,
        "first_seen_min": first_min,
        "first_seen_max": first_max,
        "nb_jours": int(df["date_id"].nunique()) if nb_vols else 0,
    }


def retenir_cible(diag: dict) -> str:
    """
    Retourne le code de cible entraînable (B) d'après les effectifs du diagnostic.
    """
    retard_n = int(diag.get("retard_non_null") or 0)
    vols_a = int(diag.get("vols_meteo_sur_routes_ge5") or 0)
    vols_b = int(diag.get("meteo_et_duree") or 0)
    if vols_a >= SEUIL_MIN_LIGNES_ENTRAINEMENT:
        return "A"
    if vols_b >= SEUIL_MIN_LIGNES_ENTRAINEMENT:
        return "B"
    raise ValueError(
        "Aucune cible entraînable : proxy trop creux "
        f"({retard_n} lignes, option C interdite sous "
        f"{SEUIL_MIN_LIGNES_ENTRAINEMENT}), routes trop rares pour une "
        f"classe OD ({vols_a} vols), durées avec météo origine "
        f"insuffisantes ({vols_b} lignes)."
    )


def ajouter_cible_duree(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute la colonne duree_minutes = last_seen − first_seen, en minutes.
    """
    travail = df.copy()
    debut = pd.to_datetime(travail["first_seen"], utc=True)
    fin = pd.to_datetime(travail["last_seen"], utc=True)
    travail[NOM_CIBLE] = (fin - debut).dt.total_seconds() / 60.0
    return travail


def filtrer_jeu_modele(df: pd.DataFrame) -> pd.DataFrame:
    """
    Conserve les vols avec météo origine et last_seen renseignés.
    """
    masque = df["weather_origin_id"].notna() & df["last_seen"].notna()
    filtre = df.loc[masque].copy()
    logger.info(
        "Jeu modèle : %s ligne(s) avec météo origine et durée observée.",
        len(filtre),
    )
    return filtre


def split_temporel(
    df: pd.DataFrame,
    colonne_temps: str = "first_seen",
    fraction_train: float = FRACTION_TRAIN_DEFAUT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Sépare le jeu en train (instants antérieurs au seuil) et test (postérieurs).
    """
    if df.empty:
        raise ValueError("Split temporel impossible : DataFrame vide.")
    if not 0.0 < fraction_train < 1.0:
        raise ValueError("fraction_train doit être strictement entre 0 et 1.")
    instants = pd.to_datetime(df[colonne_temps], utc=True)
    seuil = instants.quantile(fraction_train)
    train = df.loc[instants < seuil].copy()
    test = df.loc[instants >= seuil].copy()
    if train.empty or test.empty:
        raise ValueError(
            "Split temporel dégénéré (train ou test vide). "
            "Élargir la fenêtre de collecte ou ajuster fraction_train."
        )
    dernier_train = pd.to_datetime(train[colonne_temps], utc=True).max()
    premier_test = pd.to_datetime(test[colonne_temps], utc=True).min()
    if dernier_train >= premier_test:
        raise ValueError("Le split temporel a laissé une fuite d'instant train → test.")
    logger.info(
        "Split temporel : train=%s (jusqu'à %s), test=%s (depuis %s).",
        len(train),
        dernier_train.isoformat(),
        len(test),
        premier_test.isoformat(),
    )
    return train, test


def _heure_utc(serie: pd.Series) -> pd.Series:
    instants = pd.to_datetime(serie, utc=True)
    return instants.dt.hour + instants.dt.minute / 60.0


def construire_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Construit la matrice X et le vecteur y (durée en minutes) sans colonnes interdites.
    """
    if NOM_CIBLE not in df.columns:
        travail = ajouter_cible_duree(df)
    else:
        travail = df.copy()
    travail = travail.dropna(subset=[NOM_CIBLE]).copy()
    travail["hub_origine"] = travail["est_departure_airport"]
    travail["heure_utc"] = _heure_utc(travail["first_seen"])
    manquantes = [c for c in COLONNES_FEATURES if c not in travail.columns]
    if manquantes:
        raise KeyError(f"Colonnes de features absentes : {manquantes}.")
    X = travail.loc[:, list(COLONNES_FEATURES)].copy()
    for colonne in COLONNES_FEATURES:
        if colonne in COLONNES_CATEGORIELLES:
            continue
        X[colonne] = pd.to_numeric(X[colonne], errors="coerce")
    y = travail[NOM_CIBLE].astype("float64")
    interdites = COLONNES_INTERDITES_FEATURES.intersection(X.columns)
    if interdites:
        raise ValueError(f"Fuite de données : colonnes interdites dans X : {sorted(interdites)}.")
    y.index = X.index
    return X, y


def aligner_categories(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    colonnes: tuple[str, ...] = COLONNES_CATEGORIELLES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Encode les colonnes catégorielles sur les modalités vues en train.
    """
    train = X_train.copy()
    test = X_test.copy()
    for colonne in colonnes:
        categories = pd.Categorical(train[colonne]).categories
        train[colonne] = pd.Categorical(train[colonne], categories=categories)
        test[colonne] = pd.Categorical(test[colonne], categories=categories)
    return train, test


def preparer_train_test(
    df: pd.DataFrame,
    fraction_train: float = FRACTION_TRAIN_DEFAUT,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series, datetime, datetime]:
    """
    Filtre, ajoute la cible, split temporel, puis construit X/y train et test.
    """
    filtre = filtrer_jeu_modele(df)
    if len(filtre) < SEUIL_MIN_LIGNES_ENTRAINEMENT:
        raise ValueError(
            f"Jeu trop petit pour entraîner ({len(filtre)} lignes, "
            f"minimum {SEUIL_MIN_LIGNES_ENTRAINEMENT})."
        )
    avec_cible = ajouter_cible_duree(filtre)
    train_brut, test_brut = split_temporel(avec_cible, fraction_train=fraction_train)
    X_train, y_train = construire_features(train_brut)
    X_test, y_test = construire_features(test_brut)
    X_train, X_test = aligner_categories(X_train, X_test)
    debut_test = pd.to_datetime(test_brut["first_seen"], utc=True).min().to_pydatetime()
    fin_train = pd.to_datetime(train_brut["first_seen"], utc=True).max().to_pydatetime()
    return X_train, y_train, X_test, y_test, fin_train, debut_test
