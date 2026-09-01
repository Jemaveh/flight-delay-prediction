# iRapport final — Consommation, déploiement et automatisation

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)
> **Statut** : Brouillon — sections techniques pré-remplies, sections "Discussion" à compléter **Livrable** : Rapport final — consommation, déploiement et automatisation. Le Machine Learning a son propre rendu (`docs/rendu3_machine_learning.md`).
> **Phases internes** : le déploiement et l'automatisation relèvent surtout de la Phase 4 ; ce document consolide aussi les phases 1 à 3.

> **Rappel méthodologique** : le rapport final n'est pas une juxtaposition des Rendus 1, 2 et 3. Avant la soutenance, relire et mettre à jour ces trois rendus, puis les résumer ici plutôt que de les recopier tels quels.

---

## 1. Synthèse consolidée des rendus précédents

- **Synthèse Rendu 1** (Découverte & exploration) : [À COMPLÉTER — résumé en 5-10 lignes, avec liens vers `docs/rendu1_decouverte_exploration.md`]
- **Synthèse Rendu 2** (Organisation et modélisation **des données**) : [À COMPLÉTER — résumé en 5-10 lignes, avec liens vers `docs/rendu2_organisation_modelisation.md`]
- **Synthèse Rendu 3** (Machine Learning) : [À COMPLÉTER — résumé en 5-10 lignes, avec lien vers `docs/rendu3_machine_learning.md`]

---

## 2. Gestion du code et bonnes pratiques

- **Dépôt Git** : [À COMPLÉTER — lien vers le dépôt GitHub]
- **Structure professionnelle** : Architecture modulaire en couches (`src/ingestion`, `src/processing`, `src/database`, `src/models`, `src/api`, `src/utils`, `config`) — chaque module a une responsabilité unique, testable indépendamment (voir `tests/`).
- **Fichier de rejeu du projet** : `README.md` (racine) documente l'installation (`requirements.txt`, `.env.example`) et les commandes pour reproduire le pipeline de bout en bout.
- **Gestion des secrets** : Toutes les clés d'API (OpenSky, OpenWeather, NewsAPI) et la chaîne de connexion à la base de données sont chargées via des **variables d'environnement** (fichier `.env`, jamais commité — voir `.gitignore`), validées au démarrage par `config/settings.py` (Pydantic `BaseSettings`). Aucun secret n'est écrit en dur dans le code source.

---

## 3. Déploiement

- **Mode de déploiement retenu** : Conteneurisation **Docker** via `docker compose` (v2). **Aujourd'hui** : un service **API** (`Dockerfile`, `python:3.11.9-slim-bookworm`, pas `latest`) qui sert `POST /predict` (durée observée, pas un retard d'horaire). Le `joblib` est un **volume** `./models` (fichier gitignoré). Les secrets viennent de `env_file: .env`, pas du `Dockerfile`. PostgreSQL **reste** l'instance Windows de la Phase 2 : un Postgres Compose sur 5432 entrerait en conflit. Un service pipeline / Airflow n'est pas dans ce premier Compose.
- **Bonnes pratiques DevOps appliquées** :
  - Tag d'image Python figé (`3.11.9-slim-bookworm`).
  - `.dockerignore` (`.env`, `data/`, `venv/`, `credentials.json`).
  - `healthcheck` HTTP sur `/health`.
  - Dépendances API allégées : `requirements-api.txt` (sans torch / Jupyter).

### 3.1 Endpoints de l'API développée (annexe technique anticipée)


| Endpoint      | Méthode | Description                                                                               |
| ------------- | ------- | ----------------------------------------------------------------------------------------- |
| `/health`     | GET     | Vérification de l'état de disponibilité du service (healthcheck)                          |
| `/predict`    | POST    | Reçoit les features d'un vol (JSON), retourne la durée observée prédite (`duree_minutes`) |
| `/model/info` | GET     | Non livré dans ce premier geste (métadonnées dans le joblib ; `/docs` suffit)             |


*(Détail des schémas de requête/réponse à documenter une fois l'API implémentée en Phase 4 — génération automatique via Swagger/OpenAPI, nativement fournie par FastAPI.)*

---

## 4. Automatisation & Monitoring

- **Automatisation des traitements** : [À COMPLÉTER — orchestration retenue : cron simple, ou GitHub Actions planifié, selon le temps disponible en Phase 4]
- **CI/CD** : Pipeline GitHub Actions exécutant à chaque push : installation des dépendances, linting, tests unitaires (`pytest`), et build de l'image Docker.
- **Monitoring** : Logs structurés (voir `src/utils/logger.py`) centralisant les erreurs d'ingestion, les temps d'exécution et les alertes de rate-limiting API. [À COMPLÉTER — outil de monitoring retenu si le temps le permet : simple fichier de log, ou solution dédiée]
- **Gestion des erreurs et alertes** : Chaque module d'ingestion utilise un bloc `try/except` ciblé (pas de `except` générique silencieux) qui journalise l'erreur avec son contexte (source, timestamp, message) sans interrompre les autres sources en cas d'échec partiel (résilience du pipeline).

---

## 5. Bilan

- **Principales difficultés rencontrées** (techniques, temporelles, organisationnelles) : [À COMPLÉTER]
- **Verrous techniques majeurs** : [À COMPLÉTER]
- **Contribution principale au projet** : [À COMPLÉTER]
- **Pistes d'amélioration** (fiabilité, performance, maintenabilité) : [À COMPLÉTER]

---

## 6. Suite du projet

- **Scalabilité / intégration en production** : [À COMPLÉTER — ex : migration vers un entrepôt de données cloud managé (BigQuery, Snowflake) ou une instance PostgreSQL partitionnée, orchestration via Airflow plutôt que cron]
- **Axes d'amélioration envisagés** : [À COMPLÉTER — nouvelles sources de données, automatisation complète, visualisation temps réel]
- **Contribution du projet à une meilleure exploitation de la donnée** : [À COMPLÉTER]

---

## 7. Bibliographie

[À COMPLÉTER — articles, documentation officielle des APIs, ressources HuggingFace/LightGBM consultées]

---

## 8. Annexes

- **Schéma d'architecture technique global** : [À COMPLÉTER — diagramme incluant : sources API → ingestion → PostgreSQL (schéma en étoile) → feature engineering → modèle LightGBM → API FastAPI → conteneurs Docker]
- **Endpoints des API développées ou consommées** :
  - *Développées* : voir §3.1 ci-dessus.
  - *Consommées* : OpenSky Network (`/states/all`), OpenWeather (`/data/2.5/weather`), NewsAPI (`/v2/everything`).
- **Structure des fichiers de configuration** : `.env.example` (racine) documente toutes les variables attendues ; `config/settings.py` centralise leur chargement et validation typée.

