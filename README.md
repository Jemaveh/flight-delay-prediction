# Airlines Delay Prediction

> Projet d'évaluation — Titre RNCP 38919 (Data Engineer). Statut : Phase 1 terminée — Phase 2 terminée côté code (Rendu 2 encore brouillon) — Phase 3 / **Rendu 3** (Machine Learning) en cours (vol + météo) — Phase 4 : API FastAPI + Compose (service `api`) + Airflow LocalExecutor (profil `airflow`).

## Correspondance entre les phases du projet et les rendus

Le projet est organisé en 4 **phases internes**, qui correspondent aux livrables suivants.


| Phase interne                                      | Livrable                                                                                                        | Document                                                                               | Statut                                      |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------- |
| **Phase 1** — Ingestion et Data Profiling          | **Rendu 1** — Découverte et exploration                                                                         | [docs/rendu1_decouverte_exploration.md](docs/rendu1_decouverte_exploration.md)         | Terminée (Rendu 1 Final)                    |
| **Phase 2** — Schéma BDD en étoile et Pipeline ETL | **Rendu 2** — Organisation et modélisation **des données** (étoile, ETL ; pas de Machine Learning)              | [docs/rendu2_organisation_modelisation.md](docs/rendu2_organisation_modelisation.md)   | Code terminé ; Rendu 2 encore brouillon     |
| **Phase 3** — Machine Learning et Évaluation       | **Rendu 3** — Machine Learning (cible, LightGBM, métriques, limites)                                            | [docs/rendu3_machine_learning.md](docs/rendu3_machine_learning.md)                     | En cours (durée ADS-B ; Open-Meteo / proxy OD testé ; brouillon) |
| **Phase 4** — Docker, API, CI/CD                   | **Rapport final** — Consommation, déploiement et automatisation                                                 | [docs/rapport_final.md](docs/rapport_final.md)                                         | En cours                               |


## Objectif

Prédire les retards de vols en combinant trois sources de données hétérogènes :


| Source                           | Données                                 | Usage                                  |
| -------------------------------- | --------------------------------------- | -------------------------------------- |
| **OpenSky Network**              | Vols, positions, statuts                | Durée observée (`first_seen` / `last_seen`) |
| **OpenWeather**                  | Vent, pluie, visibilité                 | Features météo                         |
| **NewsAPI + BERT (HuggingFace)** | Actualités (grèves, météo extrême, ATC) | Score de sentiment / perturbation      |


La Phase 1 a mis en place l'ingestion et l'exploration des trois sources (modules d'ingestion, notebooks, tests unitaires, Rendu 1). La Phase 2 est **terminée côté code** : schéma PostgreSQL en étoile, pipeline ETL et ERD. Le Rendu 2 reste un **brouillon** (modélisation de données, pas de Machine Learning) ; relecture prévue plus tard, sans le marquer Final pour l'instant.

Le **Rendu 3** est le rapport de **Machine Learning** (Phase 3) : premier modèle vol + météo + actualités jointes par date (régression de la durée observée, LightGBM), y compris un score BERT agrégé par jour (`docs/experience_actualites_bert.md`). Le **rapport final** (Phase 4) couvre la consommation, le déploiement et l'automatisation — ce n'est plus « le Rendu 3 ». L'API FastAPI (consommation du `joblib`) est en place ; `docker compose up` lance le service `api`. PostgreSQL reste l'instance locale Phase 2. Airflow (profil Compose `airflow`, SequentialExecutor) orchestre ensuite collecte → ETL → entraînement. Prometheus n'est pas encore branché.

## Architecture du projet

```
src/
├── ingestion/     # Modules d'ingestion API (OpenSky, OpenWeather, NewsAPI)
├── processing/    # Nettoyage, ETL vers l'étoile, collecte hubs
├── database/      # Connexion PostgreSQL et schéma en étoile (Phase 2, terminée)
├── models/        # Premier modèle vol + météo (durée observée, LightGBM)
├── api/           # API FastAPI : GET /health, POST /predict, doc /docs
└── utils/         # Logging et chemins relatifs à la racine du projet
dags/              # DAG Airflow quotidien (collecte → ETL → entraînement)
notebooks/         # Exploration des 3 sources, modélisation vol/météo, sentiment BERT
tests/             # Tests unitaires (ingestion, schéma, ETL, modèle, API, Compose, DAG)
```

Le détail de chaque choix d'architecture est documenté dans les rapports du dossier `docs/`.

## Installation

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # puis remplacer les placeholders par les clés réelles
```

Le fichier `.env.example` ne contient aucun secret : uniquement des placeholders (`identifiant_opensky`, `identifiant_client_opensky`, `cle_api_openweather`, `cle_api_newsapi`, etc.). Le fichier `.env` n'est pas versionné.

OpenSky n'accepte plus le login compte (`OPENSKY_USERNAME`) pour `/flights/*` : il faut un **API Client** OAuth2 (`OPENSKY_CLIENT_ID` + `OPENSKY_CLIENT_SECRET` → jeton Bearer). Trino n'est pas requis. Plan Standard : **4000 crédits / jour** sur le seau `/flights` (plafond, pas le restant) ; le restant arrive dans `X-Rate-Limit-Remaining`. Une salve 10 hubs × 2 endpoints = 20 appels, chacun consomme des crédits : ne pas relancer pour « tester ». Un HTTP 403 d'avant mars/septembre 2026, c'était souvent Basic Auth ou un client encore inactif.

Smoke unique (un hub, ~2 h) : `python -m src.ingestion.opensky_client --smoke` — après avoir rempli le `.env`, sans coller le secret dans un chat.

`DATABASE_URL` pointe vers l'instance PostgreSQL locale utilisée par le schéma en étoile, l'ETL et l'entraînement (`python -m src.models.entrainer`).

## Lancer l'API FastAPI (Phase 4)

L'API sert le fichier `models/modele_vol_meteo.joblib` (gitignoré). Sans ce fichier, `GET /health` répond quand même ; `POST /predict` renvoie **503**. Entraîner d'abord : `python -m src.models.entrainer`.

Depuis la racine du projet, venv Windows :

```bash
venv\Scripts\activate
python -m uvicorn src.api.app:app --reload --host 127.0.0.1 --port 8000
```

- Santé : http://127.0.0.1:8000/health
- Documentation OpenAPI (native FastAPI) : http://127.0.0.1:8000/docs
- Prédiction : `POST /predict` (corps JSON = features de `src/models/jeu.py`, cible = durée observée en minutes, pas un retard d'horaire)
- Expérience archive météo / proxy OD (hors API) : `python -m src.models.experience_proxy_retard`

`GET /metrics` Prometheus n'est pas exposé pour l'instant (cours Monitoring).

## Lancer l'API dans Docker

Il faut **Docker Desktop** (moteur + Compose v2). Le fichier `.env` reste **hors** de l'image (`.dockerignore`) : Compose l'injecte au démarrage. Le `joblib` est monté depuis `models/` (gitignoré) : entraîner en local avant si le fichier n'existe pas (`python -m src.models.entrainer`).

Le port **8000** du PC doit être libre (arrêter uvicorn local, Ctrl+C).

```bash
docker compose up --build
```

Puis les mêmes URLs : http://127.0.0.1:8000/health et http://127.0.0.1:8000/docs

Arrêt : `Ctrl+C` puis `docker compose down`.

PostgreSQL **métier** n'est **pas** publié par ce Compose (conflit avec l'instance Windows déjà utilisée par l'ETL). L'image API n'embarque pas torch (`requirements-api.txt`).

## Orchestration Airflow (Phase 4)

Le DAG `dags/pipeline_quotidien.py` enchaîne, **une fois par jour**, les mêmes commandes qu'en local :

1. `python -m src.processing.collecter_hubs --pause 9` (OpenSky + OpenWeather ; **pas** NewsAPI)
2. `python -m src.processing.etl`
3. `python -m src.models.entrainer`

Ce n'est **pas** le Compose Celery de l'exam météo (pas de Redis, pas de Flower, pas de cron à la minute). Image officielle `apache/airflow:2.10.4-python3.11` : Postgres métabase (interne) + webserver + scheduler, SequentialExecutor. Seul `dags/` est monté. L'entrepôt vols/météo reste `DATABASE_URL`.

Les DAG naissent **en pause**.

```bash
docker compose --profile airflow down
docker compose --profile airflow up -d
```

Interface : http://127.0.0.1:8080 — compte **`airflow` / `airflow`** (UI, pas l'entrepôt). DAG `pipeline_quotidien` en pause. Arrêt : `docker compose --profile airflow down`.



Sur la VM école : les mêmes commandes, une seule horloge (ne pas faire tourner le DAG à la fois sur le PC et sur la VM).

Collecte OpenSky des hubs : `python -m src.processing.collecter_hubs --hubs LTFM,EIDW,EDDM,LEBL --pause 9`. `--pause` espace les appels ; un HTTP 429 sur un hub (backoff `Retry-After` ou 60 s, un réessai) ne coupe plus la liste, les hubs suivants sont interrogés. Un **403** (API Client / OAuth) arrête la salve vols. `--reprendre` saute les ICAO déjà présents en JSON dans `data/raw/`.

## Feuille de route

- **Phase 1** — Ingestion et Data Profiling : **terminée**
- **Phase 2** — Schéma BDD en étoile et Pipeline ETL : **terminée côté code** (PostgreSQL, étoile, ETL, ERD) ; Rendu 2 encore brouillon
- **Phase 3** — Machine Learning et Évaluation (**Rendu 3**) : **en cours** (premier modèle vol + météo + actualités ; BERT agrégé par jour, notebook `05_sentiment_bert.ipynb` ; expérience hub/flags/J−1 : `python -m src.models.experience_actu --avec-bert` ; expérience Open-Meteo + proxy OD : `python -m src.models.experience_proxy_retard`)
- **Phase 4** — API FastAPI + `docker compose` (service `api`) ; Airflow `standalone` (`--profile airflow`) ; Prometheus ensuite si le temps le permet (**rapport final**)

Le README sera complété en détail à l'issue du projet. Voir le dossier `docs/` pour les rapports des phases et des livrables officiels.
