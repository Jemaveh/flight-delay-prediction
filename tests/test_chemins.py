"""
Tests unitaires des utilitaires de chemins (src/utils/chemins.py).

Ligne de raisonnement
----------------------
La fonction `chemin_relatif_projet` est utilisée par les notebooks et les
modules d'ingestion pour afficher un chemin portable. Deux comportements
doivent rester stables : un fichier sous la racine du projet est exprimé
relativement à cette racine, et un fichier situé ailleurs ne lève pas
d'exception.
"""

from pathlib import Path

from src.utils.chemins import RACINE_PROJET, chemin_relatif_projet


def test_chemin_sous_la_racine_est_exprime_relativement() -> None:
    """Vérifie qu'un fichier du projet est renvoyé relativement à la racine."""
    chemin = RACINE_PROJET / "data" / "raw" / "exemple.json"

    assert chemin_relatif_projet(chemin) == "data/raw/exemple.json"


def test_chemin_hors_racine_est_retourne_tel_quel(tmp_path: Path) -> None:
    """
    Vérifie qu'un chemin hors du projet est renvoyé sans transformation
    et sans lever d'exception.
    """
    chemin = tmp_path / "ailleurs.json"

    assert chemin_relatif_projet(chemin) == str(chemin)
