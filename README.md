# Airlines Delay Prediction

> Projet d'évaluation — Titre RNCP 38919 (Data Engineer). Statut : Phase 1 terminée — Phase 2 terminée côté code (Rendu 2 encore brouillon) — Phase 3 (Machine Learning) à démarrer — Phase 4 non commencée.

## Correspondance entre les phases du projet et les rendus officiels

Le projet est organisé en 4 **phases internes**. Elles ne correspondent **pas 1:1** aux 3 livrables DataScientest.


| Phase interne                                      | Livrable officiel DataScientest                                                                                 | Document                                                                               | Statut                                      |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------- |
| **Phase 1** — Ingestion et Data Profiling          | **Rendu 1** — Découverte et exploration                                                                         | [docs/rendu1_decouverte_exploration.md](docs/rendu1_decouverte_exploration.md)         | Terminée (Rendu 1 Final)                    |
| **Phase 2** — Schéma BDD en étoile et Pipeline ETL | **Rendu 2** — Organisation et modélisation **des données** (étoile, ETL ; la grille ne pose aucune question ML) | [docs/rendu2_organisation_modelisation.md](docs/rendu2_organisation_modelisation.md)   | Code terminé ; Rendu 2 encore brouillon     |
| **Phase 3** — Machine Learning et Évaluation       | Pas un livrable DataScientest isolé. Alimente le bloc 2 RNCP (justification d'algo) et un chapitre du rapport final | [docs/rendu3_machine_learning.md](docs/rendu3_machine_learning.md) (brouillon de chapitre) | À démarrer (vol + météo d'abord)         |
| **Phase 4** — Docker, API, CI/CD                   | **Rendu 3 officiel** = Rapport final « Consommation, déploiement et automatisation »                            | [docs/rapport_final.md](docs/rapport_final.md)                                         | Non commencée                               |


## Objectif

Prédire les retards de vols en combinant trois sources de données hétérogènes :


| Source                           | Données                                 | Usage                                  |
| -------------------------------- | --------------------------------------- | -------------------------------------- |
| **OpenSky Network**              | Vols, positions, statuts                | Variable cible (retard) + features vol |
| **OpenWeather**                  | Vent, pluie, visibilité                 | Features météo                         |
| **NewsAPI + BERT (HuggingFace)** | Actualités (grèves, météo extrême, ATC) | Score de sentiment / perturbation      |


La Phase 1 a mis en place l'ingestion et l'exploration des trois sources (modules d'ingestion, notebooks, tests unitaires, Rendu 1). La Phase 2 est **terminée côté code** : schéma PostgreSQL en étoile, pipeline ETL et ERD. Le Rendu 2 reste un **brouillon** (modélisation de données, pas de Machine Learning) ; relecture prévue plus tard, sans le marquer Final pour l'instant.

La prochaine étape est la **Phase 3 interne** (Machine Learning) : features vol et météo d'abord, score BERT ensuite si le temps le permet. Ce travail n'est **pas** le livrable officiel « Rendu 3 ». Le Rendu 3 DataScientest est le **rapport final** (consommation, déploiement, automatisation). Docker, API FastAPI et l'orchestration relèvent de la Phase 4 ; ils ne sont pas encore en place.

## Architecture du projet

```
src/
├── ingestion/     # Modules d'ingestion API (OpenSky, OpenWeather, NewsAPI)
├── processing/    # Nettoyage, ETL vers l'étoile, collecte hubs (BERT en Phase 3)
├── database/      # Connexion PostgreSQL et schéma en étoile (Phase 2, terminée)
├── models/        # Entraînement et sauvegarde du modèle (Phase 3, à venir)
├── api/           # API FastAPI de prédiction (Phase 4, à venir)
└── utils/         # Logging et chemins relatifs à la racine du projet
notebooks/         # Exploration et data profiling des 3 sources
tests/             # Tests unitaires (ingestion, schéma, ETL, chemins, logger)
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

`DATABASE_URL` pointe vers l'instance PostgreSQL locale utilisée par le schéma en étoile et l'ETL (Phase 2).

## Feuille de route

- **Phase 1** — Ingestion et Data Profiling : **terminée**
- **Phase 2** — Schéma BDD en étoile et Pipeline ETL : **terminée côté code** (PostgreSQL, étoile, ETL, ERD) ; Rendu 2 encore brouillon
- **Phase 3** — Machine Learning et Évaluation : **prochaine étape** (vol + météo d'abord, BERT ensuite si le temps le permet)
- **Phase 4** — Docker, API FastAPI, CI/CD : non commencée (Rendu 3 officiel = rapport final)

Le README sera complété en détail à l'issue du projet. Voir le dossier `docs/` pour les rapports des phases et des livrables officiels.
