# Rendu 3 — Rapport de Machine Learning

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)  
> **Statut** : Brouillon
> **Correspond à** : Phase 3 du projet — Machine Learning et évaluation

---

## 1. Objet du rendu et périmètre

Ce rendu documente le **premier modèle** entraîné à partir de l'entrepôt PostgreSQL (consommation du fichier `joblib`, API, conteneurisation, orchestration).

Je m'appuie sur les vols OpenSky et la météo OpenWeather déjà joints dans l'étoile, plus une jointure **par date UTC** vers `dim_news_sentiment`. Une passe NewsAPI ciblée (01/09/2026 13:18) a ajouté les articles des jours de vols. Le score BERT n'entre pas dans ce modèle : `score_sentiment` reste NULL. Un flag `--sans-actu` permet de comparer le même split, les mêmes baselines, sans `nb_articles_actu` ni `proxy_perturbation_actu`.

---

## 2. Données utilisées

### 2.1 Volumétrie de l'entrepôt

Le jeu part de `fact_flights`, joint à `dim_date`, `dim_weather` (météo origine et destination, LEFT JOIN) et `dim_news_sentiment` (date UTC de `first_seen`). Aucun appel d'API pendant l'entraînement.


| Effectif                                   | Valeur                         |
| ------------------------------------------ | ------------------------------ |
| Vols dans `fact_flights`                   | 7524                           |
| Observations `dim_weather`                 | 100                            |
| Jours d'actualité (`dim_news_sentiment`)   | 26                             |
| `retard_minutes` non NULL                  | 1663 (77,9 % de NULL)          |
| dont avec météo origine                    | 4                              |
| Vols avec météo origine **et** `last_seen` | 1335 (17,7 %)                  |
| Durées > 8 h écartées du jeu modèle        | 6                              |
| Lignes réellement entraînées               | 1329                           |
| Routes OD ≥ 5 vols **parmi** les 1335      | 0                              |
| Destination ICAO renseignée                | 5564 (74,0 %)                  |


Les 26 jours d'actualité couvrent **27/07–31/08/2026** : 19 jours du corpus Rendu 1 (jusqu'au 24/08) plus **7 jours** ajoutés le 01/09 (25–31/08). `score_sentiment` est tout NULL. `nb_articles` va de 1 à 19. La fenêtre `first_seen` des vols s'étend du **25/08 au 01/09/2026 UTC** (sept jours calendaires : 25–28, 30–31/08 et 01/09 ; **pas de vol le 29/08**). **6 jours communs** (25–28, 30–31/08) : **6821 / 7524 = 90,7 %** des vols ont `nb_articles_actu` > 0. Le **01/09** (703 vols, dont tout le test) n'a **aucun** article. BERT n'a pas tourné.

Le calendrier seedé dans `dim_date` (01/07–31/12) est plus large ; ce n'est pas la profondeur du signal vol.

Les 10 observations météo du 01/09 vers 12:51 (`openweather_20260901_125113.json`) portent `dim_weather` à 100 (90 + 10). Une capture *current* ne recouvre qu'une fenêtre ± 3 h : la salve `/flights/*` porte sur **24 h**, d'où **17,7 %** de météo origine (1335 / 7524), plus bas que les 55,3 % d'août où la fenêtre vols était plus courte par rapport aux captures déjà en base.

### 2.2 Jointure météo et filtre d'entraînement

La météo n'est pas collée « au jour » : l'ETL rattache l'observation OpenWeather la plus proche de `first_seen` (origine) ou de `last_seen` (destination), écart maximal de **3 heures**, et seulement sur les hubs couverts. Au-delà, ou hors hub, `weather_*_id` est NULL (Rendu 2).

Je n'entraîne que les lignes avec **météo origine renseignée** et `last_seen` présent : 1335 / 7524 = **17,7 %**. Biais assumé : les vols hors des dix hubs, ou hors de la fenêtre ± 3 h autour d'une capture OpenWeather *current*, n'entrent pas.

Parmi ces 1335, **6** ont une durée observée **> 8 h** (max brut du jeu complet **1827 min**, ~30,5 h ; 373 durées > 8 h sur les 7524, presque toutes sans météo origine). Ce n'est pas un vol européen entre mes hubs : c'est un trou ADS-B. Je les **retire** (seuil documenté : 480 minutes). Je ne winsorise pas. Restent **1329** lignes.

La météo destination reste **quasi absente** (20 / 7524 = 0,3 %). Je la laisse dans la matrice de features (LightGBM accepte les NaN) ; elle n'informe presque rien.

### 2.3 Ce qui n'est pas dans le jeu

- Pas d'horaire programmé (aucune des trois sources n'en expose).
- Pas de score BERT : `score_sentiment` NULL ; le proxy lexical s'applique aux `mots_cles` joints (max 0,24 en train, 0 sur le test du 01/09).
- Pas de destination ICAO comme feature : même à 74 % de dest renseignée, ce n'est pas un substitut d'horaire.
- `retard_minutes` existe en base mais n'est **pas** la cible (voir § 3).
- Pas d'article NewsAPI le **01/09**, jour de tout le jeu de test.

---

## 3. Définition du problème et de la cible

### 3.1 Ce que OpenSky permet réellement

OpenSky `/flights/departure` et `/flights/arrival` exposent `firstSeen` / `lastSeen` : première et dernière position vue par le réseau ADS-B. **Pas** un slot DGAC/FAA. Inventer un horaire théorique (table d'offsets « un CDG–LHR doit faire 1 h 15 ») serait une donnée synthétique présentée comme une mesure : je ne le fais pas.

La colonne `retard_minutes` est un **proxy** déjà calculé par l'ETL : durée observée moins la médiane de la même route, si la destination est connue et si la route a au moins 5 vols. Il remplit **1663** lignes, dont **4** avec météo origine. Je ne « complète » pas les NULL. Je ne bascule pas la cible vers ce proxy sous 50 lignes non NULL **avec** météo.

### 3.2 Trois options, un seuil

Seuil interne : **50 lignes** minimum pour entraîner. Trois formulations sans horaire inventé :


| Option | Formulation                                                                                     | Effectif observé                         | Décision                |
| ------ | ----------------------------------------------------------------------------------------------- | ---------------------------------------- | ----------------------- |
| **C**  | Régression du proxy `retard_minutes` (non NULL **et** météo origine)                            | 4 (1663 non NULL au total)               | Refusée (sous le seuil) |
| **A**  | Classification « plus long que la médiane historique du couple OD », après filtre météo origine | 0 route à ≥ 5 vols                       | Refusée                 |
| **B**  | Régression de la **durée observée** `(last_seen − first_seen)`                                  | 1335 avant plafond 8 h, **1329** ensuite | Retenue                 |


`retenir_cible` (`src/models/jeu.py`) applique ce diagnostic ; je ne corrige pas le résultat à la main.

Hors filtre météo, **256** routes OD ont ≥ 5 vols (1782 faits). Dès que j'exige la météo origine, plus aucune. L'option A n'est pas « il n'y a pas de routes » : c'est la jointure ± 3 h qui les vide.

### 3.3 Formulation retenue

**Option B** : régression de `duree_minutes`. Question posée au modèle : *sachant la météo au départ, le hub, le jour, l'heure UTC (et, si elles varient, les actualités du jour), quelle durée observée OpenSky a-t-on ?*

Ce n'est **pas** une prédiction de retard au sens industriel (réel − programmé). C'est une consommation honnête de l'entrepôt, sur une cible que les sources permettent de mesurer.

---

## 4. Features, fuite de données et split temporel

### 4.1 Features retenues

Colonnes de `src/models/jeu.py` (`COLONNES_FEATURES`, plus `COLONNES_FEATURES_ACTU` si `--sans-actu` n'est pas passé) :

- Hub d'origine (catégoriel ICAO).
- Calendrier : jour de semaine ISO, mois, heure UTC dérivée de `first_seen` (connue au décollage : heure + minutes / 60).
- Météo origine : température, vent, rafale, pluie 1 h, visibilité, humidité.
- Météo destination : les mêmes champs sauf l'humidité dest, souvent NULL.
- Actualités (jointure `dim_news_sentiment` sur la date UTC de `first_seen`) : `nb_articles_actu`, `proxy_perturbation_actu` (score stocké s'il existe, sinon lexique sur `mots_cles` déjà en base). Pas de BERT. NewsAPI n'est pas rappelée pendant l'entraînement.

### 4.2 Fuite évitée

`last_seen` n'entre pas dans X : la cible **est** la durée, qui s'en sert. Sont également exclus : `duree_minutes`, `retard_minutes`, `first_seen` brut, `icao24`, `callsign`, `flight_id`, les identifiants de jointure, la destination ICAO, `mots_cles_actu`, `score_sentiment_actu`.

Un split **aléatoire** i.i.d. mélangerait des vols d'après-midi dans le train et des vols plus tôt dans le test : on « prédirait » le passé. Je coupe sur `first_seen` au quantile **70 %** : train = instants **strictement avant** le seuil, test = **après**. Pas de validation croisée k-fold : un fold mélangerait passé et futur.

### 4.3 Split observé (01/09/2026 13:20, après passe NewsAPI 25–31/08 et filtre 8 h)


| Jeu   | Lignes | Borne `first_seen`              |
| ----- | ------ | ------------------------------- |
| Train | 930    | jusqu'à 01/09/2026 09:33:06 UTC |
| Test  | 399    | depuis 01/09/2026 09:33:10 UTC  |


Le test tient dans un créneau d'environ **1 h 15** le 01/09 (jusqu'à 10:47 UTC, max du jeu). Le train mélange les vols d'août encore joints à une météo ± 3 h **et** le matin du 01/09. Le split reste temporellement honnête ; ce n'est pas une validation « semaine prochaine ». Avec ou sans actualités, **même** split (les features news ne changent pas le filtre). En train, **710 / 930 = 76,3 %** des lignes ont `nb_articles_actu` > 0. En test : **0 / 399** — le 01/09 n'a aucun article.

Avant cette salve OpenSky (CLI 12:23, 1290 vols) : train **497** / test **213**, seuil 26/08 14:44. Le 28/08 sans plafond 8 h : 500 / 214.

Hyperparamètres LightGBM volontairement petits (`max_depth=4`, `num_leaves=15`, `min_child_samples=20`, `n_estimators=200`, `learning_rate=0.05`) pour limiter le surapprentissage sur ~930 lignes.

---

## 5. Baseline, modèle et métriques

### 5.1 Deux baselines médiane

Référence naïve **globale** : la **médiane de `duree_minutes` vue en train**, recopiée sur tout le test.

Référence **par heure UTC** : médiane du train **dans l'heure entière** de `first_seen`. Si cette heure a moins de **5** observations en train (même seuil que les routes OD), ou si elle est absente, on retombe sur la médiane globale. C'est la barre plus exigeante en principe : `heure_utc` domine déjà les importances LightGBM ; battre seulement la médiane globale peut flatter un modèle qui n'a appris que l'heure.

Ce n'est pas LightGBM qui sert de baseline. Pas d'Accuracy / F1 / AUC : la cible n'est pas une classe.

### 5.2 LightGBM

Le jeu est **tabulaire** (hub catégoriel, météo numérique, beaucoup de NaN à destination, actualités numériques éventuellement constantes). Un gradient boosting sur arbres gère ce mélange sans one-hot ni imputation forcée. Un réseau de neurones n'a pas d'avantage sur cette table ; il en aurait sur le texte (BERT, plus tard). Une régression linéaire m'aurait imposé encodage et imputation, pour un premier jet.

LightGBM s'entraîne en secondes, expose `feature_importances_`, se sérialise en `joblib`. Fichiers : `src/models/jeu.py` (SQL, cible, features, split, jointure actu), `src/models/entrainer.py` (modèle, deux baselines, `--sans-actu`). Artefact : `models/modele_vol_meteo.joblib` (dossier gitignoré), entraîné **avec** actu (après la passe NewsAPI du 01/09 13:18).

### 5.3 Métriques (CLI du 01/09/2026 13:19–13:20, 7524 vols, plafond 8 h, 26 jours d'actu)

Même split, mêmes baselines, deux matrices X :


| Métrique       | LightGBM avec actu | LightGBM `--sans-actu` | Médiane globale | Médiane par heure UTC |
| -------------- | ------------------ | ---------------------- | --------------- | --------------------- |
| RMSE (minutes) | 55,22              | 56,72                  | 40,43           | 69,60                 |
| MAE (minutes)  | 50,54              | 51,82                  | 34,60           | 63,80                 |


**Avec actualités un peu mieux que sans** (−1,50 RMSE, −1,28 MAE). Importances : `nb_articles_actu` **50** splits, `proxy_perturbation_actu` **0**. Ce n'est **pas** un signal d'actu sur le test : les 399 lignes de test sont le 01/09, **sans article**. L'écart vient des arbres appris en train (76,3 % des 930 lignes ont un `nb_articles` non nul). La médiane globale gagne encore largement (40,43 vs 55,22). **Les news n'aident toujours pas à battre la baseline utile.**

**Bat la médiane globale : False. Bat la médiane horaire : True.** (avec et sans actu)

La médiane globale gagne encore (40,43 vs 55,22 / 56,72). Sur ce test étroit du 01/09, la médiane **horaire** est plus mauvaise que la globale (69,60 vs 40,43) : les heures 9–10 UTC du test ne portent pas le même mix de durées que les mêmes heures en train (août + matin du 01/09). LightGBM bat cette barre horaire ; il ne bat pas la médiane simple. Je le dis tel quel.

Avant la salve OAuth (CLI 12:23, 1290 vols) : LightGBM **80,43** / 67,87 contre globale **43,88** / 37,59 et horaire **44,48** / 39,37 (False / False). Le 28/08 sans plafond 8 h : 72,90 vs 44,06. Un jet plus tôt le 28/08, sur **972** vols et un test d'environ 40 minutes, donnait LightGBM **40,20** contre médiane **53,83**. Ce n'est **pas** le résultat de ce rendu. Avant la passe NewsAPI (CLI 12:52) : avec = sans = 56,72, importances news à 0 (aucun recouvrement).

Lecture du 55,22 / 56,72 vs 40,43 / 69,60 :

- Le **test est un créneau** ~09:33–10:47 UTC le 01/09 : mix de durées différent du train (août + matinée), **et zéro article** ce jour-là.
- `heure_utc` **domine** encore les importances (voir § 5.4). Battre l'horaire ne suffit pas à battre la médiane globale.
- La **météo destination est quasi absente**.
- Les **actualités varient en train**, constantes à 0 en test : le −1,5 RMSE n'est pas « l'actu prédit le 01/09 ».
- La cible reste une **durée ADS-B** (après plafond 8 h), pas un retard borné. 930 lignes de train ne suffisent pas au boosting contre une médiane robuste.

Ça n'autorise pas à vendre « la météo prédit les retards », ni « les actualités n'apportent rien en général » : elles n'apportent **presque rien ici**, même avec 90,7 % des vols joints à un jour d'actu, parce que le split teste un jour sans article et que le modèle perd encore contre la médiane.

### 5.4 Importances (splits LightGBM, run 01/09/2026 13:19, avec actu)


| Feature                                                                             | Importance |
| ----------------------------------------------------------------------------------- | ---------- |
| `heure_utc`                                                                         | 915        |
| `temperature_origine`                                                               | 155        |
| `vent_origine`                                                                      | 125        |
| `jour_semaine`                                                                      | 116        |
| `hub_origine`                                                                       | 84         |
| `humidite_origine`                                                                  | 71         |
| `nb_articles_actu`                                                                  | 50         |
| `mois`                                                                              | 23         |
| `pluie_origine`                                                                     | 7          |
| rafale / visibilité origine, **toute** la météo dest, `proxy_perturbation_actu`     | 0          |


L'heure UTC split encore largement plus que la température, le vent ou le jour. `nb_articles_actu` n'est plus à zéro (50 splits), loin derrière le calendrier et la météo origine. Le proxy lexical (max 0,24 en train) n'est pas utilisé. Sans `--sans-actu`, le joblib embarque les deux colonnes.

---

## 6. Collecte opérationnelle (OAuth 200, plus de 403)

L'entraînement ne rappelle pas OpenSky. La collecte qui alimente l'entrepôt dépend d'un **API Client** OAuth2 (`OPENSKY_CLIENT_ID` / `OPENSKY_CLIENT_SECRET` → jeton Bearer). Le login compte et Trino ne débloquent pas `/flights/*`. Timeout HTTP porté à **60 s**.

Un HTTP **429** n'arrête plus toute la liste : backoff (`Retry-After` si l'en-tête est présent, sinon 60 s), **un** réessai, puis passage au **hub suivant**. Un 404 arrival (aucun vol sur la fenêtre) est une liste vide, pas un crash. Un **401/403** arrête la salve vols. `--reprendre` saute les couples endpoint / ICAO déjà présents en JSON dans `data/raw/`. OpenWeather est interrogé en fin de salve. NewsAPI n'est **pas** appelée par `collecter_hubs`.

Smoke unique (01/09 vers 12:47, `python -m src.ingestion.opensky_client --smoke`) : `/flights/departure` LFPG, fenêtre ~2 h, **HTTP 200**, 73 vols. `X-Rate-Limit-Remaining` : **3940**. Jeton non logué.

Salve du **01/09/2026** vers 12:47–12:51 (`python -m src.processing.collecter_hubs --pause 9`, les dix hubs, **sans** `--reprendre`) : **20/20** appels `/flights/*` en HTTP **200** (LTFM arrival : HTTP **404**, 0 vol, liste vide). Aucun 429, aucun 403. Pas de deuxième salve. Dernier `X-Rate-Limit-Remaining` vu : **3340** (environ 30 crédits par appel `/flights`, 20 × 30 = 600, 3940 − 600 = 3340). OpenWeather 10/10 (`openweather_20260901_125113.json`).

ETL incrémental (salve vols) : 6682 vols lus, 448 rejetés, **6234** upsert ; 10 météo nouvelles ; actualités alors skippées. Entrepôt : **7524** faits (1290 + 6234), **100** météo.

**Passe NewsAPI** du 01/09 vers 13:18 (`python -m src.ingestion.newsapi_client --depuis 2026-08-25 --jusqua 2026-09-01T23:59:59`) : **5 requêtes** (les cinq `REQUETES_ACTUALITES`, une passe, pas de boucle par jour, pas de pagination). Cinq HTTP **200**. JSON `data/raw/newsapi_20260901_131812.json` (71 articles bruts : fr 7, en 64, de/es/it 0 ; 68 conservés après nettoyage). Clé API non loguée. Timeout client porté à 60 s.

ETL actualités (rejeu de la série) : 431 lues, 249 rejetées (doublons inter-fichiers), **26** jours upsert. `dim_news_sentiment` : **19 → 26** (+7 jours : 25–31/08). Recouvrement vols ∩ news : **6 jours**, **6821 / 7524 = 90,7 %** des faits. Pas d'article le 01/09. Vols et météo inchangés (46 JSON OpenSky skippés, 12 OpenWeather skippés).

Salves antérieures, pour mémoire : 28/08 (429 sur EDDM arrival / LEBL departure) → 1290 faits ; 01/09 11:55 (`--reprendre`, 0 appel OpenSky) ; 01/09 12:19 (**20/20 HTTP 403**, API Client encore inactif) → toujours 1290 faits, 90 météo. Ce 403 n'est plus l'état courant.

Ce backoff n'est **pas** un ordonnanceur. Les commandes (NewsAPI, `collecter_hubs`, ETL, entraînement) restent séparées. Airflow, un cron, un enchaînement automatique relèvent du **rapport final** (Phase 4), pas de ce rendu.

---

## 7. Limites — ce que ce modèle n'est pas

- **Pas de la prédiction de retard** : pas d'horaire programmé, proxy `retard_minutes` inexploitable pour C (1663 lignes, **4** avec météo origine, sous le seuil de 50). Le titre du projet reste une intention ; la donnée OpenSky ne livre pas le slot.
- **Volume** : 1329 lignes après plafond 8 h, sept jours de `first_seen`, dix hubs européens. **17,7 %** des vols ont une météo origine (fenêtre ± 3 h vs salve `/flights` 24 h). `dim_weather` : 100 observations.
- **Je n'explique pas une route** : après filtre météo, 0 route OD ≥ 5 vols. Les durées ADS-B > 8 h (6 lignes du jeu modèle, 373 sur les 7524) sont écartées du modèle ; il en reste de très courtes.
- **Actualités jointes, signal faible** : 26 jours en base, 6 jours communs avec les vols (90,7 % des faits), `score_sentiment` NULL. RMSE 55,22 avec actu vs 56,72 sans, vs médiane 40,43. Le test du 01/09 n'a aucun article. Ce n'est pas « les news ne marchent jamais » ; ici elles ne battent toujours pas la médiane.
- **LightGBM perd** contre la médiane globale (RMSE 55,22 vs 40,43) **et gagne** contre la médiane horaire (69,60). Avant OAuth, sur 1290 vols : 80,43 vs 43,88 / 44,48. Un score antérieur qui « battait » la baseline sur un test trop court (40,20 vs 53,83) ne doit pas être présenté comme le résultat de ce rendu.

---

## 8. Reproduction

Aucun appel d'API n'est nécessaire pour **rejouer** l'entraînement, si l'entrepôt PostgreSQL contient déjà les faits. Les trois commandes du pipeline, dans l'ordre, sont :

```bash
python -m src.ingestion.newsapi_client --depuis 2026-08-25 --jusqua 2026-09-01T23:59:59
python -m src.processing.collecter_hubs --pause 9
python -m src.processing.etl
python -m src.models.entrainer
python -m src.models.entrainer --sans-actu --sans-sauvegarde
```

NewsAPI : une passe, cinq requêtes `REQUETES_ACTUALITES`, quota 100/jour. Pas de boucle par jour. `collecter_hubs` sans `--hubs` interroge les dix ICAO et **n'appelle pas** NewsAPI. Sans `--reprendre`, OpenSky est rappelé même si des JSON d'août existent déjà (nécessaire pour une fenêtre des 24 h). Un smoke unique précède toute salve : `python -m src.ingestion.opensky_client --smoke`. Un HTTP **403** arrête les vols ; un **429** passe au hub suivant. L'ETL saute les fichiers déjà journalisés ; un JSON NewsAPI nouveau rejoue toute la série (agrégat journalier). `entrainer` échoue clairement si PostgreSQL est injoignable, sans afficher `DATABASE_URL`. `--sans-actu` retire les deux colonnes news, mêmes lignes, mêmes baselines.

Le notebook `notebooks/04_modelisation_vol_meteo.ipynb` retrace le diagnostic, le choix de cible, le split et les métriques en réutilisant `src/models/` (pas de copie du pipeline). Ses cellules de code peuvent afficher un instantané antérieur (ex. 1286 / 1290 vols) si le notebook n'a pas été relancé ; les chiffres de **ce rendu** sont ceux du CLI du 01/09/2026 13:19–13:20 (plafond 8 h, deux baselines, avec/sans actu, 7524 vols / 100 météo / 26 jours d'actu).

Tests : `python -m pytest -q` — le module modèle mocke un DataFrame, sans réseau et sans Postgres (`--sans-actu` couvert).

---

## 9. Suite

L'analyse de sentiment BERT, l'API FastAPI et Docker relèvent du **rapport final** (consommation, déploiement, automatisation). Le recouvrement actu / vols existe désormais sur six jours d'août ; il manque le 01/09 (jour du test). Relancer NewsAPI en boucle n'y changera pas grand-chose tant que le split teste un créneau sans article. Ce rendu s'arrête au modèle vol + météo ± actu, à ses métriques, et aux limites assumées.

---

## 10. Modalités d'évaluation (rappel)

Ce rendu démontre la capacité à formuler un problème supervisé à partir d'un entrepôt réel, à justifier un algorithme (LightGBM vs une médiane globale **et** une médiane par heure UTC), à comparer une jointure d'actualités par date (avec vs sans, sans BERT), à l'évaluer (RMSE, MAE) et à en assumer les limites — notamment l'absence d'horaire programmé, un test sans article le 01/09, et un modèle qui **ne bat pas** la médiane globale (55,22 / 56,72 vs 40,43) sur le jeu du 01/09/2026 13:20.

La consommation du `joblib`, le déploiement et l'automatisation ne sont pas évalués ici : ils appartiennent au rapport final.
