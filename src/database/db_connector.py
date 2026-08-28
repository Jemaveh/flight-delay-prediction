"""
Connexion PostgreSQL, application du schéma SQL et seed des dimensions
statiques (aéroports hubs, calendrier)
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from config.settings import settings
from src.ingestion.openweather_client import HUBS_AEROPORTUAIRES
from src.utils.chemins import RACINE_PROJET, chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

CHEMIN_SCHEMA = RACINE_PROJET / "src" / "database" / "schema.sql"

# Complément ville / pays des dix hubs, aligné sur HUBS_AEROPORTUAIRES
VILLE_PAYS_PAR_ICAO: dict[str, tuple[str, str]] = {
    "LFPG": ("Paris", "France"),
    "EGLL": ("Londres", "Royaume-Uni"),
    "EDDF": ("Francfort", "Allemagne"),
    "EHAM": ("Amsterdam", "Pays-Bas"),
    "LEMD": ("Madrid", "Espagne"),
    "LIRF": ("Rome", "Italie"),
    "LTFM": ("Istanbul", "Turquie"),
    "EIDW": ("Dublin", "Irlande"),
    "EDDM": ("Munich", "Allemagne"),
    "LEBL": ("Barcelone", "Espagne"),
}

DATE_SEED_DEBUT = date(2026, 7, 1)
DATE_SEED_FIN = date(2026, 12, 31)


def creer_engine() -> Engine:
    """
    Construit un engine SQLAlchemy à partir de settings.database_url,
    avec un client_encoding UTF-8.

    Returns
    -------
    Engine
        Engine pointant vers PostgreSQL.

    Raises
    ------
    ValueError
        Si DATABASE_URL n'utilise pas le dialecte postgresql.
    """
    url = settings.database_url
    if not url.startswith("postgresql"):
        raise ValueError(
            "DATABASE_URL doit utiliser le dialecte postgresql "
            "(exemple : postgresql://utilisateur:motdepasse@localhost:5432/airlines_db)."
        )
    return create_engine(url, connect_args={"client_encoding": "utf8"})


def executer_schema(engine: Engine | None = None) -> None:
    """
    Exécute src/database/schema.sql sur l'engine donné (ou un engine neuf).
    """
    moteur = engine if engine is not None else creer_engine()
    sql = CHEMIN_SCHEMA.read_text(encoding="utf-8")
    logger.info(
        "Application du schéma '%s'.",
        chemin_relatif_projet(CHEMIN_SCHEMA),
    )
    with moteur.begin() as connexion:
        connexion.exec_driver_sql(sql)


def ensemencer_aeroports(engine: Engine | None = None) -> int:
    """
    Insère ou met à jour les dix hubs (codes IATA et ICAO, coordonnées, ville, pays).

    Returns
    -------
    int
        Nombre de hubs traités.
    """
    moteur = engine if engine is not None else creer_engine()
    requete = text(
        """
        INSERT INTO dim_airport (
            code_iata, code_icao, ville, pays, latitude, longitude
        )
        VALUES (
            :code_iata, :code_icao, :ville, :pays, :latitude, :longitude
        )
        ON CONFLICT (code_icao) DO UPDATE SET
            code_iata = EXCLUDED.code_iata,
            ville = EXCLUDED.ville,
            pays = EXCLUDED.pays,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude
        """
    )
    lignes = []
    for hub in HUBS_AEROPORTUAIRES:
        ville, pays = VILLE_PAYS_PAR_ICAO.get(hub.code_icao, (None, None))
        lignes.append(
            {
                "code_iata": hub.code_iata,
                "code_icao": hub.code_icao,
                "ville": ville,
                "pays": pays,
                "latitude": hub.latitude,
                "longitude": hub.longitude,
            }
        )
    with moteur.begin() as connexion:
        connexion.execute(requete, lignes)
    logger.info("Seed dim_airport : %s hub(s) traité(s).", len(lignes))
    return len(lignes)


def _iterer_dates(debut: date, fin: date):
    jour = debut
    while jour <= fin:
        yield jour
        jour += timedelta(days=1)


def ensemencer_dates(
    engine: Engine | None = None,
    debut: date = DATE_SEED_DEBUT,
    fin: date = DATE_SEED_FIN,
) -> int:
    """
    Insère les jours du calendrier entre `debut` et `fin` (inclus), sans écraser
    les lignes déjà présentes.

    Returns
    -------
    int
        Nombre de jours soumis à l'upsert.
    """
    moteur = engine if engine is not None else creer_engine()
    requete = text(
        """
        INSERT INTO dim_date (date_id, date, jour_semaine, mois, est_ferie)
        VALUES (:date_id, :date, :jour_semaine, :mois, :est_ferie)
        ON CONFLICT (date_id) DO NOTHING
        """
    )
    lignes = []
    for jour in _iterer_dates(debut, fin):
        lignes.append(
            {
                "date_id": int(jour.strftime("%Y%m%d")),
                "date": jour,
                "jour_semaine": jour.isoweekday(),
                "mois": jour.month,
                "est_ferie": False,
            }
        )
    with moteur.begin() as connexion:
        connexion.execute(requete, lignes)
    logger.info(
        "Seed dim_date : %s jour(s) soumis entre %s et %s.",
        len(lignes),
        debut.isoformat(),
        fin.isoformat(),
    )
    return len(lignes)


def ouvrir_connexion(engine: Engine | None = None) -> Connection:
    """
    Ouvre une connexion SQLAlchemy (à fermer par l'appelant).
    """
    moteur = engine if engine is not None else creer_engine()
    return moteur.connect()
