"""
Tests du connecteur PostgreSQL.

Sans instance joignable (DATABASE_URL absent, dialecte non PostgreSQL, ou
serveur down), les tests d'accès réel sont ignorés proprement.
"""

import pytest
from sqlalchemy import text

from config.settings import settings
from src.database.db_connector import creer_engine
from src.ingestion.openweather_client import HUBS_AEROPORTUAIRES
from src.utils.chemins import RACINE_PROJET


def _postgres_joignable() -> bool:
    url = settings.database_url
    if not url.startswith("postgresql"):
        return False
    try:
        engine = creer_engine()
        with engine.connect() as connexion:
            connexion.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def test_creer_engine_refuse_un_dialecte_non_postgres() -> None:
    """
    Vérifie que creer_engine lève ValueError si DATABASE_URL n'est pas
    postgresql:// — sauf si l'URL locale est déjà PostgreSQL, auquel cas
    le test ne s'applique pas.
    """
    if settings.database_url.startswith("postgresql"):
        pytest.skip("DATABASE_URL pointe déjà vers PostgreSQL")
    with pytest.raises(ValueError, match="postgresql"):
        creer_engine()


@pytest.mark.postgres
@pytest.mark.skipif(not _postgres_joignable(), reason="PostgreSQL non joignable")
def test_schema_et_seed_s_appliquent_sur_postgres() -> None:
    """Vérifie l'application du DDL et le seed des dix hubs sur une instance réelle."""
    from src.database.db_connector import ensemencer_aeroports, ensemencer_dates, executer_schema

    engine = creer_engine()
    executer_schema(engine)
    nb_hubs = ensemencer_aeroports(engine)
    nb_jours = ensemencer_dates(engine)
    assert nb_hubs == 10
    assert nb_jours > 0
    with engine.connect() as connexion:
        hubs = connexion.execute(text("SELECT COUNT(*) FROM dim_airport")).scalar()
        assert hubs == 10
        lfpg = connexion.execute(
            text("SELECT code_iata FROM dim_airport WHERE code_icao = 'LFPG'")
        ).scalar()
        assert lfpg.strip() == "CDG"


def test_chemins_schema_sql_existe() -> None:
    """Vérifie que le fichier schema.sql est bien à l'emplacement attendu."""
    chemin = RACINE_PROJET / "src" / "database" / "schema.sql"
    assert chemin.is_file()


def test_dix_hubs_portent_iata_et_icao() -> None:
    """Vérifie que chaque hub a un IATA à 3 lettres et un ICAO à 4 lettres."""
    assert len(HUBS_AEROPORTUAIRES) == 10
    codes_icao = {hub.code_icao for hub in HUBS_AEROPORTUAIRES}
    assert "LFPG" in codes_icao
    assert "EGLL" in codes_icao
    for hub in HUBS_AEROPORTUAIRES:
        assert len(hub.code_iata) == 3
        assert len(hub.code_icao) == 4
