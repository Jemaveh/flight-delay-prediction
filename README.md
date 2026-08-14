# Airlines Delay Prediction

> Projet d'évaluation — Titre RNCP 38919 (Data Engineer)
> Statut : Phase 1 — Ingestion et Data Profiling, en cours

## Correspondance entre les phases du projet et les rendus officiels

Le projet est organisé en 4 phases, chacune correspondant à un rendu de la grille d'évaluation officielle DataScientest.

| Phase du projet | Rendu officiel correspondant | Rapport détaillé |
|---|---|---|
| **Phase 1** — Ingestion et Data Profiling | Rendu 1 — Découverte et exploration | [`docs/rendu1_decouverte_exploration.md`](docs/rendu1_decouverte_exploration.md) |
| **Phase 2** — Schéma BDD en étoile et Pipeline ETL | Rendu 2 — Organisation et modélisation | [`docs/rendu2_organisation_modelisation.md`](docs/rendu2_organisation_modelisation.md) |
| **Phase 3** — Machine Learning et Évaluation | Rendu 3 — Machine Learning et Évaluation | [`docs/rendu3_machine_learning.md`](docs/rendu3_machine_learning.md) |
| **Phase 4** — Docker, API, CI/CD | Rapport final — Consommation, déploiement et automatisation | [`docs/rapport_final.md`](docs/rapport_final.md) |

## Objectif

Prédire les retards de vols en combinant trois sources de données hétérogènes :

| Source | Données | Usage |
|---|---|---|
| **OpenSky Network** | Vols, positions, statuts | Variable cible (retard) + features vol |
| **OpenWeather** | Vent, pluie, visibilité | Features météo |
| **NewsAPI + BERT (HuggingFace)** | Actualités (grèves, météo extrême, ATC) | Score de sentiment / perturbation |

## Architecture du projet

```
src/
├── ingestion/     # Clients d'extraction API (OpenSky, OpenWeather, NewsAPI)
├── processing/    # Nettoyage, sentiment analysis (BERT), data profiling
├── database/      # Connexion et schéma de la base de données (schéma en étoile)
├── models/        # Entraînement et sauvegarde du modèle de Machine Learning
├── api/           # API FastAPI de prédiction (/predict, /health)
└── utils/         # Logging et fonctions transverses
```

Le détail de chaque choix d'architecture est documenté dans les rapports du dossier `docs/`.

## Installation

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env       # puis renseigner les clés API
```

## Feuille de route

- **Phase 1** — Ingestion et Data Profiling
- **Phase 2** — Schéma BDD en étoile et Pipeline ETL
- **Phase 3** — Machine Learning et Évaluation
- **Phase 4** — Docker, API FastAPI, CI/CD

Le README sera complété en détail à l'issue du projet. Voir le dossier `docs/` pour les rapports détaillés de chaque rendu.
