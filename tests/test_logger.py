"""
Tests unitaires du module de logging centralisé (src/utils/logger.py).

Ligne de raisonnement
----------------------
On teste ici deux comportements essentiels et faciles à casser par erreur lors
d'une future modification du code :
    1. La fonction `get_logger` renvoie bien un objet de type standard
       `logging.Logger` (contrat de l'interface).
    2. Appeler `get_logger` plusieurs fois avec le MÊME nom ne duplique pas les
       handlers (sinon, chaque message de log finirait par s'afficher en
       double, triple, etc. — un bug classique et sournois du module
       `logging`, difficile à repérer sans test dédié).
"""

import logging

from src.utils.logger import get_logger


def test_get_logger_retourne_un_logger() -> None:
    """Vérifie que get_logger renvoie bien une instance de logging.Logger."""
    logger = get_logger("test_module_type")

    assert isinstance(logger, logging.Logger)


def test_get_logger_ne_duplique_pas_les_handlers() -> None:
    """
    Vérifie qu'appeler get_logger deux fois pour le même nom de module :
      - renvoie la même instance de logger (registre partagé de `logging`) ;
      - n'ajoute pas de deuxième jeu de handlers (console + fichier).
    """
    nom_module = "test_module_sans_doublon"

    logger_premier_appel = get_logger(nom_module)
    nombre_handlers_apres_premier_appel = len(logger_premier_appel.handlers)

    logger_second_appel = get_logger(nom_module)
    nombre_handlers_apres_second_appel = len(logger_second_appel.handlers)

    assert logger_premier_appel is logger_second_appel
    assert nombre_handlers_apres_premier_appel == nombre_handlers_apres_second_appel
