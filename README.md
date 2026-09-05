# Airlines Delay Prediction

> Projet d'évaluation — Titre RNCP 38919 (Data Engineer)

## Correspondance entre les phases du projet et les rendus

Le projet est organisé en 4 **phases internes**, qui correspondent aux livrables suivants.


| Phase interne                                      | Livrable                                                                                                        | Document                                                                               | Statut                                      |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------- |
| **Phase 1** — Ingestion et Data Profiling          | **Rendu 1** — Découverte et exploration                                                                         | [docs/rendu1_decouverte_exploration.md](docs/rendu1_decouverte_exploration.md)         | Terminée                  |
| **Phase 2** — Schéma BDD en étoile et Pipeline ETL | **Rendu 2** — Organisation et modélisation **des données** (étoile, ETL)              | [docs/rendu2_organisation_modelisation.md](docs/rendu2_organisation_modelisation.md)   | Terminée                  |
| **Phase 3** — Machine Learning et Évaluation       | **Rendu 3** — Machine Learning (cible, LightGBM, métriques, limites)                                            | [docs/rendu3_machine_learning.md](docs/rendu3_machine_learning.md)                     | Terminée, Rendu 3 à relire |
| **Phase 4** — Docker, API, CI/CD                   | **Rapport final** — Consommation, déploiement et automatisation                                                 | [docs/rapport_final.md](docs/rapport_final.md)                                         | Terminée, Rapport final à relire                               |


## Objectif

Pipeline Data Engineer Europe : trois APIs publiques → JSON horodatés → entrepôt en étoile → modèle de **durée observée** ADS-B (`first_seen` / `last_seen`) → API de consommation. Ce n'est **pas** un moteur de retard passager : aucune des trois sources n'expose l'horaire programmé (cadrage dans le [Rendu 1](docs/rendu1_decouverte_exploration.md)).


| Source                           | Données                                 | Usage                                  |
| -------------------------------- | --------------------------------------- | -------------------------------------- |
| **OpenSky Network**              | Vols, positions, statuts                | Durée observée (`first_seen` / `last_seen`) |
| **OpenWeather**                  | Vent, pluie, visibilité                 | Features météo                         |
| **NewsAPI + BERT (HuggingFace)** | Actualités (grèves, météo extrême, ATC) | Score de sentiment / perturbation      |


Le détail de chaque phase est dans le livrable correspondant (tableau ci-dessus), pas dans ce README.

## Architecture du projet

```
src/
├── ingestion/     # Modules d'ingestion API (OpenSky, OpenWeather, NewsAPI)
├── processing/    # Nettoyage, ETL vers l'étoile, collecte hubs
├── database/      # Connexion PostgreSQL et schéma en étoile (Phase 2, terminée)
├── models/        # Premier modèle vol + météo (durée observée, LightGBM)
├── api/           # API FastAPI : GET /health, GET /metrics, POST /predict, doc /docs
└── utils/         # Logging et chemins relatifs à la racine du projet
dags/              # DAG Airflow quotidien (collecte → ETL → entraînement)
monitoring/        # Prometheus (scrape) + Grafana (tableaux provisionnés)
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

Le fichier `.env.example` ne contient aucun secret : uniquement des placeholders (`identifiant_opensky`, `identifiant_client_opensky`, `cle_api_openweather`, `cle_api_newsapi`, etc.).

OpenSky n'accepte plus le login compte (`OPENSKY_USERNAME`) pour `/flights/*` : il faut un **API Client** OAuth2 (`OPENSKY_CLIENT_ID` + `OPENSKY_CLIENT_SECRET` → jeton Bearer). Trino n'est pas requis. Plan Standard : **4000 crédits / jour** sur le seau `/flights` (plafond, pas le restant) ; le restant arrive dans `X-Rate-Limit-Remaining`. Une salve 10 hubs × 2 endpoints = 20 appels, chacun consomme des crédits : ne pas relancer pour « tester ».

Smoke unique (un hub, ~2 h) : `python -m src.ingestion.opensky_client --smoke` — après avoir rempli le `.env`.

`DATABASE_URL` pointe vers l'instance PostgreSQL locale utilisée par le schéma en étoile, l'ETL et l'entraînement (`python -m src.models.entrainer`).

## CI (GitHub Actions)

À chaque push (et pull request) vers `main`, GitHub lance `pytest` sur Ubuntu : `.github/workflows/tests.yml`, dépendances `requirements-ci.txt` (sans torch). Un `.env` est copié depuis `.env.example` (placeholders, **pas** les clés réelles). PostgreSQL n'est pas démarré : les tests `@pytest.mark.postgres` sont ignorés s'il n'est pas joignable. Aucun secret n'est stocké dans le workflow.

En local : `python -m pytest -q`.

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
- Métriques Prometheus : http://127.0.0.1:8000/metrics
- Expérience archive météo / proxy OD (hors API) : `python -m src.models.experience_proxy_retard`

## Lancer l'API dans Docker

Il faut **Docker Desktop** (moteur + Compose v2). Le fichier `.env` reste **hors** de l'image (`.dockerignore`) : Compose l'injecte au démarrage. Le `joblib` est monté depuis `models/` (gitignoré) : entraîner en local avant si le fichier n'existe pas (`python -m src.models.entrainer`).

Le port **8000** du PC doit être libre (arrêter uvicorn local, Ctrl+C).

```bash
docker compose --profile api up --build
```

Puis les mêmes URLs : http://127.0.0.1:8000/health et http://127.0.0.1:8000/docs

Arrêt : `Ctrl+C` puis `docker compose down`.

PostgreSQL **métier** n'est **pas** publié par ce Compose (conflit avec l'instance Windows déjà utilisée par l'ETL). L'image API n'embarque pas torch (`requirements-api.txt`).

## Monitoring Prometheus + Grafana (Phase 4)

Profil Compose **`monitoring`** : scrape de l'API déjà en service, pas de l'orchestration Airflow. Ne pas combiner `--profile monitoring` et `--profile airflow` sur le PC (RAM).

```bash
docker compose --profile monitoring up --build
```

- Prometheus (cibles) : http://127.0.0.1:9090/targets — job `airlines-api` vers `api:8000` (réseau Compose, pas `localhost` du PC)
- Grafana : http://127.0.0.1:3000 — compte **`admin` / `admin`** (UI, pas l'entrepôt). Tableau **API durée observée** (provisionné).
- Arrêt : `docker compose --profile monitoring down`

Rétention Prometheus : 24 h (`--storage.tsdb.retention.time=24h`). Les tableaux Grafana sont des fichiers versionnés (`monitoring/grafana/`), pas un volume de données.

## Orchestration Airflow (Phase 4)

Le DAG `dags/pipeline_quotidien.py` enchaîne, **une fois par jour**, les mêmes commandes qu'en local :

1. `python -m src.processing.collecter_hubs --pause 9` (OpenSky + OpenWeather ; **pas** NewsAPI)
2. `python -m src.processing.etl`
3. `python -m src.models.entrainer`

Image officielle `apache/airflow:2.10.4-python3.11` : Postgres métabase (interne) + webserver + scheduler, SequentialExecutor. Seul `dags/` est monté. L'entrepôt vols/météo reste `DATABASE_URL`.

Les DAG naissent **en pause**. L'API a les profils `api` et `monitoring` : `docker compose --profile airflow up` **ne** démarre **plus** le service `api`.

Sur le **PC**, rien d'autre dans Docker (pas de Grafana) :

```bash
docker compose --profile monitoring down
docker compose --profile airflow up -d
```

Premier `up` : téléchargement des images, plusieurs minutes.

Interface : http://127.0.0.1:8080 — compte **`airflow` / `airflow`** (UI, pas l'entrepôt). DAG `pipeline_quotidien` **en pause**. Ne pas Trigger (quota OpenSky ; l'image officielle ne monte que `dags/`, pas `src/`). Collecte réelle = venv : `python -m src.processing.collecter_hubs --pause 9` puis `python -m src.processing.etl`. Procédure pour qu'un Trigger exécute vraiment ces CLI (machine dédiée, image `Dockerfile.airflow`) : `docs/rapport_final.md`, parties 3.3 et 3.4.

Arrêt : `docker compose --profile airflow down`.

Collecte OpenSky des hubs : `python -m src.processing.collecter_hubs --hubs LTFM,EIDW,EDDM,LEBL --pause 9`. `--pause` espace les appels ; un HTTP 429 sur un hub (backoff `Retry-After` ou 60 s, un réessai) ne coupe plus la liste, les hubs suivants sont interrogés. Un **403** (API Client / OAuth) arrête la salve vols. `--reprendre` saute les ICAO déjà présents en JSON dans `data/raw/`.
