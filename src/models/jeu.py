"""
Construction du jeu vol + météo (+ actualités journalières) depuis l'entrepôt.

Cible : duree_minutes = last_seen − first_seen.
Jointure actualités : date UTC de first_seen → dim_news_sentiment.
Pas d'appel NewsAPI, pas de BERT : nb_articles et un proxy lexical
sur les mots-clés déjà stockés (score_sentiment s'il n'est pas NULL).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from src.database.db_connector import creer_engine
from src.processing.data_cleaning import proxy_perturbation_texte
from src.processing.etl import SEUIL_MIN_VOLS_ROUTE
from src.utils.logger import get_logger

logger = get_logger(__name__)

NOM_CIBLE = "duree_minutes"
CODE_CIBLE = "B"
SEUIL_MIN_LIGNES_ENTRAINEMENT = 50
FRACTION_TRAIN_DEFAUT = 0.70
# Plafond de durée observée : au-delà, first_seen/last_seen ADS-B ne mesurent
# plus un vol (trou de tracking, avion revu le lendemain). 8 h couvre les
# liaisons entre les dix hubs européens (p99 du jeu ~4,4 h) ; le max brut
# observé dépasse 23 h. On filtre, on ne winsorise pas : caper à 480 min
# traiterait encore un artefact comme un vol de 8 h.
SEUIL_DUREE_MAX_MINUTES = 8 * 60
# Heure UTC « assez peuplée » pour une médiane locale ; sinon médiane globale.
SEUIL_MIN_OBS_HEURE = SEUIL_MIN_VOLS_ROUTE

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
COLONNES_FEATURES_ACTU = ("nb_articles_actu", "proxy_perturbation_actu")
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
        "mots_cles_actu",
        "score_sentiment_actu",
    }
)


def liste_colonnes_features(avec_actu: bool = True) -> tuple[str, ...]:
    """Features vol + météo, plus actualités journalières si demandé."""
    if avec_actu:
        return COLONNES_FEATURES + COLONNES_FEATURES_ACTU
    return COLONNES_FEATURES


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
    wd.visibility AS visibilite_dest,
    n.nb_articles AS nb_articles_actu,
    n.mots_cles AS mots_cles_actu,
    n.score_sentiment AS score_sentiment_actu
FROM fact_flights f
JOIN dim_date d ON d.date_id = f.date_id
LEFT JOIN dim_weather wo ON wo.weather_id = f.weather_origin_id
LEFT JOIN dim_weather wd ON wd.weather_id = f.weather_dest_id
LEFT JOIN dim_news_sentiment n ON n.date_id = CAST(
    to_char((f.first_seen AT TIME ZONE 'UTC')::date, 'YYYYMMDD') AS INTEGER
)
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
    Charge les vols de fact_flights joints à dim_date, dim_weather et
    dim_news_sentiment (date UTC de first_seen).
    """
    moteur = ouvrir_engine_ou_echec(engine)
    with moteur.connect() as connexion:
        jeu = pd.read_sql(text(SQL_CHARGER_VOLS_METEO), connexion)
    if "first_seen" in jeu.columns:
        jeu["first_seen"] = pd.to_datetime(jeu["first_seen"], utc=True)
    if "last_seen" in jeu.columns:
        jeu["last_seen"] = pd.to_datetime(jeu["last_seen"], utc=True)
    jeu = ajouter_features_actu(jeu)
    logger.info("Jeu brut chargé : %s ligne(s), %s colonne(s).", *jeu.shape)
    return jeu


def proxy_perturbation_ligne(
    nb_articles: object,
    mots_cles: object,
    score_sentiment: object,
) -> float:
    """
    Proxy sans BERT : score_sentiment s'il est déjà en base, sinon lexique
    sur mots_cles stockés. nb_articles reste une feature séparée.
    """
    if score_sentiment is not None and not (
        isinstance(score_sentiment, float) and pd.isna(score_sentiment)
    ):
        try:
            return float(score_sentiment)
        except (TypeError, ValueError):
            pass
    if mots_cles is None or (isinstance(mots_cles, float) and pd.isna(mots_cles)):
        return 0.0
    return float(proxy_perturbation_texte(str(mots_cles)))


def ajouter_features_actu(df: pd.DataFrame) -> pd.DataFrame:
    """
    Dérive nb_articles_actu et proxy_perturbation_actu depuis les colonnes
    déjà jointes (pas d'appel NewsAPI).
    """
    travail = df.copy()
    if "nb_articles_actu" not in travail.columns:
        travail["nb_articles_actu"] = 0
    travail["nb_articles_actu"] = pd.to_numeric(
        travail["nb_articles_actu"], errors="coerce"
    ).fillna(0)
    if "proxy_perturbation_actu" not in travail.columns:
        mots = (
            travail["mots_cles_actu"]
            if "mots_cles_actu" in travail.columns
            else pd.Series([None] * len(travail), index=travail.index)
        )
        scores = (
            travail["score_sentiment_actu"]
            if "score_sentiment_actu" in travail.columns
            else pd.Series([None] * len(travail), index=travail.index)
        )
        travail["proxy_perturbation_actu"] = [
            proxy_perturbation_ligne(n, m, s)
            for n, m, s in zip(travail["nb_articles_actu"], mots, scores)
        ]
    travail["proxy_perturbation_actu"] = pd.to_numeric(
        travail["proxy_perturbation_actu"], errors="coerce"
    ).fillna(0.0)
    return travail


def diagnostiquer_volumetrie(df: pd.DataFrame) -> dict:
    """
    Compte les vols, le proxy retard, la météo et les routes assez peuplées.
    """
    nb_vols = int(len(df))
    retard_non_null = int(df["retard_minutes"].notna().sum()) if nb_vols else 0
    retard_non_null_avec_meteo = (
        int(
            (df["retard_minutes"].notna() & df["weather_origin_id"].notna()).sum()
        )
        if nb_vols
        else 0
    )
    weather_origin = int(df["weather_origin_id"].notna().sum()) if nb_vols else 0
    weather_dest = int(df["weather_dest_id"].notna().sum()) if nb_vols else 0
    dest_ok = int(df["est_arrival_airport"].notna().sum()) if nb_vols else 0
    duree_ok = (
        int(df["last_seen"].notna().sum()) if nb_vols and "last_seen" in df.columns else 0
    )
    durees_gt_seuil = 0
    duree_max_minutes = None
    if nb_vols and "last_seen" in df.columns and "first_seen" in df.columns:
        debut = pd.to_datetime(df["first_seen"], utc=True)
        fin = pd.to_datetime(df["last_seen"], utc=True)
        durees = (fin - debut).dt.total_seconds() / 60.0
        valides = durees.dropna()
        if not valides.empty:
            duree_max_minutes = float(valides.max())
            durees_gt_seuil = int((valides > SEUIL_DUREE_MAX_MINUTES).sum())

    news_score_non_null = 0
    vols_avec_nb_articles = 0
    nb_jours_news_recouvrants = 0
    if nb_vols and "score_sentiment_actu" in df.columns:
        news_score_non_null = int(df["score_sentiment_actu"].notna().sum())
    if nb_vols and "nb_articles_actu" in df.columns:
        nb_art = pd.to_numeric(df["nb_articles_actu"], errors="coerce").fillna(0)
        vols_avec_nb_articles = int((nb_art > 0).sum())
        if "date_id" in df.columns:
            nb_jours_news_recouvrants = int(df.loc[nb_art > 0, "date_id"].nunique())

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
        "retard_non_null_avec_meteo": retard_non_null_avec_meteo,
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
        "duree_max_minutes": duree_max_minutes,
        "durees_gt_seuil_8h": durees_gt_seuil,
        "seuil_duree_max_minutes": SEUIL_DUREE_MAX_MINUTES,
        "news_score_non_null": news_score_non_null,
        "vols_avec_nb_articles": vols_avec_nb_articles,
        "nb_jours_news_recouvrants": nb_jours_news_recouvrants,
    }


def retenir_cible(diag: dict) -> str:
    """
    Retourne le code de cible entraînable d'après les effectifs du diagnostic.

    L'option C (proxy ``retard_minutes``) n'est retenue que s'il y a au moins
    ``SEUIL_MIN_LIGNES_ENTRAINEMENT`` lignes non NULL **avec** météo origine.
    """
    retard_n = int(diag.get("retard_non_null") or 0)
    retard_meteo = int(diag.get("retard_non_null_avec_meteo") or 0)
    vols_a = int(diag.get("vols_meteo_sur_routes_ge5") or 0)
    vols_b = int(diag.get("meteo_et_duree") or 0)
    if retard_meteo >= SEUIL_MIN_LIGNES_ENTRAINEMENT:
        return "C"
    if vols_a >= SEUIL_MIN_LIGNES_ENTRAINEMENT:
        return "A"
    if vols_b >= SEUIL_MIN_LIGNES_ENTRAINEMENT:
        return "B"
    raise ValueError(
        "Aucune cible entraînable : proxy trop creux "
        f"({retard_n} lignes dont {retard_meteo} avec météo origine, "
        f"option C interdite sous {SEUIL_MIN_LIGNES_ENTRAINEMENT}), "
        f"routes trop rares pour une classe OD ({vols_a} vols), "
        f"durées avec météo origine insuffisantes ({vols_b} lignes)."
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


def exclure_durees_aberrantes(
    df: pd.DataFrame,
    seuil_max: float = SEUIL_DUREE_MAX_MINUTES,
) -> pd.DataFrame:
    """
    Retire les durées non positives ou strictement au-delà du plafond (défaut 8 h).
    """
    if NOM_CIBLE not in df.columns:
        travail = ajouter_cible_duree(df)
    else:
        travail = df.copy()
    n_avant = len(travail)
    masque = (
        travail[NOM_CIBLE].notna()
        & (travail[NOM_CIBLE] > 0)
        & (travail[NOM_CIBLE] <= seuil_max)
    )
    filtre = travail.loc[masque].copy()
    n_exclues = n_avant - len(filtre)
    logger.info(
        "Durées aberrantes : %s ligne(s) exclue(s) (plafond %s min).",
        n_exclues,
        seuil_max,
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


def construire_features(
    df: pd.DataFrame,
    avec_actu: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Construit la matrice X et le vecteur y (durée en minutes) sans colonnes interdites.
    """
    if NOM_CIBLE not in df.columns:
        travail = ajouter_cible_duree(df)
    else:
        travail = df.copy()
    travail = ajouter_features_actu(travail)
    travail = travail.dropna(subset=[NOM_CIBLE]).copy()
    travail["hub_origine"] = travail["est_departure_airport"]
    travail["heure_utc"] = _heure_utc(travail["first_seen"])
    colonnes = liste_colonnes_features(avec_actu)
    manquantes = [c for c in colonnes if c not in travail.columns]
    if manquantes:
        raise KeyError(f"Colonnes de features absentes : {manquantes}.")
    X = travail.loc[:, list(colonnes)].copy()
    for colonne in colonnes:
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
    avec_actu: bool = True,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series, datetime, datetime, int]:
    """
    Filtre, ajoute la cible, écarte les durées aberrantes, split temporel, X/y.
    """
    filtre = filtrer_jeu_modele(df)
    avec_cible = ajouter_cible_duree(filtre)
    n_avant_plafond = len(avec_cible)
    avec_cible = exclure_durees_aberrantes(avec_cible)
    n_exclues_duree = n_avant_plafond - len(avec_cible)
    if len(avec_cible) < SEUIL_MIN_LIGNES_ENTRAINEMENT:
        raise ValueError(
            f"Jeu trop petit pour entraîner ({len(avec_cible)} lignes, "
            f"minimum {SEUIL_MIN_LIGNES_ENTRAINEMENT})."
        )
    train_brut, test_brut = split_temporel(avec_cible, fraction_train=fraction_train)
    X_train, y_train = construire_features(train_brut, avec_actu=avec_actu)
    X_test, y_test = construire_features(test_brut, avec_actu=avec_actu)
    X_train, X_test = aligner_categories(X_train, X_test)
    debut_test = pd.to_datetime(test_brut["first_seen"], utc=True).min().to_pydatetime()
    fin_train = pd.to_datetime(train_brut["first_seen"], utc=True).max().to_pydatetime()
    return X_train, y_train, X_test, y_test, fin_train, debut_test, n_exclues_duree
