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
    assert "5432" not in texte
