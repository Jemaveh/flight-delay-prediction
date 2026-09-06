# Expérience actualités / BERT — questions, protocole, résultats, décision

> **Complète** : `notebooks/05_sentiment_bert.ipynb` (figures, requêtes SQL) et `docs/rendu3_machine_learning.md`

> **Code** : `src/processing/scorer_sentiment.py` (DistilBERT, UPDATE `dim_news_sentiment.score_sentiment`).

Ce fichier récapitule le protocole, les chiffres et la décision de conservation de BERT.

---

## 1. Questions posées avant (et pendant) le test

1. Est-ce qu'un score de sentiment sur les articles NewsAPI **améliore** la prédiction de la durée observée (`duree_minutes`) par rapport au même LightGBM **sans** colonnes actualités ?
2. Faut-il scorer **chaque vol** ou **chaque jour** ? (NewsAPI n'a pas de clé article ↔ vol.)
3. Un DistilBERT **multilingue** (FR/EN du corpus) est-il plus défendable qu'un lexique sur `mots_cles` ?
4. Si le RMSE ne bouge pas, est-ce que je **retire** BERT du pipeline, ou je le **garde** comme transformation d'entrepôt avec une limite écrite ?
5. Le 01/09 (jour de test du run précédent) n'avait **aucun** article : est-ce que remplir le 01–02/09 + BERT change la conclusion ?

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

## 4. Conclusion

**Décision** : je **conserve** le score en entrepôt et le module `scorer_sentiment`, mais en spécifiant que BERT n'optimise pas LightGBM.

**Synthèse.** DistilBERT agrégé par jour : le RMSE ne bat pas une médiane. Le score reste en entrepôt ; il n'est pas un argument de performance.

---

## 5. Comment améliorer l'utilisation des actualités

Le problème n'est pas seulement « BERT vs pas BERT » : c'est **le grain** et **le mélange**.

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

---

## 6. Ces pistes, testées le 02/09 (hors joblib)

Même split que la partie 3 (train 2016 / test 864). Code : `src/processing/actu_hub.py`, `src/models/experience_actu.py`. **N'écrase pas** le joblib de l'API.

Deux essais, dans l'ordre.

**Avec le corpus déjà en base** (requêtes génériques du matin). Filtrer les articles qui citent un hub : 185 articles → **3** lignes article × hub — trop peu pour un split. Flags grève / ATC + actualité de la veille (J−1) : faisable ; sans BERT le RMSE **empire** (78,91). Avec DistilBERT jour + ces flags : **71,51** — seul run à battre la médiane globale (73,19). Il **perd** encore contre la médiane horaire (67,94). L'heure UTC reste la variable dominante.

**Puis collecte NewsAPI par hub** (`--par-hub`, 10 appels, HTTP 200) pour nourrir le grain hub × jour. 204 lignes article × hub (contre 3). Même modèle : RMSE **77,33** — pire que la météo seule (73,63). Plus d'articles tagués n'améliore pas.

| Variante | RMSE LightGBM | vs médiane globale (73,19) | vs horaire (67,94) |
| --- | --- | --- | --- |
| Météo seule (réf. partie 3) | 73,63 | perd | perd |
| Flags + J−1 + BERT jour | **71,51** | gagne | perd |
| Hub + flags + J−1 + BERT | 77,33 | perd | perd |

**Décision.** Je ne change ni le joblib ni le schéma FastAPI. Le 71,51 ne suffit pas : colonnes nouvelles, l'horaire reste meilleur. BERT reste ce que dit la partie 4 — un score d'entrepôt, pas un argument de performance.

Ces chiffres sont ceux du **02/09**. Le Rendu 3 (campagne du 04/09) est le livrable de référence.
