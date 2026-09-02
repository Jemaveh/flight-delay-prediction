"""
Contrôles des fichiers Airflow versionnés (pas le daemon, pas d'appel API).
"""

from src.utils.chemins import RACINE_PROJET


def _texte_dag() -> str:
    return (RACINE_PROJET / "dags" / "pipeline_quotidien.py").read_text(
        encoding="utf-8"
    )


def _texte_compose() -> str:
    return (RACINE_PROJET / "docker-compose.yml").read_text(encoding="utf-8")


def test_dag_quotidien_enchaine_collecte_etl_train_sans_newsapi() -> None:
    texte = _texte_dag()
    assert 'dag_id="pipeline_quotidien"' in texte
    assert 'schedule="@daily"' in texte
    assert "catchup=False" in texte
    assert "is_paused_upon_creation=True" in texte
    assert "collecter_hubs" in texte
    assert "src.processing.etl" in texte
    assert "src.models.entrainer" in texte
    assert "src.ingestion.newsapi" not in texte
    assert "python -m src.ingestion.newsapi_client" not in texte
    assert "* * * * *" not in texte
    assert "BashOperator" in texte


def test_compose_airflow_est_local_executor_sans_celery() -> None:
    texte = _texte_compose()
    assert "LocalExecutor" in texte
    assert "CeleryExecutor" not in texte
    assert "redis" not in texte.lower()
    assert "flower" not in texte.lower()
    assert 'profiles: ["airflow"]' in texte
    assert "5432:5432" not in texte


def test_dockerfile_airflow_tag_figure() -> None:
    texte = (RACINE_PROJET / "Dockerfile.airflow").read_text(encoding="utf-8")
    lignes_from = [
        ligne.strip()
        for ligne in texte.splitlines()
        if ligne.strip().upper().startswith("FROM ")
    ]
    assert lignes_from == ["FROM apache/airflow:2.10.4-python3.11"]
