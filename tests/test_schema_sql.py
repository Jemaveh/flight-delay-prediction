"""
Vérifications statiques de src/database/schema.sql (contraintes et index),
sans instance PostgreSQL.
"""

from src.utils.chemins import RACINE_PROJET

CHEMIN_SCHEMA = RACINE_PROJET / "src" / "database" / "schema.sql"


def _sql() -> str:
    return CHEMIN_SCHEMA.read_text(encoding="utf-8")


def test_schema_declare_les_tables_du_modele_en_etoile() -> None:
    """Vérifie la présence des tables de faits, de dimensions et du journal."""
    sql = _sql()
    for table in (
        "dim_date",
        "dim_airport",
        "dim_weather",
        "dim_news_sentiment",
        "fact_flights",
        "ingestion_log",
    ):
        assert table in sql


def test_schema_fact_flights_aligne_sur_flights_pas_states() -> None:
    """Vérifie l'absence des champs ADS-B de /states/all dans la table de faits."""
    sql = _sql()
    assert "icao24" in sql
    assert "first_seen" in sql
    assert "last_seen" in sql
    assert "weather_origin_id" in sql
    assert "weather_dest_id" in sql
    assert "altitude" not in sql
    assert "vitesse" not in sql


def test_schema_unicite_vols_et_index_fk() -> None:
    """Vérifie l'index unique des vols et les index annoncés sur les FK."""
    sql = _sql()
    assert "uq_fact_flights_identite" in sql
    assert "COALESCE(est_departure_airport" in sql
    assert "idx_fact_flights_date_id" in sql
    assert "idx_fact_flights_airport_origin_id" in sql
    assert "idx_dim_weather_airport_id" in sql
    assert "idx_dim_weather_date_id" in sql
    assert "uq_dim_airport_icao" in sql
