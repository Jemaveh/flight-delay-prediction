# Expérience actualités / BERT — questions, protocole, résultats, décision

> **Date de la campagne** : 02/09/2026 (après-midi).  
> **Complète** : `notebooks/05_sentiment_bert.ipynb` (figures, requêtes SQL) et `docs/rendu3_machine_learning.md` (§ 5.3 bis).  
> **Code** : `src/processing/scorer_sentiment.py` (DistilBERT, UPDATE `dim_news_sentiment.score_sentiment`).

Ce fichier récapitule le protocole, les chiffres et la décision de conservation de BERT. Ce n'est pas un tutoriel HuggingFace.

---

## 1. Questions posées avant (et pendant) le test

1. Est-ce qu'un score de sentiment sur les articles NewsAPI **améliore** la prédiction de la durée observée (`duree_minutes`) par rapport au même LightGBM **sans** colonnes actualités ?
2. Faut-il scorer **chaque vol** ou **chaque jour** ? (NewsAPI n'a pas de clé article ↔ vol.)
3. Un DistilBERT **multilingue** (FR/EN du corpus) est-il plus défendable qu'un lexique sur `mots_cles` ?
4. Si le RMSE ne bouge pas, est-ce que je **retire** BERT du pipeline, ou je le **garde** comme transformation d'entrepôt avec une limite écrite ?
5. Le 01/09 (jour de test du run précédent) n'avait **aucun** article : est-ce que remplir le 01–02/09 + BERT change la conclusion ?

Question **météo** liée à la même salve (souvent confondue avec « plus de vols ») : sans API d'historique OpenWeather, **combien de fois** faut-il relancer *Current Weather* pour que plus de vols aient une météo origine ?

---

## 2. Comment j'ai testé BERT

Ordre réel du 02/09, PC Windows, venv, Postgres local, **sans** Airflow Docker :

1. Smoke OpenSky (`--smoke`) — un appel, contrôle 200 / crédits.
2. NewsAPI **une passe**, cinq requêtes, `--depuis 2026-09-01 --jusqua 2026-09-02` (pas de boucle par jour).
3. `collecter_hubs --pause 9` **sans** `--reprendre` : 10 hubs × 2 endpoints, puis OpenWeather *current* (10 hubs).
4. ETL incrémental.
5. `python -m src.processing.scorer_sentiment` : lecture des JSON `newsapi_*.json` **déjà** en `data/raw/`, pas de rappel NewsAPI. DistilBERT CPU `lxyuan/distilbert-base-multilingual-cased-sentiments-student`. Polarité d'article = P(positive) − P(negative). **Moyenne par `date_id`**. `UPDATE` des 27 jours.
6. Même split, mêmes baselines : `entrainer --sans-actu --sans-sauvegarde` puis `entrainer` (avec actu, joblib écrasé).

Le notebook 05 **relit** les scores en base ; il ne retélécharge pas le modèle (RAM).

Ce que BERT **n'est pas** dans ce projet : un réseau à la place de LightGBM, un score par vol, un champ dans l'API FastAPI, une dépendance de l'image Docker API (`requirements-api.txt` sans `torch`).

---

## 3. Résumé des résultats (02/09/2026 12:31)

Entrepôt après salve : **13 822** vols, **110** météos, **27** jours d'actu, **185** articles scorés, **0** `score_sentiment` NULL.

Jeu modèle (météo origine **et** durée, plafond 8 h) : **3 034** lignes brutes filtrées → train **2016** / test **864**, coupure **01/09 12:56 UTC**.

| Variante | RMSE LightGBM | MAE LightGBM | RMSE médiane globale | RMSE médiane horaire |
| --- | --- | --- | --- | --- |
| Sans actu | 73,63 | 56,92 | 73,19 | **67,94** |
| Avec actu + BERT | **73,44** | 56,12 | 73,19 | **67,94** |

Écart actu+BERT vs sans actu : **−0,19 RMSE**. LightGBM **perd** contre la médiane globale **et** contre l'horaire.

Importances (splits, joblib avec actu) : `heure_utc` **1072** ; `nb_articles_actu` **21** ; `proxy_perturbation_actu` **4** (c'est par ce proxy que le score BERT entre dans X, pas en colonne brute).

Le run du **01/09** (sans BERT, test sans article) : 55,22 vs 56,72 vs médiane 40,43. **On ne compare pas** 73 et 55 : le test n'est plus le même créneau, la médiane elle-même a changé.

NewsAPI du 02/09 : seulement **3** articles bruts sur 01–02/09. Le recouvrement jour/vol existe surtout grâce au corpus déjà en base, pas grâce à cette passe.

---

## 4. Conclusion : je garde BERT dans le projet, je ne le vends pas comme un gain ML

**Décision** : je **conserve** le score en entrepôt et le module `scorer_sentiment`. Je **ne prétends pas** que BERT optimise LightGBM.

| Je fais | Je ne fais pas |
| --- | --- |
| Laisser `score_sentiment` rempli (transformation NLP de l'entrepôt) | Présenter BERT comme un gain de RMSE |
| Comparer `--sans-actu` dans le Rendu 3 | Retirer NewsAPI du projet parce que le RMSE ne bouge pas |
| Garder le joblib **avec** les deux colonnes actu (schéma API déjà aligné) | Recoller un BERT dans l'image FastAPI |

**Synthèse.** DistilBERT agrégé par jour : le RMSE ne bat pas une médiane. Le score reste en entrepôt ; il n'est pas un argument de performance.

---

## 5. Comment j'aurais pu mieux utiliser les actualités (sans tout jeter)

Le problème n'est pas seulement « BERT vs pas BERT ». C'est **le grain** et **le mélange**.

Aujourd'hui : tous les articles du jour → une moyenne mondiale → join sur la date UTC de `first_seen`. Un article *airport strike* à Istanbul et un article générique *flight delay* aux US se **diluent** dans le même scalaire, collé à un décollage CDG.

Pistes **dans le périmètre du projet** (même NewsAPI, plus de travail de features) :

1. **Filtrer avant de scorer** : ne garder que les articles qui mentionnent un hub (CDG, Heathrow, IATA/ICAO, ville). Sentiment **par hub × jour**, jointure `airport_origin_id` + `date_id`, plus une moyenne mondiale.
2. **Événement, pas polarité** : flags binaires `greve`, `atc`, `fermeture` (lexique déjà ébauché dans `proxy_perturbation_texte`) plutôt qu'une polarité autour de 0. Une grève est un **événement rare**, mal représentée par une moyenne [−1, 1] sur 27 jours.
3. **Décalage d'un jour** : actualité du **J−1** pour les vols du jour J (l'info « grève demain » précède souvent le trafic).
4. **Ne pas tester un jour sans article** : split temporel qui exige des news **aussi** en test, ou un jour tenu à part.
5. **Compter, pas scorer** : `nb_articles` déjà là ; un `nb_articles_pertinents` après filtre hub vaudrait mieux qu'un DistilBERT sur le bruit.

Pistes **autres sources** (si je reprenais la collecte actu) :

| Source | Intérêt | Limite |
| --- | --- | --- |
| **GDELT** | Événements géolocalisés, thèmes, gratuit | Bruit, volumétrie, autre pipeline |
| **Aviation Herald** / communiqués aéroports (RSS) | Pertinence métier | Pas une API unique, parsing HTML, droit de citation |
| **EUROCONTROL / NM** (perturbations réseau) | Signal trafic réel | Accès, pas du journalisme |
| OpenWeather *current* n'est **pas** une source actu | — | — |

Je n'ajoute **pas** ces sources dans le livrable actuel : quota, temps, et le RNCP note que j'ai **justifié** un essai BERT, pas que j'ai épuisé le web.

---

## 6. Annexe météo — combien de *current* sans API historique ?

OpenWeather *Current* = **un instant** par hub. L'ETL ne rattache que si `|horodatage − first_seen| ≤ 3 h` (origine). **Une** capture couvre donc une fenêtre de **6 heures**, pas les 24 h d'une salve OpenSky.

**13 822 / 3 034 ≈ 22 %** de vols avec météo origine + durée : du même ordre que **6 h / 24 h = 25 %**. Relancer OpenSky sans étaler la météo dans la journée n'y change presque rien.

| Objectif | Combien de passes *current* (10 hubs à chaque fois) |
| --- | --- |
| Couvrir **24 h** de vols **à venir**, sans trou | **4** captures **espacées de 6 h** (ex. 00, 06, 12, 18 UTC) |
| Météo plus proche de l'heure de décollage | **8** / 24 h (toutes les 3 h) |
| Relancer 4 fois **le même après-midi** | Presque **la même** fenêtre ± 3 h — inutile |
| Rattraper les vols **déjà** en base hors des ± 3 h actuelles | **Impossible** avec *current* : l'instant est passé |

Sans l'historique OpenWeather (souvent payant), deux options honnêtes :

1. **Horloge** : tâche météo **séparée** (Airflow ou script) 4 fois par jour, **indépendante** de la salve OpenSky.
2. **Autre source d'archive** (Open-Meteo Historical Forecast) — **fait le 02/09**, récap `docs/experience_meteo_openmeteo.md` : 62 % de météo origine, proxy OD testé, **pas** de gain utile vs médiane.

Je n'ai pas lancé 4 passes météo le 02/09 : une seule, en fin de `collecter_hubs`, comme les salves précédentes.

---

## 7. Tentative du 02/09 (après-midi) : hub × jour, flags, J−1, test avec signal

Fichiers : `src/processing/actu_hub.py`, `src/models/experience_actu.py`. CLI : `python -m src.models.experience_actu --avec-bert`. **N'écrase pas** le joblib de l'API.

### Ce qui a marché / pas marché

| Piste | Résultat |
| --- | --- |
| Ne scorer que les articles qui **citent un hub** | **Échec de volumétrie** : 185 articles → **3** lignes article×hub. Les requêtes NewsAPI sont génériques (`flight delay`, pas « CDG »). 42 vols avec signal hub : sous le seuil d'un split. |
| Flags **grève / ATC** (grain **jour**, tout le corpus) | Faisable. Seuls, **sans** BERT : RMSE **78,91** (pire que la médiane 73,19). |
| Actu du **J−1** | Faisable. Le test du 01/09 12:56 a un signal via la veille (864/864 lignes). |
| Ne pas tester un jour **sans** article | Faisable : filtre après split temporel. Ici tout le test avait déjà J ou J−1. |

### Chiffres (même train 2016 / test 864 que le run LightGBM standard)

| Variante | RMSE LightGBM | Médiane globale | Médiane horaire | Bat la globale |
| --- | --- | --- | --- | --- |
| Météo seule (même split) | 73,63 | 73,19 | **67,94** | Non |
| Flags + J−1 **sans** BERT | 78,91 | 73,19 | 67,94 | Non |
| Flags + J−1 **avec** DistilBERT jour | **71,51** | 73,19 | 67,94 | **Oui** |

LightGBM **bat la médiane globale** (71,51 vs 73,19) avec BERT jour + J−1 + flags. Il **perd encore** contre la médiane **horaire** (67,94). Importances news : `nb_articles_jour` 17, `nb_articles_jour_j1` 12, `flag_greve_jour` 9, `score_bert_jour_j1` 9 — loin derrière `heure_utc` (1012).

### Décision après cette tentative

Je **ne remplace pas** le joblib / le schéma FastAPI : colonnes nouvelles, gain faible, l'horaire reste meilleur. Je **garde** l'expérience dans le repo pour l'oral.

---

## 8. Collecte NewsAPI par hub (02/09/2026 13:00)

**Quota.** 100 req/jour. Après les 5 requêtes génériques du matin, il en restait ~95 : **on pouvait le faire aujourd'hui**. 10 appels `--par-hub` (un hub, une langue). 10×5 langues = 50 : possible, non fait. Pas de boucle par jour.

CLI : `python -m src.ingestion.newsapi_client --par-hub --depuis 2026-08-25 --jusqua 2026-09-02`. Dix HTTP **200**. JSON `data/raw/newsapi_20260902_130059.json`.

Articles bruts : LFPG 2, EGLL 58, EDDF 59, EHAM 4, LEMD 25, LIRF 5, LTFM 1, EIDW 26, EDDM 34, LEBL 19 (**233**). Expérience (JSON cumulés) : **386** articles, **204** lignes article×hub (contre 3 avant le tag `code_icao`), **56** couples jour×hub.

Même split 2016 / 864 :

| Variante | RMSE LightGBM | Médiane globale | Médiane horaire | Bat la globale |
| --- | --- | --- | --- | --- |
| Météo seule | 73,63 | 73,19 | **67,94** | Non |
| Hub + flags + J−1 + BERT (après `--par-hub`) | **77,33** | 73,19 | 67,94 | **Non** |

Plus d'articles tagués hub **n'améliore pas** (77,33 > 73,63). Le 71,51 du § 7 (BERT jour, presque pas de hub) reste le seul à battre la médiane globale, pas l'horaire. Joblib API **non** remplacé.

**Synthèse.** Dix requêtes le jour même ont tagué hub × jour. L'expérience n'a pas battu la médiane.
