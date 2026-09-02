"""
Jointure vols ↔ météo horaire Open-Meteo (expérience, hors ETL prod).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from src.processing.etl import DOSSIER_RAW_DEFAUT, SEUIL_MIN_VOLS_ROUTE
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLONNES_HORAIRES = {
    "temperature_2m": "temperature_celsius",
    "wind_speed_10m": "wind_speed",
    "wind_gusts_10m": "wind_gust",
    "precipitation": "rain_1h",
    "visibility": "visibility",
    "relative_humidity_2m": "humidity",
}


def dernier_json_openmeteo(dossier: Path | None = None) -> Path | None:
    """Plus récent `openmeteo_*.json` dans data/raw/."""
    racine = Path(dossier) if dossier is not None else DOSSIER_RAW_DEFAUT
    fichiers = sorted(racine.glob("openmeteo_*.json"))
    return fichiers[-1] if fichiers else None


def hourly_vers_dataframe(icao: str, payload: dict) -> pd.DataFrame:
    """Aplatit le bloc `hourly` Open-Meteo en une ligne par heure UTC."""
    hourly = payload.get("hourly") or {}
    instants = hourly.get("time") or []
    if not instants:
        return pd.DataFrame()
    cadre = pd.DataFrame({"icao": icao, "instant_heure": instants})
    cadre["instant_heure"] = pd.to_datetime(cadre["instant_heure"], utc=True)
    for source, cible in COLONNES_HORAIRES.items():
        if source in hourly:
            cadre[cible] = pd.to_numeric(hourly[source], errors="coerce")
        else:
            cadre[cible] = pd.NA
    return cadre


def charger_series_hubs(chemin: Path) -> pd.DataFrame:
    """Empile les 10 hubs d'un JSON Open-Meteo."""
    with Path(chemin).open(encoding="utf-8") as fichier:
        brut = json.load(fichier)
    blocs = brut.get("hubs") or {}
    frames = []
    for icao, contenu in blocs.items():
        reponse = contenu.get("reponse") if isinstance(contenu, dict) else contenu
        if not isinstance(reponse, dict):
            continue
        frames.append(hourly_vers_dataframe(str(icao), reponse))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _joindre_cote(
    vols: pd.DataFrame,
    series: pd.DataFrame,
    colonne_icao: str,
    colonne_instant: str,
    suffixe: str,
) -> pd.DataFrame:
    if series.empty:
        return vols
    travail = vols.copy()
    instants = pd.to_datetime(travail[colonne_instant], utc=True)
    travail["_heure_join"] = instants.dt.floor("h")
    droit = series.rename(
        columns={
            "icao": "_icao_join",
            "instant_heure": "_heure_join",
            **{nom: f"{nom}_{suffixe}" for nom in COLONNES_HORAIRES.values()},
        }
    )
    fusion = travail.merge(
        droit,
        how="left",
        left_on=[colonne_icao, "_heure_join"],
        right_on=["_icao_join", "_heure_join"],
    )
    return fusion.drop(columns=["_heure_join", "_icao_join"], errors="ignore")


RENOMMAGE_FEATURES = {
    "temperature_celsius_origine": "temperature_origine",
    "wind_speed_origine": "vent_origine",
    "wind_gust_origine": "rafale_origine",
    "rain_1h_origine": "pluie_origine",
    "visibility_origine": "visibilite_origine",
    "humidity_origine": "humidite_origine",
    "temperature_celsius_dest": "temperature_dest",
    "wind_speed_dest": "vent_dest",
    "wind_gust_dest": "rafale_dest",
    "rain_1h_dest": "pluie_dest",
    "visibility_dest": "visibilite_dest",
    "humidity_dest": "humidite_dest",
}


def joindre_meteo_horaire(vols: pd.DataFrame, series: pd.DataFrame) -> pd.DataFrame:
    """
    Colle la météo origine (heure de first_seen) et destination (last_seen)
    si l'ICAO est l'un des dix hubs.
    """
    avec_orig = _joindre_cote(
        vols, series, "est_departure_airport", "first_seen", "origine"
    )
    fusion = _joindre_cote(
        avec_orig, series, "est_arrival_airport", "last_seen", "dest"
    )
    deja_la = [c for c in RENOMMAGE_FEATURES.values() if c in fusion.columns]
    if deja_la:
        fusion = fusion.drop(columns=deja_la)
    fusion = fusion.rename(columns=RENOMMAGE_FEATURES)
    if len(fusion) and "temperature_origine" in fusion.columns:
        taux = float(fusion["temperature_origine"].notna().mean())
        logger.info(
            "Jointure Open-Meteo : météo origine sur %.1f %% des vols.",
            100.0 * taux,
        )
    return fusion


def dates_fenetre_vols(vols: pd.DataFrame) -> tuple[date, date]:
    """Min/max des first_seen en dates UTC (inclusives)."""
    instants = pd.to_datetime(vols["first_seen"], utc=True)
    debut = instants.min().date()
    fin = instants.max().date()
    return debut, fin


def retard_sans_fuite(
    train: pd.DataFrame,
    test: pd.DataFrame,
    colonne_duree: str = "duree_minutes",
    seuil_min: int = SEUIL_MIN_VOLS_ROUTE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Écart à la médiane de route calculée **sur le train seul**.

    Les OD avec moins de ``seuil_min`` vols en train sont écartées
    (train et test). Pas de médiane calculée sur le test.
    """
    cles = ["est_departure_airport", "est_arrival_airport"]
    stats = (
        train.dropna(subset=cles + [colonne_duree])
        .groupby(cles, dropna=False)[colonne_duree]
        .agg(["median", "size"])
        .reset_index()
        .rename(columns={"median": "mediane_route_train", "size": "n_train_od"})
    )
    stats = stats.loc[stats["n_train_od"] >= seuil_min]
    if stats.empty:
        raise ValueError(
            "Aucune route OD n'a assez de vols en train pour un proxy "
            f"(seuil {seuil_min})."
        )

    def _appliquer(cadre: pd.DataFrame) -> pd.DataFrame:
        fusion = cadre.merge(stats, how="inner", on=cles)
        fusion["retard_sans_fuite"] = (
            fusion[colonne_duree] - fusion["mediane_route_train"]
        )
        return fusion

    return _appliquer(train), _appliquer(test)

