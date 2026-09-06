"""
Module de logging centralisé du projet "Airlines Delay Prediction".

"""

from __future__ import annotations

import logging
from pathlib import Path

from config.settings import settings

# Dossier de destination des fichiers de logs. On le crée automatiquement s'il
# n'existe pas encore, pour que le projet fonctionne "out of the box" après un
# `git clone`.
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

    Notes
    -----
    `logging.getLogger` renvoie la même instance pour un nom donné. Les
    handlers ne sont donc ajoutés que si le logger n'en possède pas encore,
    faute de quoi un appel répété afficherait chaque message en double.
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
    # un double affichage si le logger racine venait à être configuré
    # ailleurs dans le projet (ex : par une librairie tierce).
    logger.propagate = False

    return logger
