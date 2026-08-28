"""
Tests unitaires des transformations ETL sans base de données
(jointure météo, date_id, proxy de retard, SQL d'upsert).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.processing.etl import (
    SQL_UPSERT_NEWS,
    SQL_UPSERT_VOL,
    SQL_UPSERT_WEATHER,
    calculer_retard_proxy,
    date_id_depuis,
    rattacher_observation_meteo,
    selectionner_fichiers_incrementaux,
    synthetiser_journal_ingestion,
    unix_vers_utc,
)


def test_date_id_depuis_instant_utc() -> None:
    """Vérifie le format YYYYMMDD calé sur UTC."""
    instant = datetime(2026, 8, 25, 23, 30, tzinfo=timezone.utc)
    assert date_id_depuis(instant) == 20260825


def test_unix_vers_utc_retourne_un_datetime_aware() -> None:
    """Vérifie la conversion d'un timestamp Unix en datetime UTC."""
    instant = unix_vers_utc(1_700_000_000)
    assert instant is not None
    assert instant.tzinfo is not None
    assert instant.utcoffset() == timedelta(0)


def test_rattacher_observation_meteo_plus_proche_dans_la_fenetre() -> None:
    """
    Vérifie que l'observation retenue est la plus proche, et que hors fenêtre
    ou hors hub le résultat est None.
    """
    t0 = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    observations = pd.DataFrame(
        {
            "weather_id": [10, 11, 12],
            "airport_id": [1, 1, 2],
            "horodatage_observation": [
                t0 - timedelta(hours=2),
                t0 + timedelta(minutes=20),
                t0,
            ],
        }
    )

    assert rattacher_observation_meteo(t0, observations, airport_id=1) == 11
    assert (
        rattacher_observation_meteo(
            t0 + timedelta(hours=5), observations, airport_id=1
        )
        is None
    )
    assert rattacher_observation_meteo(t0, observations, airport_id=None) is None
    assert rattacher_observation_meteo(t0, observations, airport_id=99) is None


def test_calculer_retard_proxy_null_si_route_trop_rare() -> None:
    """Vérifie que le proxy reste nul sans assez d'historique sur la route."""
    base = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
    df = pd.DataFrame(
        {
            "est_departure_airport": ["LFPG", "LFPG"],
            "est_arrival_airport": ["EGLL", "EGLL"],
            "first_seen": [base, base],
            "last_seen": [base + timedelta(hours=1), base + timedelta(hours=2)],
        }
    )
    retard = calculer_retard_proxy(df)
    assert retard.isna().all()


def test_calculer_retard_proxy_ecart_a_la_mediane_si_effectif_suffisant() -> None:
    """Vérifie le proxy durée − médiane de route dès que l'effectif est atteint."""
    base = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
    durees_heures = [1, 1, 1, 1, 2]
    df = pd.DataFrame(
        {
            "est_departure_airport": ["LFPG"] * 5,
            "est_arrival_airport": ["EGLL"] * 5,
            "first_seen": [base] * 5,
            "last_seen": [base + timedelta(hours=h) for h in durees_heures],
        }
    )
    retard = calculer_retard_proxy(df)
    assert retard.notna().all()
    assert retard.iloc[0] == 0.0
    assert retard.iloc[-1] == 60.0


def test_requetes_upsert_contiennent_on_conflict() -> None:
    """Vérifie que les trois upserts SQL portent bien une clause ON CONFLICT."""
    assert "ON CONFLICT (airport_id, horodatage_observation)" in SQL_UPSERT_WEATHER
    assert "ON CONFLICT (date_id)" in SQL_UPSERT_NEWS
    assert "ON CONFLICT (icao24, first_seen," in SQL_UPSERT_VOL
    assert "COALESCE(est_departure_airport" in SQL_UPSERT_VOL


def test_synthetiser_journal_ignore_les_lignes_sans_fin() -> None:
    """Vérifie qu'un chargement sans horodatage_fin n'est pas traité comme réussi."""
    fin = datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc)
    ingeres, derniere = synthetiser_journal_ingestion(
        [
            {"fichier_source": "data/raw/a.json", "horodatage_fin": None},
            {"fichier_source": "data/raw/b.json", "horodatage_fin": fin},
            {"fichier_source": None, "horodatage_fin": fin},
        ]
    )
    assert ingeres == {"data/raw/b.json"}
    assert derniere == fin


def test_selectionner_skip_si_chemin_deja_journalise(tmp_path: Path) -> None:
    """Vérifie le skip par chemin relatif déjà présent dans ingestion_log."""
    ancien = tmp_path / "deja.json"
    nouveau = tmp_path / "nouveau.json"
    ancien.write_text("{}", encoding="utf-8")
    nouveau.write_text("{}", encoding="utf-8")
    a_charger, ignores = selectionner_fichiers_incrementaux(
        [ancien, nouveau],
        fichiers_ingeres={"deja.json"},
        relativiser=lambda chemin: Path(chemin).name,
    )
    assert ignores == [ancien]
    assert a_charger == [nouveau]


def test_selectionner_skip_si_mtime_anterieure_au_journal(tmp_path: Path) -> None:
    """
    Vérifie le skip par date de fichier, pour les journaux par lot sans nom
    de fichier (premières passes ETL).
    """
    ancien = tmp_path / "old.json"
    recent = tmp_path / "new.json"
    ancien.write_text("{}", encoding="utf-8")
    recent.write_text("{}", encoding="utf-8")
    watermark = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)
    mtimes = {
        ancien: watermark - timedelta(hours=2),
        recent: watermark + timedelta(minutes=10),
    }
    a_charger, ignores = selectionner_fichiers_incrementaux(
        [ancien, recent],
        fichiers_ingeres=set(),
        derniere_ingestion=watermark,
        relativiser=lambda chemin: Path(chemin).name,
        mtime_de=lambda chemin: mtimes[Path(chemin)],
    )
    assert ignores == [ancien]
    assert a_charger == [recent]


def test_selectionner_charge_tout_sans_journal(tmp_path: Path) -> None:
    """Vérifie qu'une base vierge relit tous les JSON (relançable à froid)."""
    fichier = tmp_path / "brut.json"
    fichier.write_text("{}", encoding="utf-8")
    a_charger, ignores = selectionner_fichiers_incrementaux(
        [fichier],
        fichiers_ingeres=set(),
        derniere_ingestion=None,
        relativiser=lambda chemin: Path(chemin).name,
    )
    assert a_charger == [fichier]
    assert ignores == []


def test_selectionner_actualites_rejoue_toute_la_serie_si_un_nouveau(
    tmp_path: Path,
) -> None:
    """
    Vérifie qu'un JSON d'actualités nouveau relance toute la série, pour
    ne pas écraser l'agrégat journalier avec un sous-ensemble d'articles.
    """
    ancien = tmp_path / "news_old.json"
    nouveau = tmp_path / "news_new.json"
    ancien.write_text("{}", encoding="utf-8")
    nouveau.write_text("{}", encoding="utf-8")
    watermark = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)
    mtimes = {
        ancien: watermark - timedelta(days=1),
        nouveau: watermark + timedelta(hours=1),
    }
    a_charger, ignores = selectionner_fichiers_incrementaux(
        [ancien, nouveau],
        fichiers_ingeres=set(),
        derniere_ingestion=watermark,
        rejouer_tous_si_nouveau=True,
        relativiser=lambda chemin: Path(chemin).name,
        mtime_de=lambda chemin: mtimes[Path(chemin)],
    )
    assert a_charger == [ancien, nouveau]
    assert ignores == []


def test_selectionner_actualites_skip_si_toute_la_serie_deja_ingeree(
    tmp_path: Path,
) -> None:
    """Vérifie que le rejeu d'agrégat ne relance rien si aucun JSON n'est nouveau."""
    premier = tmp_path / "news_a.json"
    second = tmp_path / "news_b.json"
    premier.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    watermark = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)
    mtimes = {
        premier: watermark - timedelta(days=1),
        second: watermark - timedelta(hours=1),
    }
    a_charger, ignores = selectionner_fichiers_incrementaux(
        [premier, second],
        fichiers_ingeres=set(),
        derniere_ingestion=watermark,
        rejouer_tous_si_nouveau=True,
        relativiser=lambda chemin: Path(chemin).name,
        mtime_de=lambda chemin: mtimes[Path(chemin)],
    )
    assert a_charger == []
    assert ignores == [premier, second]
