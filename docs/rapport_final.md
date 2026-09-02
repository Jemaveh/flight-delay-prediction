# Rapport final — Consommation, déploiement et automatisation

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)
> **Statut** : Brouillon. Livrable : consommation, déploiement et automatisation. Le Machine Learning a son propre rendu (`docs/rendu3_machine_learning.md`).
> **Phases internes** : le déploiement et l'automatisation relèvent surtout de la Phase 4 ; ce document consolide aussi les phases 1 à 3.

> **Rappel méthodologique** : le rapport final n'est pas une juxtaposition des Rendus 1, 2 et 3. Avant la soutenance, relire et mettre à jour ces trois rendus, puis les résumer ici plutôt que de les recopier tels quels.

---

## 1. Synthèse consolidée des rendus précédents

- **Synthèse Rendu 1** (Découverte & exploration) : trois APIs (OpenSky, OpenWeather, NewsAPI), ingestion automatisée, profiling. Aucune n'expose un horaire programmé : un retard « réel − prévu » n'est pas dans le contrat de données (`docs/rendu1_decouverte_exploration.md`).
- **Synthèse Rendu 2** (Organisation et modélisation **des données**) : schéma en étoile PostgreSQL, ETL incrémental, `retard_minutes` = proxy (durée vs médiane de route), pas un slot DGAC. Un CSV BTS n'entre pas dans `fact_flights` (`docs/rendu2_organisation_modelisation.md`).
- **Synthèse Rendu 3** (Machine Learning) : cible livrée = **durée ADS-B**. LightGBM ne bat pas une médiane. BERT et Open-Meteo testés, sans débloquer un retard. Trois chemins pour l'avoir vraiment : CSV US (Kaggle), 4e source d'horaires Europe, ou reformuler la question — seul le troisième est celui du projet (`docs/rendu3_machine_learning.md` § 8).

---

## 2. Gestion du code et bonnes pratiques

- **Dépôt Git** : [À COMPLÉTER — lien vers le dépôt GitHub]
- **Structure professionnelle** : Architecture modulaire en couches (`src/ingestion`, `src/processing`, `src/database`, `src/models`, `src/api`, `src/utils`, `config`) — chaque module a une responsabilité unique, testable indépendamment (voir `tests/`).
- **Fichier de rejeu du projet** : `README.md` (racine) documente l'installation (`requirements.txt`, `.env.example`) et les commandes pour reproduire le pipeline de bout en bout.
- **Gestion des secrets** : Toutes les clés d'API (OpenSky, OpenWeather, NewsAPI) et la chaîne de connexion à la base de données sont chargées via des **variables d'environnement** (fichier `.env`, jamais commité — voir `.gitignore`), validées au démarrage par `config/settings.py` (Pydantic `BaseSettings`). Aucun secret n'est écrit en dur dans le code source.

---

## 3. Déploiement

- **Mode de déploiement retenu** : Conteneurisation **Docker** via `docker compose` (v2). Service **API** (`Dockerfile`, `python:3.11.9-slim-bookworm`, pas `latest`) qui sert `POST /predict` (durée observée, pas un retard d'horaire). Le `joblib` est un **volume** `./models` (fichier gitignoré). Les secrets viennent de `env_file: .env`, pas du `Dockerfile`. PostgreSQL **métier** reste l'instance locale de la Phase 2 : aucun mapping `5432:5432` dans Compose. L'orchestration quotidienne est un profil **`airflow`** (image `apache/airflow:2.10.4-python3.11`) : métabase Postgres interne à Airflow, distincte de l'entrepôt. L'exécuteur retenu est **SequentialExecutor** (une tâche à la fois) : le DAG est linéaire (`collecte → ETL → entraînement`), le parallélisme d'un LocalExecutor n'apporte rien, et un stack Celery (Redis, workers) serait disproportionné par rapport à la RAM disponible. La commande `airflow standalone` (SQLite) n'est pas utilisée : verrouillage fichier sous Windows ; le Compose officiel sépare webserver, scheduler et métabase Postgres.
- **Bonnes pratiques DevOps appliquées** :
  - Tag d'image Python figé (`3.11.9-slim-bookworm`).
  - `.dockerignore` (`.env`, `data/`, `venv/`, `credentials.json`).
  - `healthcheck` HTTP sur `/health`.
  - Dépendances API allégées : `requirements-api.txt` (sans torch / Jupyter).

### 3.1 Endpoints de l'API développée (annexe technique anticipée)


| Endpoint      | Méthode | Description                                                                               |
| ------------- | ------- | ----------------------------------------------------------------------------------------- |
| `/health`     | GET     | Vérification de l'état de disponibilité du service (healthcheck)                          |
| `/metrics`    | GET     | Exposition Prometheus (latence HTTP, jauge joblib, compteur `POST /predict`)              |
| `/predict`    | POST    | Reçoit les features d'un vol (JSON), retourne la durée observée prédite (`duree_minutes`) |
| `/docs`       | GET     | Documentation OpenAPI native FastAPI                                                      |


*(Schémas de requête/réponse : génération automatique via Swagger/OpenAPI, nativement fournie par FastAPI, visible sur `/docs`.)*

---

## 4. Automatisation & Monitoring

- **Automatisation des traitements** : Apache Airflow **SequentialExecutor** (`docker compose --profile airflow`). DAG `pipeline_quotidien` (`@daily`, `catchup=False`, créé en pause) : `collecter_hubs` → `etl` → `entrainer`. NewsAPI n'est pas dans le DAG (quota et grain journalier, pas une salve horaire). Les clés restent le `.env` du projet (pas des Variables Airflow). Un Postgres interne (`airflow-db`) stocke uniquement les métadonnées Airflow ; l'entrepôt étoile est `DATABASE_URL` / `DATABASE_URL_CONTENEUR` (`host.docker.internal` depuis un conteneur). SequentialExecutor plutôt que LocalExecutor : une seule chaîne de tâches, pas de branches parallèles à accélérer. Un exécuteur Celery (file Redis, workers) viserait un parallélisme distribué dont ce DAG n'a pas besoin, au prix d'une empreinte mémoire trop élevée. La commande `airflow standalone` n'est pas retenue : elle s'appuie sur SQLite, source de verrouillage fichier sous Windows ; le Compose officiel sépare webserver, scheduler et métabase Postgres.
- **CI/CD** : un contrôle automatique à chaque push (et pull request) vers `main`, sur un runner GitHub, sans dépendre d'un `pytest` lancé à la main sur le poste de développement. C'est la preuve de non-régression de la Phase 4 : le dépôt reste testable par un tiers (jury, clone GitHub) sans clés API et sans entrepôt local.
  - **Périmètre livré** : GitHub Actions (`.github/workflows/tests.yml`) installe `requirements-ci.txt` et exécute `pytest`. Un fichier `.env` est copié depuis `.env.example` (placeholders) pour que Pydantic `Settings` démarre ; **aucun secret** n'est stocké dans le workflow ni dans les secrets GitHub à ce stade.
  - **pytest seulement** : la suite `tests/` couvre déjà l'ingestion (réseau mocké), le schéma, l'ETL, le modèle (DataFrames mockés), l'API FastAPI (`TestClient`), et la relecture des fichiers Dockerfile / Compose / DAG. C'est le filet qui protège les choix métier. Un lint (Ruff, Flake8, Black) n'est pas configuré dans le dépôt : l'annoncer dans ce rapport serait inexact. Un `docker build` dans Actions n'est pas non plus branché : les tests lisent déjà le Dockerfile (tag Python figé, pas `latest`) et le Compose (`env_file`, volume `models/`, pas de publication `5432`) ; un build d'image ne prouverait pas `POST /predict` (le `joblib` est gitignoré) et alourdirait le runner sans gain de preuve.
  - **Dépendances CI** : `requirements-ci.txt` reprend les bibliothèques nécessaires aux tests (FastAPI, LightGBM, scikit-learn, httpx, pytest) **sans** torch / Jupyter / ydata-profiling. DistilBERT n'est pas chargé à la collecte des tests ; HuggingFace est mocké. Les tests marqués `@pytest.mark.postgres` sont ignorés si PostgreSQL n'est pas joignable — le runner Ubuntu n'héberge pas l'entrepôt Phase 2, c'est volontaire.
- **Monitoring** : deux niveaux. Les **logs** applicatifs (`src/utils/logger.py`) tracent ingestion, durées d'exécution et erreurs d'API (dont le rate-limiting). Le **monitoring de l'API** est un profil Compose `monitoring` : Prometheus (`prom/prometheus:v2.54.1`) scrape `GET /metrics` toutes les 15 s sur le hostname Compose `api:8000` ; Grafana (`grafana/grafana:11.3.1`) affiche un tableau provisionné (joblib chargé, débit HTTP, latence p95, cumul `POST /predict`). Ce profil n'est pas combiné avec `airflow` sur le poste de développement (contrainte mémoire). La rétention Prometheus est limitée à 24 h. Ce n'est pas un monitoring d'Airflow ni de PostgreSQL métier.
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
  - *Consommées* : OpenSky Network (`/flights/departure`, `/flights/arrival`), OpenWeather (`/data/2.5/weather`), NewsAPI (`/v2/everything`).
- **Structure des fichiers de configuration** : `.env.example` (racine) documente toutes les variables attendues ; `config/settings.py` centralise leur chargement et validation typée.

