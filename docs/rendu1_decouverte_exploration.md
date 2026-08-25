# Rendu 1 — Rapport de découverte et d'exploration des sources de données

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)
> **Statut** : Brouillon 
> **Correspond à** : Phase 1 du projet — Ingestion et Data Profiling

---

## 1. Introduction au projet

### 1.1 Contexte

- **Contexte métier / d'insertion du projet** : Ce projet s'inscrit dans une démarche de reconversion professionnelle vers le métier de Data Engineer, réalisée dans le cadre de la formation certifiante DataScientest visant le titre RNCP 38919.
- **Contexte technique** : Le secteur aérien génère un volume massif de données hétérogènes (position des vols en temps réel, conditions météorologiques, actualités impactant le trafic). Ces données sont dispersées dans des silos (APIs distinctes, formats différents) et ne sont, par défaut, reliées par aucun système commun. Le projet répond à un besoin technique classique de **Data Engineering : ingérer, fusionner et structurer des sources multi-format** pour les rendre exploitables par un pipeline de données (analytique et/ou Machine Learning).
- **Contexte économique** : Les retards de vols représentent un coût direct pour les compagnies aériennes (pénalités, correspondances manquées, hébergement) et un coût indirect pour les aéroports et les passagers. Anticiper un retard, même partiellement, a une valeur économique réelle (allocation des ressources, communication proactive).
- **Contexte scientifique** : Le projet s'appuie sur des travaux existants combinant données opérationnelles (ADS-B via OpenSky) et données exogènes (météo, actualités/sentiment) pour la prédiction de retards. L'apport de l'analyse de sentiment (NLP/BERT) sur des news est une approche moins conventionnelle qui vise à capturer des signaux faibls (grèves, perturbations sociales) absents des données structurées classiques.

### 1.2 Objectifs

- **Objectifs principaux** :
  1. **Collecte** : Extraire automatiquement 3 sources de données hétérogènes via API (vols, météo, actualités).
  2. **Structuration** : Nettoyer, normaliser et fusionner ces sources dans un schéma de données cohérent (voir Rendu 2).
  3. **Automatisation** : Construire des scripts d'ingestion réutilisables et paramétrables (pas de collecte manuelle).
  4. **Mise à disposition** : Rendre les données exploitables pour un cas d'usage concret (prédiction de retard, voir Rendu 3 — Machine Learning).
- **Niveau d'expertise de l'équipe vis-à-vis de l'ingestion/transformation/stockage** : Une expérience déjà significative en data/analytics précédait ce projet, ce qui a permis de concentrer l'effort d'apprentissage sur les compétences plus spécifiquement liées à l'ingénierie de données : conception de pipelines d'ingestion automatisés, architecture de stockage relationnelle et conteneurisation, moins pratiquées jusqu'ici.
- **Échanges avec des experts techniques ou métiers** : Ce projet a été mené en autonomie complète, sans échange complémentaire avec des experts du secteur aérien ou de la donnée en dehors du cadre d'encadrement standard de la formation.
- **Projet similaire connu** : De nombreux projets de prédiction de retards de vols existent sur Kaggle, notamment à partir des données du Bureau of Transportation Statistics américain. Ces projets ont servi de source d'inspiration pour la définition du périmètre et de l'approche de ce projet.

---

## 2. Exploration des données

### 2.1 Cadre

| Source | Type | Public / Propriétaire | Format | Fréquence de mise à jour |
|---|---|---|---|---|
| **OpenSky Network** | API REST | Public (inscription gratuite requise) | JSON | Temps quasi-réel (rafraîchissement ~5-10s côté OpenSky, mais on interroge par batch périodique) |
| **OpenWeather** | API REST | Public (clé API gratuite, quota limité) | JSON | Données courantes rafraîchies toutes les ~10 min côté fournisseur |
| **NewsAPI** | API REST | Public (clé API gratuite, quota limité) | JSON | Articles publiés en continu, requêtés par mots-clés |

- **Sécurité & Confidentialité (RGPD)** : Les 3 sources ne contiennent **pas de données personnelles identifiables (PII)** au sens RGPD :
  - OpenSky expose des identifiants techniques d'aéronefs (immatriculation, indicatif de vol) et des données de position — ce sont des données opérationnelles publiques, pas des données à caractère personnel (pas de lien avec des passagers).
  - OpenWeather fournit des mesures météorologiques agrégées par zone géographique — aucune donnée personnelle.
  - NewsAPI renvoie des articles de presse publics (titre, auteur éventuel, contenu) — le nom d'un journaliste peut apparaître, mais il s'agit d'une donnée déjà publique et non traitée à des fins d'identification. Aucune donnée sensible (santé, opinions, origine...) n'est collectée ou dérivée.
  - **Mesure de précaution appliquée** : aucun champ nominatif n'est conservé au-delà du strict nécessaire (le champ "auteur" des articles n'est pas utilisé dans les features du modèle).
- **Volumétrie approximative** : [À COMPLÉTER une fois les scripts d'ingestion exécutés — taille sur disque, nombre de lignes/fichiers collectés sur la période de test]

### 2.2 Pertinence

- **Données les plus pertinentes au regard des objectifs** :
  - OpenSky → variable cible potentielle (retard estimé via écart horaire) + features (compagnie, aéroport origine/destination, altitude/vitesse).
  - OpenWeather → features météo (vent, précipitations, visibilité) sur les aéroports de départ/arrivée.
  - NewsAPI + BERT → score de sentiment agrégé par jour/zone, comme proxy de perturbation (grève, incident).
- **Formats manipulés** : JSON en sortie d'API (toutes les sources), converti en tabulaire (pandas DataFrame / Parquet) pour le stockage intermédiaire.
- **Contraintes et limitations rencontrées** :
  - **Rate limiting** : OpenWeather et NewsAPI limitent le nombre d'appels en offre gratuite (nécessite une stratégie de cache/pagination et un espacement des appels).
  - **Authentification** : OpenSky nécessite un compte (Basic Auth / OAuth2 selon version d'API).
  - **Qualité d'origine** : Les données OpenSky peuvent contenir des valeurs manquantes (aéronefs hors couverture des récepteurs ADS-B) ; les articles NewsAPI ne sont pas garantis pertinents à 100% (nécessité de filtrage par mots-clés).

---

## 3. Préparation et nettoyage

- **Démarche retenue** : les règles de nettoyage sont identifiées et documentées au fur et à mesure de l'exploration de chaque source, avant d'être implémentées dans le pipeline de transformation en Phase 2 (Rendu 2). Ce choix évite d'écrire un code de nettoyage isolé source par source qu'il faudrait ensuite retravailler une fois les 3 sources connues et le schéma de fusion défini.
- **Règles de nettoyage identifiées sur OpenSky** (voir `notebooks/01_exploration_opensky.ipynb` pour le détail statistique complet) :
  - Le champ `sensors` est vide dans 100 % des cas observés : à exclure du pipeline.
  - L'altitude barométrique (`baro_altitude`) est manquante pour la quasi-totalité des avions au sol (95,5 %) contre une infime minorité en vol (0,05 %) : traitement différencié requis selon le statut `on_ground` plutôt qu'une imputation uniforme.
  - Des vitesses physiquement impossibles ont été observées (jusqu'à 1298 m/s), toujours associées à des positions anciennes : un filtre combinant l'âge de la donnée et un seuil de plausibilité physique est nécessaire avant tout usage de la vitesse comme feature.
- **Règles de nettoyage sur OpenWeather et NewsAPI** : à documenter ici une fois l'exploration de ces deux sources réalisée.
- **Scripts d'ingestion / automatisation** : Voir le module `src/ingestion/` (`opensky_client.py` disponible, `openweather_client.py` et `newsapi_client.py` à venir) — chaque client encapsule les appels API, la gestion des erreurs et la sauvegarde brute horodatée dans `data/raw/`.
- **Transformations et enrichissements prévus** : l'implémentation effective du nettoyage (`src/processing/data_cleaning.py`) et de l'analyse de sentiment (`src/processing/sentiment_analysis.py`) est prévue en Phase 2, une fois les 3 sources explorées et le schéma de fusion arrêté.

---

## 4. Visualisations et analyses descriptives (Data Profiling)

> **Note méthodologique** : ce Data Profiling porte sur la **qualité de l'ingestion** (distributions, complétude, corrélations), et non sur un dashboard de restitution finale (qui relèverait d'un outil de BI type Power BI/Tableau, hors scope de ce rendu).

- **Visualisations techniques produites** : [À COMPLÉTER une fois `src/processing/data_profiling.py` exécuté — rapport HTML `ydata-profiling` dans `data/profiling_reports/`, incluant distributions, matrice de corrélation, matrice de complétude]
- **Incohérences ou anomalies détectées** : [À COMPLÉTER — valeurs manquantes, doublons, outliers observés après exécution du profiling]
- **Conclusions pour la future organisation et modélisation des données** : [À COMPLÉTER — ex : quelles colonnes conserver, quelles jointures seront nécessaires entre les 3 sources, quel niveau de granularité (par vol ? par heure/aéroport ?)]

---

## 5. Modalités d'évaluation (rappel officiel)

> *"Mise en situation professionnelle reconstituée : à partir de sources de données réelles (API, web scraping, bases existantes…), le/la candidat(e) devra identifier, collecter et préparer les données pour qu'elles soient exploitables dans un pipeline de données."*

Ce rendu démontre la capacité à identifier des sources pertinentes, à les collecter de façon automatisée et à préparer leur exploitation future (Rendu 2).
