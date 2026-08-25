# Rendu 2 — Rapport d'organisation et de modélisation des données

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)
> **Statut** : Brouillon — sections techniques pré-remplies, sections réflexives à compléter
> **Correspond à** : Phase 2 du projet — Organisation et modélisation des données

---

## 1. Architecture et stockage

### 1.1 Base de données choisie

**PostgreSQL** (système de gestion de base de données relationnel, client-serveur).

**Pourquoi PostgreSQL plutôt qu'une base embarquée ou une base NoSQL ?**
- **SGBD relationnel client-serveur mature et largement utilisé en entreprise** : PostgreSQL est un standard de l'industrie, avec un écosystème riche (extensions, outils d'administration, pilotes disponibles dans tous les langages), ce qui en fait un choix directement transférable à un contexte professionnel.
- **Gestion native de la concurrence d'accès** : contrairement à une base embarquée, PostgreSQL gère nativement plusieurs connexions simultanées en lecture et en écriture, ce qui correspond à un usage réaliste où le pipeline d'ingestion, l'API de prédiction et d'éventuels outils d'analyse accèdent à la base en parallèle.
- **Intégration naturelle avec un environnement conteneurisé** : une image Docker officielle est disponible, ce qui prépare directement la conteneurisation prévue en Phase 4 (le service de base de données rejoint les autres services du `docker-compose` dès la Phase 2, plutôt que d'être ajouté après coup).
- **Compatibilité avec SQLAlchemy** : l'utilisation d'un toolkit SQL standard (SQLAlchemy) au-dessus de PostgreSQL facilite l'écriture de requêtes portables et la maintenance du code d'accès aux données.
- MongoDB (NoSQL document) a été écarté : nos données sont structurées et relationnelles par nature (un vol a une météo et un contexte d'actualité associés à une date/aéroport) — un modèle relationnel est plus adapté qu'un stockage document flexible dont on n'a pas l'usage ici.

Une base de données analytique embarquée (de type DuckDB) aurait également constitué un choix technique valide pour le volume de données de ce projet, notamment pour sa simplicité de mise en œuvre sans serveur dédié. PostgreSQL a été retenu à la place afin de démontrer une compétence de gestion de base de données client-serveur complète (connexion réseau, gestion de la concurrence, conteneurisation), plus représentative des architectures rencontrées en environnement de production.

### 1.2 Choix d'architecture : Schéma en étoile (Star Schema)

Nous adoptons un **schéma en étoile**, standard des Data Warehouses pour les cas d'usage analytiques/ML :

```
                    ┌──────────────────┐
                    │   dim_date        │
                    │  (jour, mois,     │
                    │   jour_semaine)   │
                    └─────────┬─────────┘
                              │
┌──────────────────┐         │         ┌──────────────────────┐
│   dim_airport      │◄────────┼────────►│   dim_weather          │
│ (code IATA/ICAO,   │         │         │ (vent, pluie,          │
│  ville, pays)       │    ┌────┴────┐    │  visibilité, date/     │
└──────────────────┘    │  FACT   │    │  aéroport)             │
                          │ flights │    └──────────────────────┘
                          └────┬────┘
                              │
                    ┌─────────┴─────────┐
                    │ dim_news_sentiment │
                    │ (score sentiment,  │
                    │  date, mots-clés)  │
                    └────────────────────┘
```

**Pourquoi un schéma en étoile plutôt qu'un schéma en flocon ou un Data Lake brut ?**
- **Vs. flocon (snowflake)** : le flocon normalise davantage les dimensions (ex : `dim_airport` éclatée en `dim_ville` + `dim_pays`), ce qui réduit la redondance mais complexifie les jointures. Vu le volume modeste de notre projet (quelques centaines/milliers d'aéroports et d'entrées météo), la redondance du schéma en étoile est négligeable et les requêtes restent simples — critère prioritaire pour un pipeline ML qui doit produire une table plate (features) rapidement.
- **Vs. Data Lake brut (fichiers Parquet non modélisés)** : un Data Lake est pertinent pour du stockage brut à très grande échelle et une exploration ad hoc. Notre volumétrie ne le justifie pas, et un schéma en étoile offre une structure prête à l'emploi pour le feature engineering (Rendu 3 — ML) sans étape de modélisation supplémentaire en aval.

### 1.3 Table de faits et dimensions (détail)

| Table | Rôle | Colonnes clés (indicatif) |
|---|---|---|
| **fact_flights** | Table de faits — un enregistrement par vol observé | `flight_id`, `date_id` (FK), `airport_origin_id` (FK), `airport_dest_id` (FK), `callsign`, `retard_minutes` (variable cible), `altitude`, `vitesse` |
| **dim_airport** | Dimension aéroport | `airport_id` (PK), `code_iata`, `code_icao`, `ville`, `pays`, `latitude`, `longitude` |
| **dim_weather** | Dimension météo (rattachée à un aéroport + une date) | `weather_id` (PK), `airport_id` (FK), `date_id` (FK), `vent_kmh`, `precipitation_mm`, `visibilite_m` |
| **dim_news_sentiment** | Dimension sentiment des actualités | `sentiment_id` (PK), `date_id` (FK), `score_sentiment` (BERT), `nb_articles`, `mots_cles` |
| **dim_date** | Dimension temporelle (facilite les agrégations calendaires) | `date_id` (PK), `date`, `jour_semaine`, `mois`, `est_ferie` |

*(Le schéma ERD détaillé avec les types précis sera généré en `docs/erd_schema.png` ou via un fichier `.dbml`/`.sql` lors du développement de `src/database/schema.sql`.)*

### 1.4 Comment les sources sont-elles reliées entre elles ?

La clé de jointure commune entre les 3 sources est la paire **(aéroport, date/heure)** :
- Un vol (`fact_flights`) a un aéroport d'origine et de destination → jointure avec `dim_airport`.
- La météo (`dim_weather`) est rattachée à un aéroport et une date/heure → jointure avec `fact_flights` via `airport_id` + `date_id`.
- Le sentiment des actualités (`dim_news_sentiment`) est agrégé par date (et éventuellement mot-clé/zone géographique) → jointure via `date_id`.

---

## 2. Documentation technique

### 2.1 Pipelines de données : ETL, code-based (Python)

Nous choisissons une approche **ETL code-based en Python** (par opposition à une approche déclarative type dbt/SQL) :

**Pourquoi Python plutôt que dbt ?**
- dbt est excellent pour transformer des données **déjà présentes dans un entrepôt SQL**. Ici, l'étape critique est l'**ingestion depuis des APIs externes hétérogènes** (JSON complexe, authentification, gestion d'erreurs réseau, appel à un modèle BERT) — un besoin procédural que Python gère nativement, alors que dbt n'est pas conçu pour appeler des APIs ou exécuter un modèle de NLP.
- Cohérence d'écosystème : un seul langage (Python) pour l'ingestion, la transformation ET le Machine Learning (Rendu 3), ce qui simplifie la maintenance pour un projet solo.

**Logique du pipeline** :
1. **Extract** (`src/ingestion/`) : appel des 3 APIs, sauvegarde brute horodatée dans `data/raw/` (traçabilité et possibilité de rejouer les transformations sans réinterroger les APIs).
2. **Transform** (`src/processing/`) : nettoyage, normalisation, calcul du score de sentiment BERT, calcul de la variable cible (retard).
3. **Load** (`src/database/`) : écriture dans le schéma en étoile PostgreSQL.

### 2.2 Outils, frameworks et technologies utilisés

| Catégorie | Outil | Justification courte |
|---|---|---|
| Langage | Python 3.11+ | Écosystème data/ML complet |
| Config & validation | Pydantic | Typage strict, validation automatique des variables d'environnement et des schémas de données |
| HTTP | requests | Simplicité, standard de facto |
| Data | pandas | Manipulation tabulaire |
| NLP | transformers (HuggingFace) | Accès simple à des modèles BERT pré-entraînés |
| BDD | PostgreSQL | Voir §1.1 |
| Accès BDD | SQLAlchemy, psycopg2-binary | Toolkit SQL et pilote de connexion PostgreSQL pour Python |
| Profiling | ydata-profiling | Rapport de qualité automatisé (Rendu 1) |
| Tests | pytest | Standard Python, intégration CI/CD simple (Phase 4) |

---

## 3. Optimisation et fiabilité

- **Optimisations de performance** :
  - **Format Parquet** (colonnes compressées) pour les données intermédiaires plutôt que CSV → lecture plus rapide, typage préservé.
  - **Indexation** PostgreSQL sur les clés de jointure (`airport_id`, `date_id`) pour accélérer les jointures entre `fact_flights` et les dimensions.
  - [À COMPLÉTER une fois mesuré — temps d'exécution avant/après optimisation, taille des fichiers]
- **Qualité et cohérence des données** :
  - **Validation de schéma** via Pydantic à l'entrée de chaque pipeline (rejet/log des enregistrements non conformes plutôt que crash silencieux).
  - **Tests unitaires** (`tests/`) sur les fonctions de nettoyage et de transformation (ex : vérifier qu'un enregistrement avec une date invalide est bien rejeté).
  - **Logs structurés** (`src/utils/logger.py`) à chaque étape du pipeline (nombre d'enregistrements traités, erreurs rencontrées, durée d'exécution).
- **Mécanismes de mise à jour incrémentale** :
  - Chaque ingestion enregistre un **timestamp de dernière extraction** (fichier de métadonnées ou table `ingestion_log` en base).
  - Les nouvelles extractions ne récupèrent que les données postérieures à ce timestamp (évite de retraiter l'historique complet à chaque exécution) et utilisent une logique d'**upsert** (`INSERT ... ON CONFLICT`) dans PostgreSQL pour éviter les doublons.

---

## 4. Modalités d'évaluation (rappel officiel)

> *"Mise en situation professionnelle : le/la candidat(e) devra démontrer sa capacité à concevoir et documenter une architecture de données robuste, adaptée à la volumétrie et aux usages attendus."*
