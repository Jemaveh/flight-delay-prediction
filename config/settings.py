"""
Module de configuration centralisée du projet "Airlines Delay Prediction".

Ligne de raisonnement
----------------------
Un pipeline de données manipule des informations sensibles (clés d'API, mots de
passe, chaînes de connexion à une base de données). Écrire ces valeurs "en dur"
dans le code source serait une faute professionnelle grave :
    - Elles se retrouveraient versionnées dans Git (donc visibles par quiconque
      a accès au dépôt, y compris sur un dépôt public).
    - Il faudrait modifier le code source à chaque changement de clé (ex :
      renouvellement d'un abonnement API), ce qui est risqué en production.

La solution standard en Data Engineering consiste à charger ces valeurs depuis
des VARIABLES D'ENVIRONNEMENT, elles-mêmes définies dans un fichier local
".env" qui n'est JAMAIS commité (voir la règle correspondante dans .gitignore).

On utilise ici la librairie "pydantic-settings" plutôt qu'un simple
`os.getenv("MA_VARIABLE")` répété dans chaque module, pour trois raisons :
    1. VALIDATION AUTOMATIQUE : si une variable obligatoire manque ou a le
       mauvais type, l'erreur apparaît immédiatement au démarrage de
       l'application, avec un message clair, plutôt que de planter au milieu
       d'un pipeline plusieurs minutes plus tard.
    2. TYPAGE FORT : chaque variable est typée explicitement (str, int...), ce
       qui permet à l'éditeur de code et aux outils d'analyse statique de
       détecter des erreurs avant même d'exécuter le programme.
    3. SOURCE UNIQUE DE VÉRITÉ : un seul objet "settings", importable partout
       dans le projet, évite de dupliquer la logique de lecture des variables
       d'environnement dans chaque module (src/ingestion, src/database...).
"""

from __future__ import annotations

import sys

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Représente l'ensemble des paramètres de configuration du projet.

    Chaque attribut ci-dessous correspond exactement à une variable définie
    dans le fichier ".env" (voir ".env.example" à la racine du projet pour la
    liste complète et leur description).

    Note sur la correspondance des noms (case_sensitive=False) :
        Par convention Python (PEP8), les attributs de classe sont écrits en
        "snake_case" minuscule (ex : opensky_username). Les variables
        d'environnement, elles, suivent la convention shell classique en
        MAJUSCULES (ex : OPENSKY_USERNAME). Avec `case_sensitive=False`
        (comportement activé explicitement ci-dessous), pydantic-settings fait
        automatiquement la correspondance entre "opensky_username" et
        "OPENSKY_USERNAME" : aucun mapping manuel n'est nécessaire.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # on ignore les variables d'environnement non déclarées ici
    )

    # --- OpenSky Network (données de vols) ---
    opensky_username: str
    opensky_password: str

    # --- OpenWeather (données météo) ---
    openweather_api_key: str

    # --- NewsAPI (actualités) ---
    newsapi_key: str

    # --- Base de données ---
    database_url: str

    # --- Niveau de log, avec une valeur par défaut raisonnable ---
    log_level: str = "INFO"


def _charger_configuration() -> Settings:
    """
    Instancie l'objet Settings en gérant proprement le cas où le fichier .env
    est absent ou incomplet.

    Pourquoi une fonction dédiée plutôt qu'un simple `settings = Settings()` ?
    ----------------------------------------------------------------------
    Sans ce garde-fou, une erreur de configuration produirait un traceback
    Pydantic technique et peu lisible pour un⋅e débutant⋅e (du type
    "ValidationError: 4 validation errors for Settings..."). On préfère
    intercepter cette erreur pour afficher un message pédagogique et
    actionnable, qui explique QUOI faire pour la corriger, plutôt que de
    laisser remonter une pile d'appels brute.

    Returns
    -------
    Settings
        L'instance de configuration validée et prête à l'emploi.
    """
    try:
        return Settings()
    except ValidationError as erreur:
        message = (
            "\n[ERREUR DE CONFIGURATION] Impossible de charger les paramètres du projet.\n"
            "Cause probable : le fichier '.env' est absent ou incomplet à la racine du projet.\n\n"
            "Solution :\n"
            "  1. Copie le fichier modèle :   copy .env.example .env   (Windows)\n"
            "  2. Ouvre '.env' et renseigne tes vraies clés d'API.\n\n"
            f"Détail technique de l'erreur Pydantic :\n{erreur}\n"
        )
        print(message, file=sys.stderr)
        sys.exit(1)


# Instance unique, créée une seule fois au chargement du module (motif "singleton").
# Tous les autres modules du projet importent cette même instance plutôt que d'en
# recréer une nouvelle à chaque fois :
#   from config.settings import settings
settings: Settings = _charger_configuration()
