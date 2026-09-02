"""
DAG quotidien : collecte OpenSky/OpenWeather, ETL PostgreSQL, entraînement.

NewsAPI n'est pas appelée. Le DAG est créé en pause (déclenchement manuel
ou activation explicite) pour ne pas consommer le quota OpenSky au premier
démarrage d'Airflow.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator

RACINE_CONTENEUR = "/opt/airflow"

with DAG(
    dag_id="pipeline_quotidien",
    description=(
        "Collecte hubs, chargement de l'étoile PostgreSQL, "
        "réentraînement LightGBM (durée observée)."
    ),
    schedule="@daily",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    default_args={
        "retries": 0,
        "execution_timeout": timedelta(hours=2),
    },
    tags=["airlines", "entrepot"],
) as dag:
    collecter_hubs = BashOperator(
        task_id="collecter_hubs",
        cwd=RACINE_CONTENEUR,
        bash_command="python -m src.processing.collecter_hubs --pause 9",
    )
    etl = BashOperator(
        task_id="etl",
        cwd=RACINE_CONTENEUR,
        bash_command="python -m src.processing.etl",
    )
    entrainer = BashOperator(
        task_id="entrainer",
        cwd=RACINE_CONTENEUR,
        bash_command="python -m src.models.entrainer",
    )

    collecter_hubs >> etl >> entrainer
