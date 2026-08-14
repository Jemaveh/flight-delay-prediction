"""
Module de logging centralisé du projet "Airlines Delay Prediction".

Ligne de raisonnement
----------------------
Pourquoi ne pas se contenter de `print()` pour suivre l'exécution du pipeline ?
    - `print()` ne permet pas de distinguer un simple message d'information
      d'une erreur critique (pas de notion de "niveau" de gravité).
    - `print()` n'écrit que dans la console : impossible de consulter
      l'historique des exécutions passées une fois le terminal fermé.
    - En production, on a besoin de savoir QUAND (timestamp) et OÙ (quel
      module) un événement s'est produit, pas seulement CE QUI s'est produit.

On utilise ici le module `logging` de la bibliothèque standard Python (aucune
dépendance externe à installer) plutôt qu'une librairie tierce comme
`loguru` : ses fonctionnalités suffisent largement aux besoins du projet, et
cela évite d'ajouter une dépendance supplémentaire pour un gain marginal, tout
en restant l'outil que l'on croise le plus souvent dans du code Python
professionnel.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config.settings import settings

# Dossier de destination des fichiers de logs. On le crée automatiquement s'il
# n'existe pas encore, pour que le projet fonctionne "out of the box" après un
# `git clone`, sans étape d'installation manuelle supplémentaire.
DOSSIER_LOGS = Path("logs")
DOSSIER_LOGS.mkdir(parents=True, exist_ok=True)

# Format commun à tous les loggers du projet : date/heure, nom du module
# émetteur, niveau de gravité, puis le message lui-même.
FORMAT_LOG = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_logger(nom_module: str) -> logging.Logger:
    """
    Crée (ou récupère) un logger configuré pour un module donné.

    Parameters
    ----------
    nom_module : str
        Nom du module appelant, généralement `__name__`, afin que chaque ligne
        de log indique précisément sa provenance (ex :
        "src.ingestion.opensky_client").

    Returns
    -------
    logging.Logger
        Une instance de logger prête à l'emploi, écrivant simultanément dans
        la console et dans le fichier `logs/app.log`.

    Pourquoi vérifier `logger.handlers` avant d'en ajouter de nouveaux ?
    ----------------------------------------------------------------------
    Le module `logging` de Python renvoie la MÊME instance de logger à chaque
    appel de `logging.getLogger(nom_module)` avec un nom identique (c'est un
    registre interne partagé par toute l'application). Si l'on ajoutait un
    handler à chaque appel de `get_logger()` sans vérifier l'existant, un
    module sollicité plusieurs fois (ex : dans plusieurs tests, ou si le
    pipeline importe deux fois le même module) finirait par afficher CHAQUE
    message de log en double, triple, etc. On protège donc cette fonction
    pour qu'elle soit "idempotente" : l'appeler plusieurs fois avec le même
    nom produit toujours le même résultat, sans effet de bord cumulatif.
    """
    logger = logging.getLogger(nom_module)

    if logger.handlers:
        # Le logger a déjà été configuré lors d'un appel précédent : on le
        # retourne tel quel pour éviter la duplication des handlers.
        return logger

    logger.setLevel(settings.log_level.upper())

    formatteur = logging.Formatter(FORMAT_LOG)

    # --- Handler console : affichage immédiat, utile pendant le développement ---
    handler_console = logging.StreamHandler()
    handler_console.setFormatter(formatteur)
    logger.addHandler(handler_console)

    # --- Handler fichier : conservation d'un historique consultable après coup ---
    chemin_fichier_log = DOSSIER_LOGS / "app.log"
    handler_fichier = logging.FileHandler(chemin_fichier_log, encoding="utf-8")
    handler_fichier.setFormatter(formatteur)
    logger.addHandler(handler_fichier)

    # On empêche la propagation vers le logger racine de Python pour éviter,
    # là encore, un double affichage si le logger racine venait à être
    # configuré ailleurs dans le projet (ex : par une librairie tierce).
    logger.propagate = False

    return logger
