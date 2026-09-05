# Rendu 3 — Rapport de Machine Learning

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)  
> **Statut** : Final  

---

## 1. Volonté

Ce rendu documente le premier modèle entraîné sur l'entrepôt PostgreSQL. L'API, Docker et l'orchestration sont dans le **rapport final**.

**Intention** : Avec les trois APIs seulement, la question tenable est : *quelle durée observée ADS-B (`last_seen − first_seen`) attendre, sachant la météo au départ, le hub, l'heure UTC et, le cas échéant, le signal d'actualité du jour ?*

**MVP** : Régression de cette durée, comparée à deux médianes, exportée en `joblib` (`python -m src.models.entrainer`). Un artefact, versionné par Git (fichier gitignoré). Pas de dashboard vols, pas de MLflow, pas de mesure de dérive (volume trop court, pas de serving 24/7).

---

## 2. Données

Le jeu part de `fact_flights`, joint à `dim_date`, `dim_weather` (LEFT JOIN) et `dim_news_sentiment` (date UTC de `first_seen`). Aucun appel d'API pendant l'entraînement.

**Effectif de référence (04/09/2026)**

| Effectif | Valeur |
| --- | --- |
| Vols | **21 054** |
| Observations météo | **120** |
| Jours d'actualité | **27** |
| Jeu modèle (météo origine + durée) | **3 664** (~17 %) |
| Durées > 8 h exclues | 159 |
| Train / test | **2 453 / 1 052** (seuil 02/09 09:11 UTC) |

- Jointure météo : observation la plus proche de `first_seen` (origine) ou `last_seen` (destination), max **3 heures**, sur un hub (Rendu 2). Sinon NULL.
- Entraînement : météo origine + `last_seen` seulement. Biais : hors des dix hubs, ou hors fenêtre ± 3 h d'une capture *current* (6 h de couverture pour 24 h de `/flights/*`).
- Durées > 8 h : trou ADS-B, retirées (seuil 480 min), pas winsorisées.
- Météo destination quasi absente : laissée dans X (LightGBM gère les NaN).
- Hors jeu : horaire programmé ; destination ICAO comme feature ; `retard_minutes` comme cible.

---

## 3. Cible

OpenSky expose `firstSeen` / `lastSeen`, pas un slot. Inventer un horaire (« un CDG–LHR fait 1 h 15 ») serait une donnée synthétique : je ne le fais pas.

`retard_minutes` est un **proxy** déjà calculé par l'ETL (durée − médiane de route, si destination connue et route ≥ 5 vols). Ce n'est pas la cible.

Seuil interne : **50 lignes**. Trois options sans horaire inventé :

| Option | Formulation | Premier diagnostic | Décision |
| --- | --- | --- | --- |
| **A** | Classification : le vol est-il plus long que la médiane de sa route (origine–destination), après filtre météo ? | 0 route ≥ 5 vols | Refusée |
| **B** | Régression de la **durée observée** (`last_seen − first_seen`) | 1 329 lignes | **Retenue** |
| **C** | Régression du proxy `retard_minutes` (durée − médiane de route), seulement si la ligne a aussi une météo | 4 lignes | Refusée alors |

`retenir_cible` (`src/models/jeu.py`) applique ce diagnostic. Au 04/09 le jeu modèle a 3 664 lignes et le diagnostic propose l'**option C** (proxy `retard_minutes`) ; l'entraînement **reste sur l'option B** (durée observée) : le proxy n'est toujours pas un horaire.

Question posée au modèle (option B) : *sachant la météo au départ, le hub, le calendrier et, si elle varie, l'actualité du jour, quelle durée OpenSky ?*

---

## 4. Méthode

**Features** (`src/models/jeu.py`) :

- Hub d'origine (ICAO).
- Jour de semaine, mois, heure UTC dérivée de `first_seen`.
- Météo origine : température, vent, rafale, pluie 1 h, visibilité, humidité ; météo destination (souvent NULL).
- Actualités du jour : `nb_articles_actu`, `proxy_perturbation_actu` (score BERT s'il existe). DistilBERT n'est pas rechargé pendant `entrainer`. Flag `--sans-actu` pour comparer le même split sans ces deux colonnes.

**Fuite évitée.** `last_seen` n'entre pas dans X : il fabrique la cible. Exclus aussi : `duree_minutes`, `retard_minutes`, `first_seen` brut, identifiants, destination ICAO, textes d'articles.

**Split.** Quantile 70 % sur `first_seen` : train strictement avant, test après. Pas de k-fold (un fold mélangerait passé et futur). Au 04/09 : 2 453 / 1 052. Même split avec ou sans actualités.

**Pourquoi LightGBM.** Jeu tabulaire (catégoriel, numérique, beaucoup de NaN). Les arbres gèrent ce mélange sans one-hot ni imputation. Une régression linéaire l'aurait imposé ; un réseau n'a pas d'avantage ici. BERT sert au **texte** des articles, agrégé en un scalaire par jour, pas à remplacer le boosting. Hyperparamètres petits (`max_depth=4`, `num_leaves=15`, `min_child_samples=20`, `n_estimators=200`, `learning_rate=0.05`) pour limiter le surapprentissage.

Deux **baselines** : médiane globale de `duree_minutes` vue en train ; médiane par heure UTC (si l'heure a moins de 5 observations, retour à la globale). Pas d'Accuracy / F1 / AUC : la cible n'est pas une classe.

---

## 5. Observations

Référence : CLI du **04/09/2026 11:29**.

| Estimateur | RMSE | MAE |
| --- | --- | --- |
| LightGBM (actu) | 54,02 | 49,86 |
| Médiane globale | **44,07** | 38,41 |
| Médiane par heure UTC | 47,99 | 42,61 |

- LightGBM **ne bat ni** la médiane globale **ni** l'horaire. Agrandir l'étoile (7 524 → 21 054 vols) n'inverse pas le constat : le jeu modèle ne passe que de 3 034 à 3 664, parce qu'une capture *current* ne recouvre pas les 24 h de `/flights/*`.
- **Heure UTC** domine les importances. La météo origine contribue ; la météo destination et le proxy lexical, presque pas.
- **Actualités / BERT** : écart avec vs sans actu inférieur à 2 min de RMSE (runs 01/09 et 02/09) ; le test du 01/09 n'avait aucun article. Un sentiment mondial par jour ne bat pas une médiane. BERT reste en entrepôt ; je ne le vends pas comme un gain.
- **Open-Meteo** (expérience isolée, pas le joblib) : couverture météo **61,8 %**. Sur l'option B (durée) : LightGBM 65,54 vs médiane 66,02 (MAE moins bonne). Sur l'option C (proxy écart à la route) : 6,57 vs constante 0 à 6,50. Classe > 15 min : 1,3 % de positifs, F1+ = 0.

---

## 6. Limites et alternatives

**Limites**

- Pas un retard : pas d'horaire. OpenSky ne livre pas le slot.
- ~17 % des vols ont une météo *current* utile (120 observations, dix hubs).
- Je n'explique pas une route : dès qu'on exige la météo, l'**option A** (classe « plus long que la médiane de route ») n'a plus assez de vols par couple origine–destination. Plus tard l'**option C** (proxy `retard_minutes`) devient proposable ; je reste sur l'**option B** (durée observée), parce que ce proxy n'est pas un horaire.
- Signal d'actualité plat. LightGBM sous la médiane (54,02 vs 44,07). Un score ancien « gagnant » sur un test de 40 minutes n'est pas le résultat de ce rendu.

**Ce que j'aurais pu faire autrement** (trois chemins, dès le cadrage) :

| Chemin | Quoi changer | Retard  ? | Pipeline Europe + APIs live ? |
| --- | --- | --- | --- |
| **1. CSV BTS / Kaggle** | Remplacer OpenSky | Oui (vols US, souvent classe ≥ 15 min) | **Non** |
| **2. 4e source d'horaires** | Joindre un slot publié | Oui, si la jointure tient | **Oui** — seul chemin « Europe + retard » |
| **3. Changer la question** | Option B (durée observée) ou option C (écart à la route) | Non | **Oui** — livré : option B |


Testé **sans quitter l'option B** : météo d'archive (couverture en hausse ; l'option C reste perdue) ; flags / hub / BERT sur les news (ne bat pas une médiane horaire).

> Pour prédire un retard, il fallait un horaire. Avec OpenSky + OpenWeather + NewsAPI seulement, on estime une **durée** et on teste un **écart à la route**. Ce rendu documente ce pivot, pas un échec de LightGBM.

---

## 7. Reproduction

Si l'entrepôt contient déjà les faits :

```bash
python -m src.models.entrainer
python -m src.models.entrainer --sans-actu --sans-sauvegarde
python -m src.models.experience_proxy_retard --sans-collecte
```

Collecte amont (quota) : `python -m src.processing.collecter_hubs --pause 9` puis `etl`.

NewsAPI et `scorer_sentiment` à part.

Notebooks : `04_modelisation_vol_meteo.ipynb`, `05_sentiment_bert.ipynb`.

Chiffres de référence : CLI du 04/09.

Tests : `python -m pytest -q`.
