"""
Contrôles du Dockerfile / Compose (fichiers versionnés, pas Docker daemon).
"""

from pathlib import Path

from src.utils.chemins import RACINE_PROJET


def test_dockerfile_python_figure_pas_latest() -> None:
    texte = (RACINE_PROJET / "Dockerfile").read_text(encoding="utf-8")
    lignes_from = [
        ligne.strip()
        for ligne in texte.splitlines()
        if ligne.strip().upper().startswith("FROM ")
    ]
    assert lignes_from == ["FROM python:3.11.9-slim-bookworm"]


def test_compose_api_injecte_env_et_monte_le_modele() -> None:
    texte = (RACINE_PROJET / "docker-compose.yml").read_text(encoding="utf-8")
    assert "env_file:" in texte
    assert "./models:/app/models" in texte
    assert "5432:5432" not in texte
    assert 'profiles: ["api", "monitoring"]' in texte


def test_compose_monitoring_est_un_profil_separe() -> None:
    texte = (RACINE_PROJET / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["monitoring"]' in texte
    assert "prom/prometheus:v2.54.1" in texte
    assert "grafana/grafana:11.3.1" in texte
    assert "prometheus:latest" not in texte
    assert "grafana:latest" not in texte
    assert "9090:9090" in texte
    assert "3000:3000" in texte


def test_prometheus_scrape_l_api_sur_le_reseau_compose() -> None:
    texte = (RACINE_PROJET / "monitoring" / "prometheus.yml").read_text(
        encoding="utf-8"
    )
    assert "api:8000" in texte
    assert "localhost:8000" not in texte
    assert "127.0.0.1:8000" not in texte
    assert "/metrics" in texte
