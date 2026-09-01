# Airlines Delay Prediction

> Projet d'évaluation — Titre RNCP 38919 (Data Engineer). Statut : Phase 1 terminée — Phase 2 terminée côté code (Rendu 2 encore brouillon) — Phase 3 / **Rendu 3** (Machine Learning) en cours (vol + météo) — Phase 4 / rapport final en cours.

## Correspondance entre les phases du projet et les rendus

Le projet est organisé en 4 **phases internes**, qui correspondent aux livrables suivants.


| Phase interne                                      | Livrable                                                                                                        | Document                                                                               | Statut                                      |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------- |
| **Phase 1** — Ingestion et Data Profiling          | **Rendu 1** — Découverte et exploration                                                                         | [docs/rendu1_decouverte_exploration.md](docs/rendu1_decouverte_exploration.md)         | Terminée (Rendu 1 Final)                    |
| **Phase 2** — Schéma BDD en étoile et Pipeline ETL | **Rendu 2** — Organisation et modélisation **des données** (étoile, ETL ; pas de Machine Learning)              | [docs/rendu2_organisation_modelisation.md](docs/rendu2_organisation_modelisation.md)   | Code terminé ; Rendu 2 encore brouillon     |
| **Phase 3** — Machine Learning et Évaluation       | **Rendu 3** — Machine Learning (cible, LightGBM, métriques, limites)                                            | [docs/rendu3_machine_learning.md](docs/rendu3_machine_learning.md)                     | En cours (premier modèle vol + météo ; brouillon) |
| **Phase 4** — Docker, API, CI/CD                   | **Rapport final** — Consommation, déploiement et automatisation                                                 | [docs/rapport_final.md](docs/rapport_final.md)                                         | En cours                               |


## Objectif

Prédire les retards de vols en combinant trois sources de données hétérogènes :


| Source                           | Données                                 | Usage                                  |
| -------------------------------- | --------------------------------------- | -------------------------------------- |
| **OpenSky Network**              | Vols, positions, statuts                | Variable cible (retard) + features vol |
| **OpenWeather**                  | Vent, pluie, visibilité                 | Features météo                         |
| **NewsAPI + BERT (HuggingFace)** | Actualités (grèves, météo extrême, ATC) | Score de sentiment / perturbation      |


La Phase 1 a mis en place l'ingestion et l'exploration des trois sources (modules d'ingestion, notebooks, tests unitaires, Rendu 1). La Phase 2 est **terminée côté code** : schéma PostgreSQL en étoile, pipeline ETL et ERD. Le Rendu 2 reste un **brouillon** (modélisation de données, pas de Machine Learning) ; relecture prévue plus tard, sans le marquer Final pour l'instant.

Le **Rendu 3** est le rapport de **Machine Learning** (Phase 3) : premier modèle vol + météo (régression de la durée observée, LightGBM). Le score BERT n'est pas encore dans le modèle. Le **rapport final** (Phase 4) couvre la consommation, le déploiement et l'automatisation — ce n'est plus « le Rendu 3 ». Docker, API FastAPI et l'orchestration sont en cours.

## Architecture du projet

```
src/
├── ingestion/     # Modules d'ingestion API (OpenSky, OpenWeather, NewsAPI)
├── processing/    # Nettoyage, ETL vers l'étoile, collecte hubs
├── database/      # Connexion PostgreSQL et schéma en étoile (Phase 2, terminée)
├── models/        # Premier modèle vol + météo (durée observée, LightGBM)
├── api/           # API FastAPI de prédiction (Phase 4, à venir)
└── utils/         # Logging et chemins relatifs à la racine du projet
notebooks/         # Exploration des 3 sources + notebook de modélisation vol/météo
tests/             # Tests unitaires (ingestion, schéma, ETL, modèle, chemins, logger)
```

Le détail de chaque choix d'architecture est documenté dans les rapports du dossier `docs/`.

## Installation

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # puis remplacer les placeholders par les clés réelles
```

Le fichier `.env.example` ne contient aucun secret : uniquement des placeholders (`identifiant_opensky`, `cle_api_openweather`, `cle_api_newsapi`, etc.). Le fichier `.env` n'est pas versionné.

`DATABASE_URL` pointe vers l'instance PostgreSQL locale utilisée par le schéma en étoile, l'ETL et l'entraînement (`python -m src.models.entrainer`).

Collecte OpenSky des hubs : `python -m src.processing.collecter_hubs --hubs LTFM,EIDW,EDDM,LEBL --pause 9`. `--pause` espace les appels ; un HTTP 429 sur un hub (backoff `Retry-After` ou 60 s, un réessai) ne coupe plus la liste, les hubs suivants sont interrogés. `--reprendre` saute les ICAO déjà présents en JSON dans `data/raw/`.

## Feuille de route

- **Phase 1** — Ingestion et Data Profiling : **terminée**
- **Phase 2** — Schéma BDD en étoile et Pipeline ETL : **terminée côté code** (PostgreSQL, étoile, ETL, ERD) ; Rendu 2 encore brouillon
- **Phase 3** — Machine Learning et Évaluation (**Rendu 3**) : **en cours** (premier modèle vol + météo ; BERT ensuite si le temps le permet)
- **Phase 4** — Docker, API FastAPI, CI/CD : en cours (**rapport final** = consommation, déploiement, automatisation)

Le README sera complété en détail à l'issue du projet. Voir le dossier `docs/` pour les rapports des phases et des livrables officiels.
