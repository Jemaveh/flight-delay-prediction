# Rapport final — Consommation, déploiement et automatisation

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)
> **Statut** : Brouillon — sections techniques pré-remplies, sections réflexives à compléter
> **Livrable** : Rapport final — consommation, déploiement et automatisation. Le Machine Learning a son propre rendu (`docs/rendu3_machine_learning.md`).
> **Phases internes** : le déploiement et l'automatisation relèvent surtout de la Phase 4 ; ce document consolide aussi les phases 1 à 3.

> **Rappel méthodologique** : le rapport final n'est pas une juxtaposition des Rendus 1, 2 et 3. Avant la soutenance, relire et mettre à jour ces trois rendus, puis les résumer ici plutôt que de les recopier tels quels.

---

## 1. Synthèse consolidée des rendus précédents

- **Synthèse Rendu 1** (Découverte & exploration) : [À COMPLÉTER — résumé en 5-10 lignes, avec liens vers `docs/rendu1_decouverte_exploration.md`]
- **Synthèse Rendu 2** (Organisation et modélisation **des données**) : [À COMPLÉTER — résumé en 5-10 lignes, avec liens vers `docs/rendu2_organisation_modelisation.md`]
- **Synthèse Rendu 3** (Machine Learning) : [À COMPLÉTER — résumé en 5-10 lignes, avec lien vers `docs/rendu3_machine_learning.md`]

---

## 2. Gestion du code et bonnes pratiques

- **Dépôt Git** : [À COMPLÉTER — lien vers le dépôt GitHub/GitLab une fois créé]
- **Structure professionnelle** : Architecture modulaire en couches (`src/ingestion`, `src/processing`, `src/database`, `src/models`, `src/api`, `src/utils`, `config`) — chaque module a une responsabilité unique, testable indépendamment (voir `tests/`).
- **Fichier de rejeu du projet** : `README.md` (racine) documente l'installation (`requirements.txt`, `.env.example`) et les commandes pour reproduire le pipeline de bout en bout.
- **Gestion des secrets** : Toutes les clés d'API (OpenSky, OpenWeather, NewsAPI) et la chaîne de connexion à la base de données sont chargées via des **variables d'environnement** (fichier `.env`, jamais commité — voir `.gitignore`), validées au démarrage par `config/settings.py` (Pydantic `BaseSettings`). Aucun secret n'est écrit en dur dans le code source.

---

## 3. Déploiement

- **Mode de déploiement retenu** : Conteneurisation **Docker** via `docker-compose`, orchestrant :
  1. Un service **pipeline** (batch) exécutant l'ingestion + transformation + chargement en base à intervalle régulier.
  2. Un service **API** (FastAPI, `src/api/`) exposant un endpoint `/predict` qui consomme le modèle sauvegardé (`joblib`) pour retourner une prédiction de retard à la demande.
  3. Un service **base de données** (PostgreSQL conteneurisé, avec volume de données persistant).
- **Bonnes pratiques DevOps appliquées** :
  - Images Docker basées sur des tags de version explicites (pas de `latest`) pour la reproductibilité.
  - Fichier `.dockerignore` pour éviter d'embarquer les secrets/données dans l'image.
  - Variables d'environnement injectées au conteneur (pas de secrets dans le `Dockerfile`).
  - [À COMPLÉTER une fois implémenté — multi-stage build, healthchecks, etc.]

### 3.1 Endpoints de l'API développée (annexe technique anticipée)

| Endpoint | Méthode | Description |
|---|---|---|
| `/health` | GET | Vérification de l'état de disponibilité du service (healthcheck) |
| `/predict` | POST | Reçoit les features d'un vol (JSON), retourne la probabilité/prédiction de retard |
| `/model/info` | GET | Retourne les métadonnées du modèle chargé (version, date d'entraînement, métriques) |

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
