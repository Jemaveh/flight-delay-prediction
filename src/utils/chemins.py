"""
Utilitaires de manipulation des chemins de fichiers du projet
"Airlines Delay Prediction".
"""

from __future__ import annotations

import os
from pathlib import Path

# Racine du projet, déduite de l'emplacement de ce fichier (src/utils/chemins.py)
RACINE_PROJET = Path(__file__).resolve().parents[2]


def chemin_relatif_projet(chemin: str | os.PathLike[str]) -> str:
    """
    Exprime un chemin de fichier relativement à la racine du projet.

    Parameters
    ----------
    chemin : str | os.PathLike[str]
        Chemin à convertir, absolu ou relatif au répertoire de travail courant.

    Returns
    -------
    str
        Le chemin relatif à la racine du projet, avec "/" comme séparateur.
        Si le fichier se situe en dehors de la racine du projet, le chemin
        reçu est retourné tel quel.
    """
    try:
        return Path(chemin).resolve().relative_to(RACINE_PROJET).as_posix()
    except ValueError:
        return str(chemin)
