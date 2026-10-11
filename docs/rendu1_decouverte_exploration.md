# Rendu 1 — Rapport de découverte et d'exploration des sources de données

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)  
> **Statut** : Final  
> **Correspond à** : Phase 1 du projet — Ingestion et Data Profiling

---

## 1. Introduction au projet

### 1.1 Contexte

- **Contexte métier / d'insertion du projet** : Après un Master en Biologie obtenu en 2019, j'ai travaillé plusieurs années dans la recherche scientifique en biologie végétale, où je concevais des protocoles expérimentaux et recueillais des données de terrain et de laboratoire. C'est au fil de ces expériences que j'ai identifié la phase du travail que je préférais réellement : le traitement et l'analyse de la donnée, plus que sa seule production. En 2022, en autodidacte, j'ai découvert Python en développant un script capable de reconnaître automatiquement sur des photographies la présence de maladies sur des feuilles de plantes et d'en calculer la surface, dans le cadre de mes expérimentations. Cette expérience a agi comme un déclencheur et m'a convaincue de me reconvertir dans la DATA.
  Je me suis d'abord formée et certifiée comme Data Analyst, un choix cohérent avec mon parcours scientifique initial. J'ai ensuite poursuivi jusqu'au niveau Master avec un parcours Data Engineer, une orientation qui correspondait davantage à mes affinités techniques et pour laquelle je constatais un besoin croissant dans la majorité des entreprises.
  
  
  Ce projet s'inscrit directement dans cette trajectoire : il est conçu comme une pièce de portfolio technique, en complément des missions réalisées durant mon alternance en entreprise, pour démontrer ma capacité à intervenir sur toute la chaîne de valeur — de l’ingestion des données à la mise en production dans un contexte professionnel reconstitué.
  Le choix du secteur aérien pour ce projet n'est pas anodin : je vis et travaille à Toulouse, un bassin d'emploi dont l'économie est très largement structurée autour d'Airbus et de la filière aéronautique. Travailler sur une problématique data ancrée dans ce secteur me permet de rapprocher ce projet de portfolio de mon environnement professionnel local, et potentiellement des opportunités d'emploi que je vise.
- **Contexte technique** : Le secteur aérien génère un volume massif de données hétérogènes (position des vols en temps réel, conditions météorologiques, actualités impactant le trafic). Ces données sont dispersées dans des silos (APIs distinctes, formats différents) et ne sont, par défaut, reliées par aucun système commun. Le projet répond à un besoin technique classique de **Data Engineering : ingérer, fusionner et structurer des sources multi-format** pour les rendre exploitables par un pipeline de données (analytique et/ou Machine Learning).
- **Contexte économique** : Les retards de vols représentent un coût direct pour les compagnies aériennes (pénalités, correspondances manquées, hébergement) et un coût indirect pour les aéroports et les passagers. Par exemple, en Europe, le **Règlement (CE) n° 261/2004** impose aux compagnies des obligations financières strictes :
  - **Prise en charge dès 2 heures de retard** (selon la distance) : restauration, rafraîchissements et, si nécessaire, hébergement avec transport.
  - **Droit au remboursement ou réacheminement à partir de 5 heures de retard** si le passager renonce à voyager.
  - **Indemnisation forfaitaire (par passager) dès 3 heures de retard à l'arrivée** (sauf circonstances extraordinaires), s'élevant à **250 €** (vols ≤ 1 500 km), **400 €** (vols intra-UE > 1 500 km ou autres vols entre 1 500 et 3 500 km) ou **600 €** (vols extra-UE > 3 500 km).
  Dans ce cadre légal contraignant, anticiper un retard — même partiellement — possède une valeur économique réelle. Cela permet d'optimiser l'allocation des ressources au sol, de rationaliser la communication proactive et d'atténuer les pénalités financières directes.
- **Contexte scientifique** : Le projet s'appuie sur des travaux existants combinant données opérationnelles (ADS-B via OpenSky) et données exogènes (météo, actualités/sentiment) pour la prédiction de retards. L'apport de l'analyse de sentiment (NLP/BERT) sur des news est une approche moins conventionnelle qui vise à capturer des signaux faibles (grèves, perturbations sociales) absents des données structurées classiques.



### 1.2 Objectifs

- **Objectifs principaux** :
  1. **Collecte** : Extraire automatiquement 3 sources de données hétérogènes via API (vols, météo, actualités).
  2. **Structuration** : Nettoyer, normaliser et fusionner ces sources dans un schéma de données cohérent (voir Rendu 2).
  3. **Automatisation** : Construire des scripts d'ingestion réutilisables et paramétrables (pas de collecte manuelle).
  4. **Mise à disposition** : Rendre les données exploitables pour un cas d'usage (durée de vol observée / tentative de retard — le Rendu 3 précise ce que les sources permettent réellement de prédire).
- **Niveau d'expertise vis-à-vis de l'ingestion/transformation/stockage** : Une expérience déjà significative en data/analytics précédait ce projet, ce qui a permis de concentrer l'effort d'apprentissage sur les compétences plus spécifiquement liées à l'ingénierie de données : conception de pipelines d'ingestion automatisés, architecture de stockage relationnelle et conteneurisation, moins pratiquées jusqu'ici.
- **Échanges avec des experts techniques ou métiers** : Ce projet a été mené en autonomie complète, sans échange complémentaire avec des experts du secteur aérien ou de la donnée en dehors du cadre d'encadrement standard de la formation.
- **Projet similaire connu** : De nombreux projets de prédiction de retards existent sur Kaggle, à partir des données du Bureau of Transportation Statistics américain. Ces fichiers contiennent déjà l'horaire programmé et le retard. Ils ont inspiré le *thème* du projet ; ils ne décrivent pas le contrat des trois APIs choisit (voir Rendu 3).

### 1.3 Cahier des charges (cadrage)

Ce sous-ensemble tient lieu de cahier des charges **non exhaustif** : périmètre, interlocuteurs fictifs du produit, indicateurs. Il n'y a pas eu d'entretiens métier ni de questionnaires : le projet est mené en autonomie dans le cadre de la formation. Les « personas » ci-dessous sont donc un cadrage de **contrat de données**,pas le résultat d'une enquête terrain.

**Why** : les retards ont un coût (CE n°261/2004, correspondances, ressources au sol). Les données opérationnelles, météo et actualités existent, mais dans des silos.

**What** : un pipeline Data Engineer Europe : trois APIs publiques → JSON horodatés → entrepôt en étoile → modèle de **durée observée** ADS-B → API de consommation. Ce n'est **pas** un clone de Flightradar24, ni un moteur d'indemnisation passager.

**Value** : rendre interrogeable un entrepôt reproductible et un service `/predict` honnête sur ce que les sources mesurent. Le règlement 261/2004 motive le sujet du projet mais il ne définit pas ce que l’API renvoie.

**Dans le périmètre (IN)** :

- Ingestion automatisée OpenSky (`/flights/departure` et `/flights/arrival`, dix hubs européens), OpenWeather *Current*, NewsAPI.
- Nettoyage, étoile PostgreSQL, ETL incrémental.
- Régression de la durée observée (`last_seen − first_seen`), modèle enregistré (`joblib`), API FastAPI, conteneurisation, orchestration quotidienne décrite (DAG en pause ; exécution réelle = scripts locaux), CI, monitoring du **service** (Prometheus / Grafana).

**Hors périmètre (OUT)** :

- Retard « réel − prévu » : aucune des trois APIs n'expose l'horaire programmé. Donc impossible de calculer le retard passager (heure d’arrivée réelle - heure annoncée sur le billet).
- Tableau de bord cartographique des avions en direct.
- Entretiens utilisateurs, Experience Map terrain, MLflow, mesure de *data drift*, Kubernetes.

**Personas** :

| Persona | Besoin | Servi par ce projet ? |
|---|---|---|
| Exploitant / OCC (Operations Control Center) / passager 261/2004 | Retard vs horaire publié | **Non** — pas d'heure prévue dans les sources |
| Analyste interne | Durée plausible, service appelable | **Oui** — `POST /predict`, `/docs` (Phase 4) |
| Data engineer | Pipeline relançable, quota, qualité | **Oui** — JSON, étoile, logs, DAG en pause, CI |

**Indicateurs de cadrage (quatre KPI)** — à suivre pour prioriser :

| KPI | Nature | État actuel des choses |
|---|---|---|
| Crédits OpenSky restants (`X-Rate-Limit-Remaining`) | Technique / quota | Seau `/flights` 4000 / jour ; une salve 10 hubs ≈ 20 appels, ~30 crédits chacun |
| Part des vols avec météo origine (± 3 h, *current*) | Qualité de jointure | ~17–22 % selon la salve (3 664 / 21 054 au 04/09) |
| RMSE LightGBM vs médiane globale (durée, min) | Performance modèle | Le modèle **ne bat pas** la médiane pour le moment (54,02 vs 44,07 au 04/09) |
| Disponibilité du service (`GET /health`, jauge joblib) | Exploitation | Processus UP + fichier `modele_vol_meteo.joblib` chargé |


Ce qui limite ce projet, ce n'est pas le nombre de vols en base : c'est l'absence d'horaire programmé (donc pas de retard calculable) et le fait qu'une capture météo *current* ne recouvre qu'une fenêtre de quelques heures, alors que chaque salve OpenSky porte sur 24h.

### 1.4 Veille technologique et réglementaire
Avant de figer les trois APIs, trois pistes existaient déjà. Aucune n'a été retenue comme source principale.

**Flightradar24** :
Type de données : carte, flotte mondiale, souvent des horaires commerciaux. Il n'existe **pas** d'API Flightradar24 gratuite en donnée réelle : l'API officielle est un abonnement payant.  Le *sandbox* est gratuit mais renvoie des réponses figées.
Pour contourner cela il faudrait faire du **scraping**.
OpenSky est un choix rapide et fiable : ADS-B public, documenté, scriptable — mais au prix de l'horaire manquant (la documentation OpenSky l'indique : pas d'horaires ni de retards commerciaux).

**FlightAware (AeroAPI)** : API payante, hors du cadrage retenu (trois APIs publiques). Non utilisée.

**CSV Kaggle / BTS (US DOT)** :
Il a déjà l'horaire et le retard (`DEP_DELAY`). L'utiliser *à la place* d'OpenSky fait un bon exercice ML (souvent une classe ≥ 15 min) et mais rien d'interressant d'un point de vue Data Engineer : plus d'API live, plus d'Europe, plus de quotas à gérer. Le **mélanger** dans `fact_flights` n'ajoute aucune heure prévue aux vols européens et casse l'étoile (voir Rendu 3).

**Réglementation.** Le règlement (CE) n° 261/2004 définit le retard indemnizable comme un écart à l'heure d'arrivée *prévue* : les trois APIs du projet n'exposent pas cette heure, donc cette promesse n'est pas tenable. Le RGPD ne bloque pas le projet (pas de PII passager) mais interdit d'inventer un couplage passager–vol. Les quotas (OpenSky 4000 crédits / jour, NewsAPI 100 requêtes / jour) calent le rythme de collecte autant qu'un texte de loi.
En résumé : Flightradar et Kaggle ont été écartés pour garder un pipeline Europe, public, reproductible. Le pivot (durée observée plutôt qu'un retard affiché) est la conséquence de ce choix.

### 1.5 Analyse SWOT

| | |
|---|---|
| **Forces** | Trois APIs publiques documentées ; pipeline reproductible (ingestion, JSON, plus tard étoile) ; RGPD simple (pas de PII). |
| **Faiblesses** | Pas d'heure prévue ; grains incompatibles (vol / point météo / jour d'actu) ; quotas ; PC personnel limité à 8 Go. |
| **Opportunités** | Sur ce pipeline : météo d’archive (Open-Meteo, déjà testée en Phase 3) pour mieux recouvrir les 24 h de vols ; machine plus dimensionnée pour qu’Airflow exécute vraiment la collecte. |
| **Menaces** | HTTP 429 / épuisement du seau OpenSky|

---

## 2. Exploration des données

### 2.1 Cadre


| Source              | Type     | Public / Propriétaire                   | Format | Fréquence de mise à jour                                                                        |
| ------------------- | -------- | --------------------------------------- | ------ | ----------------------------------------------------------------------------------------------- |
| **OpenSky Network** | API REST | Public (inscription gratuite requise)   | JSON   | Temps quasi réel (rafraîchissement ~5-10s côté OpenSky, mais on interroge par batch périodique) |
| **OpenWeather**     | API REST | Public (clé API gratuite, quota limité) | JSON   | Données courantes rafraîchies toutes les ~10 min côté fournisseur                               |
| **NewsAPI**         | API REST | Public (clé API gratuite, quota limité) | JSON   | Articles publiés en continu, requêtés par mots-clés                                             |


- **Sécurité & Confidentialité (RGPD)** : Les 3 sources ne contiennent **pas de données personnelles identifiables (PII)** au sens RGPD :
  - OpenSky expose des identifiants techniques d'aéronefs (immatriculation, indicatif de vol) et des données de position — ce sont des données opérationnelles publiques, pas des données à caractère personnel (pas de lien avec des passagers).
  - OpenWeather fournit des mesures météorologiques agrégées par zone géographique — aucune donnée personnelle.
  - NewsAPI renvoie des articles de presse publics (titre, auteur éventuel, contenu) — le nom d'un journaliste peut apparaître, mais il s'agit d'une donnée déjà publique et non traitée à des fins d'identification. Aucune donnée sensible (santé, opinions, origine...) n'est collectée ou dérivée.

**Mesures de précaution appliquées** : aucun champ nominatif n'est conservé au-delà du strict nécessaire (le champ "auteur" des articles n'est pas utilisé dans les features du modèle).

- **Volumétrie approximative** (mesurée sur une capture de référence par source, voir `notebooks/01_exploration_opensky.ipynb`, `notebooks/02_exploration_openweather.ipynb` et `notebooks/03_exploration_newsapi.ipynb` pour le détail complet) :
  - **OpenSky** : environ 4 100 avions et 1 Mo de JSON brut par appel (bounding box Europe). Sur deux semaines de collecte, une capture toutes les 5 minutes représenterait environ 4 Go, contre environ 1,4 Go toutes les 15 minutes.
  - **OpenWeather** : 10 lignes (une par hub aéroportuaire) et environ 11 Ko de JSON brut par capture. Sur deux semaines de collecte, même une capture toutes les 10 minutes ne représenterait qu'environ 22 Mo au total.
  - **NewsAPI** : 120 articles et environ 129 Ko de JSON brut pour une capture de 5 requêtes mots-clé/langue. Le facteur limitant n'est pas le volume (quelques dizaines de Mo maximum sur deux semaines de collecte, même au quota maximal) mais le nombre de requêtes autorisées, plafonné à 100 par jour sur le plan gratuit.

Ces trois ordres de grandeur très différents (Mo, Ko, centaines de Ko) s'expliquent directement par l'architecture de chaque API (zone géographique pour OpenSky, point géographique pour OpenWeather, recherche par mots-clés pour NewsAPI) plutôt que par une différence de qualité entre les sources.

Côté stockage, chaque appel de collecte produit un fichier JSON horodaté, un par source (`data/raw/opensky_*.json`, `openweather_*.json`, `newsapi_*.json`) : pas de base de données à ce stade du projet, celle-ci n'étant prévue qu'en Phase 2 une fois le schéma en étoile arrêté (voir Rendu 2).



### 2.2 Pertinence

- **Données les plus pertinentes au regard des objectifs** :
  - OpenSky → trajectoire observée (`first_seen` / `last_seen`) : on en dérive une **durée**, pas un retard d'horaire (aucune des trois APIs n'expose l'heure prévue ; voir Rendu 3).
  - OpenWeather → features météo (vent, précipitations, visibilité) sur les aéroports de départ/arrivée.
  - NewsAPI + BERT → score de sentiment agrégé par jour/zone, comme proxy de perturbation (grève, incident).
- **Formats manipulés** : JSON en sortie d'API (toutes les sources), converti en tabulaire (pandas DataFrame / Parquet) pour le stockage intermédiaire.
- **Contraintes et limitations rencontrées** :
  - **Rate limiting** : OpenWeather et NewsAPI limitent le nombre d'appels en offre gratuite (nécessite une stratégie de cache/pagination et un espacement des appels).
  - **Authentification** : OpenSky nécessite un compte (Basic Auth / OAuth2 selon version d'API).
  - **Qualité d'origine** : Les données OpenSky peuvent contenir des valeurs manquantes (aéronefs hors couverture des récepteurs ADS-B) ; les articles NewsAPI ne sont pas garantis pertinents à 100 % (nécessité de filtrage par mots-clés).
  - **Pas d'horaire programmé** : OpenSky, OpenWeather et NewsAPI ne donnent pas l'heure de départ ou d'arrivée **annoncée**. Un retard au sens du règlement 261/2004 (ou des jeux Kaggle BTS) est *heure réelle − heure prévue*. Sans l'heure prévue, cette cible n'est pas mesurable. Les projets Kaggle cités en en veille techno partent de CSV américains qui ont déjà cette colonne ; ce n'est pas le contrat de nos trois APIs. Conséquence pour le modèle : Rendu 3.

---



## 3. Préparation et nettoyage

- **Démarche retenue** : les règles de nettoyage sont identifiées au fil de l'exploration de chaque source, puis appliquées concrètement, à titre de démonstration, directement dans chaque notebook sur les données déjà chargées pour cette exploration. Cette démonstration reste volontairement locale à chaque notebook. Le script de nettoyage réutilisable (`src/processing/data_cleaning.py`) a été écrit **en Phase 2**, une fois le schéma en étoile arrêté (Rendu 2).

- **Mise à plat déjà appliquée sur les 3 sources** : au-delà du nettoyage à proprement parler, les 3 notebooks appliquent déjà une première transformation sur chaque source — la mise à plat du JSON imbriqué renvoyé par chaque API en DataFrame tabulaire (`pd.json_normalize` pour les champs `main.`*/`wind.*`/`sys.*` d'OpenWeather, reconstruction ligne par ligne pour les états OpenSky et les articles NewsAPI).

- **Contrôles préalables d'intégrité du texte et des unités** : avant de définir la moindre règle de nettoyage, chaque notebook vérifie l'intégrité de ce qui arrive de l'API. Sur les colonnes textuelles des 3 sources, un contrôle d'encodage cherche les séquences de mojibake caractéristiques d'un texte UTF-8 relu en Latin-1 (`Ã©`, `Ã¨`, `Ã` , `Ãª`, `Ã¼`, `Ã§`, `â€`) ainsi que le caractère de remplacement U+FFFD, et affiche des libellés accentués comme preuve visuelle.
S'y ajoutent, sur les textes d'articles, la recherche de balises et d'entités HTML résiduelles et la validation de la forme des URL ; et, sur les colonnes numériques, la confrontation des unités documentées aux ordres de grandeur réellement observés (vitesses et altitudes OpenSky, échelle de température et vitesse de vent OpenWeather). Aucun de ces contrôles n'a conduit à une correction : les 3 sources arrivent en UTF-8 correctement décodé et dans les unités annoncées, ce qui évite d'avoir à prévoir une étape de réparation d'encodage ou de conversion d'unités dans le pipeline. 

- **Nettoyage identifié puis appliqué sur OpenSky** (voir `notebooks/01_exploration_opensky.ipynb` pour le détail statistique complet) :
  - Le champ `sensors` est vide dans 100 % des cas observés. **Appliqué** : colonne supprimée.
  - Des vitesses au sol physiquement impossibles ont été observées, toujours associées à des positions très anciennes (donnée périmée, pas une vraie vitesse de croisière). **Appliqué** : filtre combinant l'âge de la position (seuil de 300 secondes) et un seuil de vitesse plausible (400 m/s), qui retire quelques lignes par capture.
  - L'altitude barométrique (`baro_altitude`) est manquante pour la quasi-totalité des avions au sol, contre une infime minorité en vol : traitement différencié selon `on_ground`, repris dans `data_cleaning.py` (Phase 2) une fois le grain `/flights/*` arrêté. Les notebooks d'exploration portent encore sur `/states/all`.
  - La colonne `callsign` affiche une complétude de 100 % au sens de pandas alors qu'une petite partie de ses valeurs sont des chaînes réduites à des espaces : le taux brut surestime la disponibilité de l'indicatif de vol. **Reste à généraliser** dans le script de nettoyage : conversion de ces chaînes vides en valeurs manquantes dès le chargement, avant tout calcul de complétude.
  - Certains zéros masquent une "non-mesure" plutôt qu'une valeur réelle (`velocity == 0` ou `baro_altitude == 0` sur un avion déclaré en vol), et l'écart entre `baro_altitude` et `geo_altitude` dépasse ponctuellement le kilomètre sur un même avion au même instant. **Reste à généraliser** : traiter ces zéros comme non renseignés et ajouter un contrôle de cohérence entre les deux altitudes, le filtre sur l'âge de la position n'écartant qu'une partie de ces cas.
- **Nettoyage identifié puis appliqué sur OpenWeather** (voir `notebooks/02_exploration_openweather.ipynb`) :
  - Les champs `rain.1h` et `wind.gust` sont absents de la réponse pour la majorité des aéroports : absence structurelle (le phénomène n'est renvoyé que lorsqu'il est mesuré). **Appliqué** : remplacement par zéro, les deux colonnes passant de 1/10 à 10/10 valeurs non nulles sur la capture explorée.
  - La visibilité est plafonnée à 10 000 mètres par l'API (aucune valeur de la capture explorée ne dépassait déjà ce seuil).
- **Nettoyage identifié puis appliqué sur NewsAPI** (voir `notebooks/03_exploration_newsapi.ipynb`) :
  - Le champ `content` est systématiquement tronqué à environ 200 caractères sur le plan gratuit (confirmé à 213,9 caractères en moyenne sur 120 articles). **Appliqué** : colonne exclue, la capture explorée passant de 11 à 10 colonnes ; l'analyse de sentiment s'appuiera sur `title` et `description`, fournis en entier.
  - La recherche par mots-clés génériques peut remonter des articles hors sujet (tensions géopolitiques, actualité sans lien avec le trafic aérien commercial) : aucun critère simple et objectif de filtrage n'a été dégagé à ce stade, donc aucun filtre supplémentaire n'a été appliqué. Un raffinement n'a pas été poussé ensuite : le signal jour reste un agrégat (Phases 2–3).
  - Le même article peut apparaître sous plusieurs URL distinctes (reprise par un agrégateur, ou même média servi sous deux domaines) : le contrôle de doublons par URL ne détecte pas ces cas, alors qu'une comparaison sur le titre normalisé (minuscules, sans ponctuation) les fait ressortir. **Reste à généraliser** : dédupliquer sur le titre normalisé en plus de l'URL, sans quoi un même événement serait compté plusieurs fois dans le signal d'actualité d'une journée.
  - La répartition par langue des articles est très déséquilibrée (une capture dominée à 80 % par l'anglais) : point à intégrer dans la conception du futur modèle d'analyse de sentiment, sans action de nettoyage associée.
- **Scripts d'ingestion / automatisation** : Voir le module `src/ingestion/` (`opensky_client.py`, `openweather_client.py`, `newsapi_client.py`) — chaque module encapsule les appels API, la gestion des erreurs et la sauvegarde brute horodatée dans `data/raw/`.
- **Suite réalisée après ce rendu** : le script `src/processing/data_cleaning.py` et l'étoile (Rendu 2) ; le score BERT journalier (`src/processing/scorer_sentiment.py`, Phase 3). Le filtrage de pertinence NewsAPI n'a pas été poussé au-delà de la déduplication titre / URL (Rendu 2–3).

---



## 4. Visualisations et analyses descriptives (Data Profiling)

Cette section documente le **dispositif de profiling** et les constats qui n'ont pas donné lieu à un filtre à ce stade.

**Dispositif** : Un rapport `ydata-profiling` par source, généré depuis les notebooks d'exploration et enregistré dans `data/profiling_reports/` (`opensky_profiling_report.html`, `openweather_profiling_report.html`, `newsapi_profiling_report.html`) : distributions, complétude, valeurs distinctes, corrélations. En complément, des figures ciblées dans les notebooks : complétude par colonne ; nuage géographique et pays d'origine (OpenSky) ; température et vent par aéroport (OpenWeather) ; langue de requête (NewsAPI). Les volumes et les extrêmes OpenSky varient d'une capture à l'autre ; les *types* d'anomalies, eux, restent stables.

**Constats supplémentaires** :

- **OpenSky** : quelques altitudes barométriques légèrement négatives d'une capture à l'autre (sol sous le niveau de la mer, ou artefact ADS-B). Aucun doublon sur `icao24` : chaque appel `/states/all` est un instantané, une ligne par avion.
- **OpenWeather** : pas de valeur hors bornes sur température, humidité, pression, vent et visibilité. `main.temp`, `main.feels_like` et l'encadrement min/max sont cohérents ; sur certains aéroports les trois valeurs sont égales : l'encadrement est alors inexploitable comme feature à lui seul.
- **NewsAPI** : `publishedAt` est en UTC ; le tampon de collecte était en heure locale naïve (bug corrigé dans le module d'ingestion, biais d'environ 2 h sur l'âge des articles, impact limité vu un âge moyen d'environ 6,8 jours).

---

## 5. Conclusions pour la future organisation et modélisation des données

Cette première phase fixe le contrat des trois APIs: elles n'ont pas le même grain : un avion à un instant (OpenSky), un aéroport à une capture (OpenWeather), un article (NewsAPI).

La jointure utile est donc le couple (aéroport, date/heure) dans le schéma en étoile, après agrégation des actualités par jour, sans inventer une clé article–vol. C'est l'objet du Rendu 2.

Les colonnes exclues et le script `data_cleaning.py` sont déjà décrits dans le nettoyage ci-dessus. La cible « retard vs horaire » n'est pas calculable avec ces APIs : c'est cadré dans l'introduction ; le Rendu 3 en tire la conséquence pour le modèle.

---