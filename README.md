# Airlines Delay Prediction

> Projet d'évaluation — Titre RNCP 38919 (Data Engineer) Statut : Phase 1 terminée — Phases 2 à 4 en cours

## Correspondance entre les phases du projet et les rendus officiels

Le projet est organisé en 4 phases, chacune correspondant à un rendu de la grille d'évaluation officielle DataScientest.


| Phase du projet                                    | Rendu officiel correspondant                                | Rapport détaillé                                                                       | Statut   |
| -------------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------- | -------- |
| **Phase 1** — Ingestion et Data Profiling          | Rendu 1 — Découverte et exploration                         | `[docs/rendu1_decouverte_exploration.md](docs/rendu1_decouverte_exploration.md)`       | Terminée |
| **Phase 2** — Schéma BDD en étoile et Pipeline ETL | Rendu 2 — Organisation et modélisation                      | `[docs/rendu2_organisation_modelisation.md](docs/rendu2_organisation_modelisation.md)` | En cours |
| **Phase 3** — Machine Learning et Évaluation       | Rendu 3 — Machine Learning et Évaluation                    | `[docs/rendu3_machine_learning.md](docs/rendu3_machine_learning.md)`                   | En cours |
| **Phase 4** — Docker, API, CI/CD                   | Rapport final — Consommation, déploiement et automatisation | `[docs/rapport_final.md](docs/rapport_final.md)`                                       | En cours |




## Objectif

Prédire les retards de vols en combinant trois sources de données hétérogènes :


| Source                           | Données                                 | Usage                                  |
| -------------------------------- | --------------------------------------- | -------------------------------------- |
| **OpenSky Network**              | Vols, positions, statuts                | Variable cible (retard) + features vol |
| **OpenWeather**                  | Vent, pluie, visibilité                 | Features météo                         |
| **NewsAPI + BERT (HuggingFace)** | Actualités (grèves, météo extrême, ATC) | Score de sentiment / perturbation      |


La Phase 1 a mis en place l'ingestion et l'exploration des trois sources (modules, notebooks, tests unitaires, Rendu 1). Le stockage relationnel (PostgreSQL, schéma en étoile) et le pipeline ETL relèvent de la Phase 2. Le modèle de prédiction (features météo et score de sentiment) relève de la Phase 3.

## Architecture du projet

```
src/
├── ingestion/     # Modules d'extraction API (OpenSky, OpenWeather, NewsAPI)
├── processing/    # Nettoyage, sentiment analysis (BERT), data profiling
├── database/      # Connexion PostgreSQL et schéma en étoile (Phase 2)
├── models/        # Entraînement et sauvegarde du modèle de Machine Learning
├── api/           # API FastAPI de prédiction (/predict, /health)
└── utils/         # Logging et chemins relatifs à la racine du projet
notebooks/         # Exploration et data profiling des 3 sources
tests/             # Tests unitaires (ingestion, chemins, logger)
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

`DATABASE_URL` pointe vers PostgreSQL ; cette connexion n'est utilisée qu'à partir de la Phase 2.

## Feuille de route

- **Phase 1** — Ingestion et Data Profiling : **terminée**
- **Phase 2** — Schéma BDD en étoile et Pipeline ETL
- **Phase 3** — Machine Learning et Évaluation
- **Phase 4** — Docker, API FastAPI, CI/CD

Le README sera complété en détail à l'issue du projet. Voir le dossier `docs/` pour les rapports détaillés de chaque rendu.