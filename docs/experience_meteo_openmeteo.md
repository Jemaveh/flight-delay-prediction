# Expérience Open-Meteo + proxy de retard — questions, protocole, résultats

 
> **Code** : `src/ingestion/openmeteo_client.py`, `src/processing/meteo_archive.py`, `src/models/experience_proxy_retard.py`.  
> **CLI** : `python -m src.models.experience_proxy_retard` (collecte) puis `--sans-collecte` (rejeu).  
> **N'écrase pas** `models/modele_vol_meteo.joblib`. OpenWeather *Current* reste la source du pipeline prod.

Ce fichier documente le protocole, les chiffres et la décision.

---

## 1. Questions avant le test

1. Est-ce que le goulot « 22 % des vols ont une météo » **empêchait** LightGBM de battre une médiane ? Si on colle une météo **horaire** à (presque) tous les vols, est-ce que ça change ?
2. Sans horaire programmé, le proxy déjà en ETL (`durée − médiane de route`) est-il un **retard entraînable** une fois la météo disponible ?
3. Une classe binaire **> 15 min** (seuil BTS / Kaggle `DEP_DEL15`) a-t-elle un sens sur ce proxy ?

---

## 2. Ce que ce test n'est pas

| Idée | Pourquoi on ne l'a pas fait ici |
| --- | --- |
| Télécharger le **BTS américain** (Kaggle `usdot/flight-delays`) | Ce n'est **pas une API live**. Ce sont des CSV mensuels US (`CRS_DEP_TIME`, `DEP_DELAY`). Autre pays, autre cible, autre projet. |
| Remplacer OpenSky par Aviationstack / AeroAPI | Plan gratuit minuscule ou payant ; ça casse le pipeline déjà construit. |
| Changer le joblib / l'API FastAPI | Expérience isolée. Même si le RMSE bouge un peu, le produit reste une **durée ADS-B**. |

BTS répond à « retard vs horaire » uniquement sur un jeu US historique. Ce n'est pas une API comparable à OpenSky.

---

## 3. Protocole

1. Lire `fact_flights` (13 822 vols), **sans** exiger `weather_origin_id` OpenWeather.
2. Open-Meteo **Historical Forecast**, 10 hubs, fenêtre min/max des `first_seen`, **sans clé**. 10 HTTP. JSON `data/raw/openmeteo_20260902_131554.json` (216 pas horaires / hub). Repli ERA5 prévu dans le client (retard ~5 jours : aurait manqué le test du 01–02/09).
3. Jointure : ICAO + heure UTC de `first_seen` (origine) / `last_seen` (destination).
4. Plafond 8 h, split temporel 70/30.
5. **A — durée** : LightGBM vs médiane globale vs médiane horaire (même question que le Rendu 3, jeu plus large).
6. **B — proxy** : médiane de route calculée **sur le train seul** (pas `retard_minutes` de l'ETL, qui voit le test). OD avec < 5 vols en train écartées.
7. **C — classe** : `retard_sans_fuite > 15` min vs classe majoritaire.

---

## 4. Chiffres (02/09/2026 13:15)

Jointure origine : **60,9 %** des 13 822 (les départs hors des 10 hubs n'ont pas de série). Après plafond 8 h : **13 034** vols, **8 057** avec météo origine (**61,8 %**), contre **3 034 / 22 %** avec OpenWeather *current*.

Split durée : train **9 124** jusqu'au 01/09 13:41 UTC, test **3 910** depuis 01/09 13:41 UTC. Météo origine en test : **64 %**.

### A. Régression de la durée (tous les vols plafonnés)

| Estimateur | RMSE | MAE |
| --- | --- | --- |
| LightGBM + Open-Meteo | **65,54** | 50,77 |
| Médiane globale | 66,02 | **44,69** |
| Médiane par heure UTC | 69,30 | 46,07 |

LightGBM **gagne 0,48 RMSE** sur la médiane globale et bat l'horaire. Il **perd franchement en MAE** (50,8 vs 44,7) : mieux sur les gros écarts, moins bon sur l'erreur typique. Importances (splits) : `heure_utc` 601, `hub_origine` 272, puis visibilité / température dest et origine. L'heure domine encore.

Sur le jeu *current* (3 034 lignes), l'horaire gagnait (67,94 vs 73,44). Ici l'horaire **perd** : le test (après-midi du 01/09) n'a plus le même mélange de routes que le train, une médiane par heure se transfère mal. Ce n'est pas « Open-Meteo a débloqué la durée ». C'est un écart RMSE **inférieur à une minute**, avec une MAE moins bonne.

### B. Proxy OD sans fuite (3112 train / 1431 test)

| Estimateur | RMSE | MAE |
| --- | --- | --- |
| LightGBM + Open-Meteo | 6,57 | 4,13 |
| Médiane du proxy (train) | 6,50 | 4,03 |
| Médiane horaire du proxy | **6,47** | **3,99** |
| Constante 0 (= « la route est typique ») | 6,50 | 4,03 |

LightGBM **perd** contre les trois baselines. Une fois la durée typique de la route retirée, il reste ~**6,5 min** d'écart-type. La météo n'explique pas ce résidu.

### C. Classe > 15 min (seuil Kaggle)

| | Train | Test |
| --- | --- | --- |
| Taux « en retard » | 3,4 % | **1,3 %** |

Accuracy modèle **=** baseline (toujours « à l'heure ») : **0,987**. F1 de la classe positive : **0**. AUC : **0,69** (un peu de rang, zéro détection).

Un vol OpenSky est presque toujours **proche de la médiane de sa route**. Le « retard 15 min » BTS est un écart à l'**horaire**, pas à la durée habituelle : d'où ~20 % de positifs aux US, vs 1 % ici.

---

## 5. Décision

**Pourquoi je ne le garde pas.** La couverture passe à ~62 % (contre ~22 % avec OpenWeather *Current*), mais le modèle ne devient pas utile : sur la durée, +0,5 min de RMSE et pire en MAE ; sur le proxy (écart à la route), LightGBM perd ; une classe « > 15 min » n'a presque aucun positif. **Donc le trou n'était pas la météo. C'est l'absence d'horaire**.

OpenWeather *Current* reste la source du pipeline. Je ne touche pas au joblib ni à l'API.

Ces chiffres sont ceux du **02/09**. Le Rendu 3 (campagne du 04/09) est le livrable de référence.
