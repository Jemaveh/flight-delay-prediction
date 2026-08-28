"""
Orchestrateur ETL : JSON bruts (data/raw/) vers le schéma en étoile PostgreSQL.

Ordre de chargement : dim_date → dim_airport → dim_weather →
dim_news_sentiment → fact_flights. Incrémental : les JSON déjà ingérés
avec succès (ingestion_log / mtime) sont sautés ; l'upsert ON CONFLICT
reste le filet d'idempotence si un fichier est relou.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from src.database.db_connector import (
    creer_engine,
    ensemencer_aeroports,
    ensemencer_dates,
    executer_schema,
)
from src.processing.data_cleaning import (
    aplatir_actualites,
    aplatir_meteo,
    aplatir_vols,
    charger_json,
    nettoyer_actualites,
    nettoyer_meteo,
    nettoyer_vols,
)
from src.utils.chemins import RACINE_PROJET, chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

DOSSIER_RAW_DEFAUT = RACINE_PROJET / "data" / "raw"
ECART_MAX_METEO = timedelta(hours=3)
SEUIL_MIN_VOLS_ROUTE = 5

SQL_UPSERT_WEATHER = """
INSERT INTO dim_weather (
    airport_id, date_id, horodatage_observation,
    temperature_celsius, feels_like_celsius, humidity, pressure,
    wind_speed, wind_gust, rain_1h, visibility, description_ciel
)
VALUES (
    :airport_id, :date_id, :horodatage_observation,
    :temperature_celsius, :feels_like_celsius, :humidity, :pressure,
    :wind_speed, :wind_gust, :rain_1h, :visibility, :description_ciel
)
ON CONFLICT (airport_id, horodatage_observation) DO UPDATE SET
    date_id = EXCLUDED.date_id,
    temperature_celsius = EXCLUDED.temperature_celsius,
    feels_like_celsius = EXCLUDED.feels_like_celsius,
    humidity = EXCLUDED.humidity,
    pressure = EXCLUDED.pressure,
    wind_speed = EXCLUDED.wind_speed,
    wind_gust = EXCLUDED.wind_gust,
    rain_1h = EXCLUDED.rain_1h,
    visibility = EXCLUDED.visibility,
    description_ciel = EXCLUDED.description_ciel
"""

SQL_UPSERT_NEWS = """
INSERT INTO dim_news_sentiment (date_id, nb_articles, mots_cles, score_sentiment)
VALUES (:date_id, :nb_articles, :mots_cles, :score_sentiment)
ON CONFLICT (date_id) DO UPDATE SET
    nb_articles = EXCLUDED.nb_articles,
    mots_cles = EXCLUDED.mots_cles
"""

SQL_UPSERT_VOL = """
INSERT INTO fact_flights (
    icao24, callsign, first_seen, last_seen,
    est_departure_airport, est_arrival_airport, date_id,
    airport_origin_id, airport_dest_id,
    weather_origin_id, weather_dest_id, retard_minutes
)
VALUES (
    :icao24, :callsign, :first_seen, :last_seen,
    :est_departure_airport, :est_arrival_airport, :date_id,
    :airport_origin_id, :airport_dest_id,
    :weather_origin_id, :weather_dest_id, :retard_minutes
)
ON CONFLICT (icao24, first_seen, (COALESCE(est_departure_airport, ''))) DO UPDATE SET
    callsign = EXCLUDED.callsign,
    last_seen = EXCLUDED.last_seen,
    est_arrival_airport = EXCLUDED.est_arrival_airport,
    date_id = EXCLUDED.date_id,
    airport_origin_id = EXCLUDED.airport_origin_id,
    airport_dest_id = EXCLUDED.airport_dest_id,
    weather_origin_id = EXCLUDED.weather_origin_id,
    weather_dest_id = EXCLUDED.weather_dest_id,
    retard_minutes = EXCLUDED.retard_minutes
"""

SQL_LOG = """
INSERT INTO ingestion_log (
    source, fichier_source, horodatage_debut, horodatage_fin,
    lignes_lues, lignes_rejetees, lignes_inserees
)
VALUES (
    :source, :fichier_source, :horodatage_debut, :horodatage_fin,
    :lignes_lues, :lignes_rejetees, :lignes_inserees
)
"""


def date_id_depuis(instant: datetime) -> int:
    """
    Convertit un instant UTC en identifiant calendaire YYYYMMDD.
    """
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    else:
        instant = instant.astimezone(timezone.utc)
    return int(instant.strftime("%Y%m%d"))


def unix_vers_utc(valeur) -> datetime | None:
    """
    Convertit un timestamp Unix (secondes) en datetime UTC.
    """
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    return datetime.fromtimestamp(int(valeur), tz=timezone.utc)


def _vers_python(valeur):
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    if hasattr(valeur, "item"):
        return valeur.item()
    return valeur


def assurer_dates(connexion: Connection, date_ids: list[int]) -> None:
    """
    Insère les date_id manquants dans dim_date (ON CONFLICT DO NOTHING).
    """
    requete = text(
        """
        INSERT INTO dim_date (date_id, date, jour_semaine, mois, est_ferie)
        VALUES (:date_id, :date, :jour_semaine, :mois, :est_ferie)
        ON CONFLICT (date_id) DO NOTHING
        """
    )
    for date_id in sorted(set(int(d) for d in date_ids if pd.notna(d))):
        jour = datetime.strptime(str(date_id), "%Y%m%d").date()
        connexion.execute(
            requete,
            {
                "date_id": date_id,
                "date": jour,
                "jour_semaine": jour.isoweekday(),
                "mois": jour.month,
                "est_ferie": False,
            },
        )


def rattacher_observation_meteo(
    horodatage_vol: datetime | None,
    observations: pd.DataFrame,
    airport_id: int | None,
    ecart_max: timedelta = ECART_MAX_METEO,
) -> int | None:
    """
    Retourne l'identifiant de l'observation météo la plus proche dans le temps,
    si l'aéroport est un hub et si l'écart reste sous `ecart_max`.
    """
    if horodatage_vol is None or airport_id is None or observations.empty:
        return None
    if isinstance(airport_id, float) and pd.isna(airport_id):
        return None
    candidates = observations.loc[observations["airport_id"] == airport_id]
    if candidates.empty:
        return None
    ecarts = (candidates["horodatage_observation"] - horodatage_vol).abs()
    index_min = ecarts.idxmin()
    if ecarts.loc[index_min] > ecart_max:
        return None
    return int(candidates.loc[index_min, "weather_id"])


def calculer_retard_proxy(df: pd.DataFrame) -> pd.Series:
    """
    Proxy de retard : durée observée moins la médiane de la même route,
    si la destination est connue et si la route a assez d'observations.
    """
    if df.empty:
        return pd.Series(dtype="float64")
    duree = (
        pd.to_datetime(df["last_seen"], utc=True)
        - pd.to_datetime(df["first_seen"], utc=True)
    ).dt.total_seconds() / 60.0
    travail = df.assign(_duree=duree)
    groupe = ["est_departure_airport", "est_arrival_airport"]
    mediane = travail.groupby(groupe)["_duree"].transform("median")
    effectif = travail.groupby(groupe)["_duree"].transform("size")
    retard = duree - mediane
    retard = retard.where(effectif >= SEUIL_MIN_VOLS_ROUTE)
    retard = retard.where(df["est_arrival_airport"].notna())
    return retard


def _lister_fichiers(dossier: Path, motif: str) -> list[Path]:
    return sorted(dossier.glob(motif))


def horodatage_modification_utc(chemin: Path) -> datetime:
    """
    Retourne la date de modification du fichier, en UTC.
    """
    return datetime.fromtimestamp(chemin.stat().st_mtime, tz=timezone.utc)


def synthetiser_journal_ingestion(
    lignes: list[dict],
) -> tuple[set[str], datetime | None]:
    """
    Réduit des lignes d'ingestion_log en fichiers déjà réussis et dernier
    horodatage de fin.
    """
    ingeres: set[str] = set()
    derniere: datetime | None = None
    for ligne in lignes:
        fin = ligne.get("horodatage_fin")
        if not isinstance(fin, datetime):
            continue
        if fin.tzinfo is None:
            fin = fin.replace(tzinfo=timezone.utc)
        else:
            fin = fin.astimezone(timezone.utc)
        if derniere is None or fin > derniere:
            derniere = fin
        nom = ligne.get("fichier_source")
        if nom:
            ingeres.add(str(nom))
    return ingeres, derniere


def selectionner_fichiers_incrementaux(
    fichiers: list[Path],
    fichiers_ingeres: set[str],
    derniere_ingestion: datetime | None = None,
    *,
    rejouer_tous_si_nouveau: bool = False,
    relativiser=chemin_relatif_projet,
    mtime_de=horodatage_modification_utc,
) -> tuple[list[Path], list[Path]]:
    """
    Sépare les JSON à charger de ceux déjà ingérés avec succès.

    Un fichier est ignoré s'il figure dans `fichiers_ingeres`, ou si sa
    date de modification est antérieure ou égale à `derniere_ingestion`.
    Si `rejouer_tous_si_nouveau` est vrai, un seul fichier nouveau relance
    toute la série (agrégat journalier des actualités).
    """
    a_charger: list[Path] = []
    ignores: list[Path] = []
    for chemin in fichiers:
        deja = relativiser(chemin) in fichiers_ingeres
        if not deja and derniere_ingestion is not None:
            deja = mtime_de(chemin) <= derniere_ingestion
        if deja:
            ignores.append(chemin)
        else:
            a_charger.append(chemin)

    if rejouer_tous_si_nouveau and a_charger:
        return list(fichiers), []
    return a_charger, ignores


def _etat_ingestion(
    connexion: Connection, source: str
) -> tuple[set[str], datetime | None]:
    lignes = connexion.execute(
        text(
            """
            SELECT fichier_source, horodatage_fin
            FROM ingestion_log
            WHERE source = :source
            """
        ),
        {"source": source},
    ).mappings()
    return synthetiser_journal_ingestion([dict(ligne) for ligne in lignes])


def _journaliser_skips(chemins: list[Path], source: str) -> None:
    for chemin in chemins:
        logger.info(
            "Fichier déjà ingéré, skip (%s) : '%s'.",
            source,
            chemin_relatif_projet(chemin),
        )
    if chemins:
        logger.info(
            "%s : %s fichier(s) déjà ingéré(s), skip.",
            source,
            len(chemins),
        )


def _lire_observations_meteo(connexion: Connection) -> pd.DataFrame:
    """
    Relit dim_weather pour la jointure vols, y compris si les JSON météo
    ont été sautés.
    """
    chargees = connexion.execute(
        text(
            """
            SELECT weather_id, airport_id, horodatage_observation
            FROM dim_weather
            """
        )
    ).mappings()
    return pd.DataFrame(list(chargees))


def _charger_correspondance_aeroports(connexion: Connection) -> dict[str, int]:
    lignes = connexion.execute(
        text("SELECT airport_id, code_icao FROM dim_airport")
    ).mappings()
    return {ligne["code_icao"].strip(): int(ligne["airport_id"]) for ligne in lignes}


def _journaliser(
    connexion: Connection,
    source: str,
    fichier: str | None,
    debut: datetime,
    lues: int,
    rejetees: int,
    inserees: int,
) -> None:
    connexion.execute(
        text(SQL_LOG),
        {
            "source": source,
            "fichier_source": fichier,
            "horodatage_debut": debut,
            "horodatage_fin": datetime.now(timezone.utc),
            "lignes_lues": lues,
            "lignes_rejetees": rejetees,
            "lignes_inserees": inserees,
        },
    )


def _charger_meteo(
    connexion: Connection,
    dossier_raw: Path,
    icao_vers_id: dict[str, int],
) -> tuple[pd.DataFrame, dict[str, int]]:
    fichiers = _lister_fichiers(dossier_raw, "openweather_*.json")
    ingeres, derniere = _etat_ingestion(connexion, "openweather")
    a_charger, ignores = selectionner_fichiers_incrementaux(
        fichiers, ingeres, derniere
    )
    _journaliser_skips(ignores, "openweather")

    cadres: list[pd.DataFrame] = []
    lues = 0
    rejetees = 0
    traites: list[tuple[Path, datetime, int, int, int]] = []
    for chemin in a_charger:
        debut = datetime.now(timezone.utc)
        brut = charger_json(chemin)
        plat = aplatir_meteo(brut)
        propre, bilan = nettoyer_meteo(plat)
        lues += bilan["lues"]
        rejetees += bilan["rejetees"]
        logger.info(
            "Météo '%s' : %s lues, %s rejetées, %s conservées.",
            chemin_relatif_projet(chemin),
            bilan["lues"],
            bilan["rejetees"],
            bilan["conservees"],
        )
        if not propre.empty:
            cadres.append(propre)
        traites.append(
            (chemin, debut, bilan["lues"], bilan["rejetees"], bilan["conservees"])
        )

    enregistrements_n = 0
    if cadres:
        df = pd.concat(cadres, ignore_index=True)
        df["horodatage_observation"] = df["dt"].map(unix_vers_utc)
        df["airport_id"] = df["code_icao"].map(icao_vers_id)
        df = df.dropna(subset=["airport_id", "horodatage_observation"]).copy()
        df["airport_id"] = df["airport_id"].astype(int)
        df["date_id"] = df["horodatage_observation"].map(date_id_depuis)
        assurer_dates(connexion, df["date_id"].tolist())

        enregistrements = df.to_dict(orient="records")
        enregistrements_n = len(enregistrements)
        for ligne in enregistrements:
            connexion.execute(
                text(SQL_UPSERT_WEATHER),
                {
                    "airport_id": _vers_python(ligne["airport_id"]),
                    "date_id": _vers_python(ligne["date_id"]),
                    "horodatage_observation": ligne["horodatage_observation"],
                    "temperature_celsius": _vers_python(
                        ligne.get("temperature_celsius")
                    ),
                    "feels_like_celsius": _vers_python(ligne.get("feels_like_celsius")),
                    "humidity": _vers_python(ligne.get("humidity")),
                    "pressure": _vers_python(ligne.get("pressure")),
                    "wind_speed": _vers_python(ligne.get("wind_speed")),
                    "wind_gust": _vers_python(ligne.get("wind_gust")),
                    "rain_1h": _vers_python(ligne.get("rain_1h")),
                    "visibility": _vers_python(ligne.get("visibility")),
                    "description_ciel": ligne.get("description_ciel"),
                },
            )

    for chemin, debut, lues_f, rej_f, cons_f in traites:
        _journaliser(
            connexion,
            "openweather",
            chemin_relatif_projet(chemin),
            debut,
            lues_f,
            rej_f,
            cons_f,
        )

    return _lire_observations_meteo(connexion), {
        "lues": lues,
        "rejetees": rejetees,
        "inserees": enregistrements_n,
        "ignorees": len(ignores),
    }


def _charger_actualites(connexion: Connection, dossier_raw: Path) -> dict[str, int]:
    fichiers = _lister_fichiers(dossier_raw, "newsapi_*.json")
    ingeres, derniere = _etat_ingestion(connexion, "newsapi")
    a_charger, ignores = selectionner_fichiers_incrementaux(
        fichiers, ingeres, derniere
    )
    if a_charger and ignores:
        logger.info(
            "newsapi : au moins un JSON nouveau, rejeu de toute la série "
            "(agrégat journalier)."
        )
        a_charger, ignores = list(fichiers), []
    _journaliser_skips(ignores, "newsapi")
    if not a_charger:
        return {"lues": 0, "rejetees": 0, "inserees": 0, "ignorees": len(ignores)}

    cadres: list[pd.DataFrame] = []
    lues = 0
    rejetees = 0
    traites: list[tuple[Path, datetime, int, int, int]] = []
    for chemin in a_charger:
        debut = datetime.now(timezone.utc)
        brut = charger_json(chemin)
        plat = aplatir_actualites(brut)
        propre, bilan = nettoyer_actualites(plat)
        lues += bilan["lues"]
        rejetees += bilan["rejetees"]
        logger.info(
            "Actualités '%s' : %s lues, %s rejetées, %s conservées.",
            chemin_relatif_projet(chemin),
            bilan["lues"],
            bilan["rejetees"],
            bilan["conservees"],
        )
        if not propre.empty:
            cadres.append(propre)
        traites.append(
            (chemin, debut, bilan["lues"], bilan["rejetees"], bilan["conservees"])
        )

    inserees = 0
    rejetees_global = 0
    if cadres:
        df = pd.concat(cadres, ignore_index=True)
        df, bilan_global = nettoyer_actualites(df)
        rejetees_global = bilan_global["rejetees"]
        instants = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
        df = df.assign(published_at=instants).dropna(subset=["published_at"])
        df["date_id"] = df["published_at"].map(
            lambda instant: date_id_depuis(instant.to_pydatetime())
        )
        assurer_dates(connexion, df["date_id"].tolist())

        agregats = (
            df.groupby("date_id")
            .agg(
                nb_articles=("url", "count"),
                mots_cles=(
                    "mots_cles",
                    lambda s: " | ".join(sorted({m for m in s if m})),
                ),
            )
            .reset_index()
        )
        for ligne in agregats.to_dict(orient="records"):
            connexion.execute(
                text(SQL_UPSERT_NEWS),
                {
                    "date_id": int(ligne["date_id"]),
                    "nb_articles": int(ligne["nb_articles"]),
                    "mots_cles": ligne["mots_cles"] or None,
                    "score_sentiment": None,
                },
            )
        inserees = len(agregats)

    for chemin, debut, lues_f, rej_f, cons_f in traites:
        _journaliser(
            connexion,
            "newsapi",
            chemin_relatif_projet(chemin),
            debut,
            lues_f,
            rej_f,
            cons_f,
        )
    return {
        "lues": lues,
        "rejetees": rejetees + rejetees_global,
        "inserees": inserees,
        "ignorees": len(ignores),
    }


def _charger_vols(
    connexion: Connection,
    dossier_raw: Path,
    icao_vers_id: dict[str, int],
    observations: pd.DataFrame,
) -> dict[str, int]:
    fichiers = _lister_fichiers(dossier_raw, "opensky_flights_*.json")
    ingeres, derniere = _etat_ingestion(connexion, "opensky_flights")
    a_charger, ignores = selectionner_fichiers_incrementaux(
        fichiers, ingeres, derniere
    )
    _journaliser_skips(ignores, "opensky_flights")
    if not a_charger:
        return {"lues": 0, "rejetees": 0, "inserees": 0, "ignorees": len(ignores)}

    cadres: list[pd.DataFrame] = []
    lues = 0
    rejetees = 0
    traites: list[tuple[Path, datetime, int, int, int]] = []
    for chemin in a_charger:
        debut = datetime.now(timezone.utc)
        brut = charger_json(chemin)
        plat = aplatir_vols(brut)
        propre, bilan = nettoyer_vols(plat)
        lues += bilan["lues"]
        rejetees += bilan["rejetees"]
        logger.info(
            "Vols '%s' : %s lus, %s rejetés, %s conservés.",
            chemin_relatif_projet(chemin),
            bilan["lues"],
            bilan["rejetees"],
            bilan["conservees"],
        )
        if not propre.empty:
            cadres.append(propre)
        traites.append(
            (chemin, debut, bilan["lues"], bilan["rejetees"], bilan["conservees"])
        )

    enregistrements_n = 0
    rejetees_global = 0
    if cadres:
        df = pd.concat(cadres, ignore_index=True)
        df, bilan_global = nettoyer_vols(df)
        rejetees_global = bilan_global["rejetees"]
        df["first_seen"] = df["first_seen"].map(unix_vers_utc)
        df["last_seen"] = df["last_seen"].map(unix_vers_utc)
        df = df.dropna(subset=["first_seen"]).copy()
        df["date_id"] = df["first_seen"].map(date_id_depuis)
        assurer_dates(connexion, df["date_id"].tolist())
        df["airport_origin_id"] = df["est_departure_airport"].map(icao_vers_id)
        df["airport_dest_id"] = df["est_arrival_airport"].map(icao_vers_id)
        df["retard_minutes"] = calculer_retard_proxy(df)

        if observations.empty:
            df["weather_origin_id"] = None
            df["weather_dest_id"] = None
        else:
            df["weather_origin_id"] = [
                rattacher_observation_meteo(
                    row.first_seen,
                    observations,
                    None
                    if pd.isna(row.airport_origin_id)
                    else int(row.airport_origin_id),
                )
                for row in df.itertuples(index=False)
            ]
            df["weather_dest_id"] = [
                rattacher_observation_meteo(
                    row.last_seen,
                    observations,
                    None
                    if pd.isna(row.airport_dest_id)
                    else int(row.airport_dest_id),
                )
                for row in df.itertuples(index=False)
            ]

        enregistrements = []
        for ligne in df.to_dict(orient="records"):
            enregistrements.append(
                {
                    "icao24": ligne["icao24"],
                    "callsign": ligne.get("callsign"),
                    "first_seen": ligne["first_seen"],
                    "last_seen": ligne.get("last_seen"),
                    "est_departure_airport": ligne.get("est_departure_airport"),
                    "est_arrival_airport": ligne.get("est_arrival_airport"),
                    "date_id": int(ligne["date_id"]),
                    "airport_origin_id": (
                        int(ligne["airport_origin_id"])
                        if pd.notna(ligne.get("airport_origin_id"))
                        else None
                    ),
                    "airport_dest_id": (
                        int(ligne["airport_dest_id"])
                        if pd.notna(ligne.get("airport_dest_id"))
                        else None
                    ),
                    "weather_origin_id": (
                        int(ligne["weather_origin_id"])
                        if pd.notna(ligne.get("weather_origin_id"))
                        else None
                    ),
                    "weather_dest_id": (
                        int(ligne["weather_dest_id"])
                        if pd.notna(ligne.get("weather_dest_id"))
                        else None
                    ),
                    "retard_minutes": (
                        float(ligne["retard_minutes"])
                        if pd.notna(ligne.get("retard_minutes"))
                        else None
                    ),
                }
            )
            connexion.execute(text(SQL_UPSERT_VOL), enregistrements[-1])
        enregistrements_n = len(enregistrements)

    for chemin, debut, lues_f, rej_f, cons_f in traites:
        _journaliser(
            connexion,
            "opensky_flights",
            chemin_relatif_projet(chemin),
            debut,
            lues_f,
            rej_f,
            cons_f,
        )
    return {
        "lues": lues,
        "rejetees": rejetees + rejetees_global,
        "inserees": enregistrements_n,
        "ignorees": len(ignores),
    }


def executer_etl(
    engine: Engine | None = None,
    dossier_raw: Path | None = None,
    appliquer_schema: bool = True,
) -> dict:
    """
    Enchaîne seed, chargement des dimensions puis des faits depuis data/raw/.

    Les JSON déjà ingérés avec succès sont sautés. Un fichier nouveau est
    lu, upserté, puis tracé dans ingestion_log.

    Returns
    -------
    dict
        Bilans par source (lignes lues / rejetées / insérées / ignorées).
    """
    moteur = engine if engine is not None else creer_engine()
    dossier = dossier_raw if dossier_raw is not None else DOSSIER_RAW_DEFAUT

    if appliquer_schema:
        executer_schema(moteur)
        ensemencer_aeroports(moteur)
        ensemencer_dates(moteur)

    with moteur.begin() as connexion:
        icao_vers_id = _charger_correspondance_aeroports(connexion)
        observations, bilan_meteo = _charger_meteo(connexion, dossier, icao_vers_id)
        bilan_news = _charger_actualites(connexion, dossier)
        bilan_vols = _charger_vols(connexion, dossier, icao_vers_id, observations)

    rapport = {
        "openweather": bilan_meteo,
        "newsapi": bilan_news,
        "opensky_flights": bilan_vols,
    }
    logger.info("ETL terminé : %s", rapport)
    return rapport


def mesurer_entrepot(engine: Engine | None = None) -> dict:
    """
    Compte les lignes des tables et les taux de destination / météo / retard.

    Returns
    -------
    dict
        Effectifs globaux, vols par hub (départ et arrivée) et taux de jointure.
    """
    moteur = engine if engine is not None else creer_engine()
    with moteur.connect() as connexion:
        global_ = connexion.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM fact_flights) AS nb_vols,
                    (SELECT COUNT(*) FROM dim_weather) AS nb_meteo,
                    (SELECT COUNT(*) FROM dim_airport) AS nb_aeroports,
                    (SELECT COUNT(*) FROM dim_date) AS nb_dates,
                    (SELECT COUNT(*) FROM dim_news_sentiment) AS nb_jours_actu,
                    (SELECT COUNT(*) FROM fact_flights
                     WHERE est_arrival_airport IS NOT NULL) AS dest_renseignee,
                    (SELECT COUNT(*) FROM fact_flights
                     WHERE weather_origin_id IS NOT NULL) AS weather_origin,
                    (SELECT COUNT(*) FROM fact_flights
                     WHERE weather_dest_id IS NOT NULL) AS weather_dest,
                    (SELECT COUNT(*) FROM fact_flights
                     WHERE retard_minutes IS NULL) AS retard_null
                """
            )
        ).mappings().one()

        par_hub = connexion.execute(
            text(
                """
                SELECT
                    a.code_icao,
                    (SELECT COUNT(*) FROM fact_flights f
                     WHERE f.est_departure_airport = a.code_icao) AS nb_depart,
                    (SELECT COUNT(*) FROM fact_flights f
                     WHERE f.est_arrival_airport = a.code_icao) AS nb_arrivee
                FROM dim_airport a
                ORDER BY a.code_icao
                """
            )
        ).mappings()
        hubs = [dict(ligne) for ligne in par_hub]

    nb_vols = int(global_["nb_vols"])
    dest = int(global_["dest_renseignee"])
    w_orig = int(global_["weather_origin"])
    w_dest = int(global_["weather_dest"])
    retard_null = int(global_["retard_null"])
    return {
        "nb_vols": nb_vols,
        "nb_meteo": int(global_["nb_meteo"]),
        "nb_aeroports": int(global_["nb_aeroports"]),
        "nb_dates": int(global_["nb_dates"]),
        "nb_jours_actu": int(global_["nb_jours_actu"]),
        "dest_renseignee": dest,
        "pct_dest_renseignee": round(100.0 * dest / nb_vols, 1) if nb_vols else None,
        "weather_origin": w_orig,
        "pct_weather_origin": round(100.0 * w_orig / nb_vols, 1) if nb_vols else None,
        "weather_dest": w_dest,
        "pct_weather_dest": round(100.0 * w_dest / nb_vols, 1) if nb_vols else None,
        "retard_null": retard_null,
        "pct_retard_null": round(100.0 * retard_null / nb_vols, 1) if nb_vols else None,
        "par_hub": hubs,
    }


if __name__ == "__main__":
    try:
        rapport = executer_etl()
        mesure = mesurer_entrepot()
        logger.info(
            "Entrepôt après ETL : %s vols, %s observations météo, "
            "%s jours d'actualité.",
            mesure["nb_vols"],
            mesure["nb_meteo"],
            mesure["nb_jours_actu"],
        )
        logger.info("Bilan incrémental : %s", rapport)
    except ValueError as erreur:
        logger.error("%s", erreur)
        logger.error(
            "PostgreSQL n'est pas joignable avec DATABASE_URL. "
            "Lancer une instance locale (installation Windows, ou "
            "`docker run --name airlines-postgres -e POSTGRES_USER=airlines "
            "-e POSTGRES_PASSWORD=airlines -e POSTGRES_DB=airlines_db "
            "-p 5432:5432 -d postgres:16`) puis aligner DATABASE_URL."
        )
        raise SystemExit(1)
