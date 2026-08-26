# Rendu 3 — Machine Learning et Évaluation

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)
> **Statut** : Brouillon — sections techniques pré-remplies, sections réflexives à compléter
> **Correspond à** : Phase 3 du projet — Machine Learning et Évaluation

Ce rendu documente la construction du modèle de prédiction de retard à partir du schéma de données mis en place au Rendu 2. Il démontre que le pipeline de données construit dans les Rendus 1 et 2 est réellement exploitable pour un cas d'usage concret, conformément à l'objectif de mise à disposition des données énoncé dès le Rendu 1.

---

## 1. Objectif du modèle

Prédire si un vol subira un **retard significatif** (ex : > 15 minutes, seuil standard utilisé par l'industrie aérienne/DGAC/FAA) à partir des features issues du schéma en étoile (Rendu 2) :
- Features "vol" (compagnie, aéroport origine/destination, heure de départ programmée, distance).
- Features météo (vent, précipitations, visibilité à l'aéroport de départ/arrivée).
- Feature "sentiment actualité" (score BERT agrégé par date/zone).

**Formulation retenue** : [À COMPLÉTER — classification binaire (retard > 15min : oui/non) ou régression (nombre de minutes de retard) ? Le choix a un impact sur la métrique d'évaluation.]

---

## 2. Feature Engineering

- **Variables catégorielles** : compagnie aérienne, aéroport (encodage via target encoding ou one-hot selon cardinalité).
- **Variables temporelles** : heure de la journée, jour de la semaine, caractère férié — dérivées de `dim_date`.
- **Variables météo** : agrégées par créneau horaire (vent, pluie, visibilité) — issues de `dim_weather`.
- **Variable sentiment** : score de sentiment BERT moyen sur les 24h précédant le vol — issue de `dim_news_sentiment`.
- **Fuite de données (data leakage) à éviter** : ne jamais utiliser une information connue seulement après le vol (ex : l'heure d'arrivée réelle) comme feature d'entrée.

---

## 3. Choix du modèle : LightGBM

**Pourquoi LightGBM plutôt qu'une régression logistique ou un réseau de neurones ?**
- **Données tabulaires hétérogènes** (mélange de catégorielles et numériques, valeurs manquantes fréquentes côté météo) : les modèles à base d'arbres de type Gradient Boosting sont reconnus comme état de l'art sur ce type de données, surpassant généralement les réseaux de neurones qui excellent plutôt sur données non-structurées (image, texte, son).
- **Gestion native des valeurs manquantes et des variables catégorielles** (contrairement à la régression logistique qui nécessite un encodage et une imputation manuels complets).
- **Rapidité d'entraînement** (boosting par histogrammes) permettant d'itérer rapidement sur le feature engineering.
- **Interprétabilité** : LightGBM fournit nativement l'importance des features (SHAP compatible), ce qui permet d'expliquer *pourquoi* le modèle prédit un retard (ex : "la feature vent_kmh contribue à 30% de la décision").

---

## 4. Entraînement et validation

- **Découpage train/test** : split temporel (et non aléatoire) — on entraîne sur une période et on teste sur une période postérieure, pour simuler un usage réaliste (prédire l'avenir, pas interpoler le passé).
- **Validation croisée** : [À COMPLÉTER — nombre de folds, stratégie retenue]
- **Gestion du déséquilibre des classes** (si peu de vols réellement en retard significatif) : [À COMPLÉTER — pondération de classe, sur/sous-échantillonnage]

---

## 5. Métriques de performance

| Métrique | Valeur obtenue | Interprétation |
|---|---|---|
| Accuracy | [À COMPLÉTER] | À utiliser avec prudence si classes déséquilibrées |
| Precision / Recall | [À COMPLÉTER] | Recall prioritaire si le coût d'un retard non anticipé > coût d'une fausse alerte |
| F1-score | [À COMPLÉTER] | Compromis precision/recall |
| ROC-AUC | [À COMPLÉTER] | Capacité de discrimination globale du modèle |

**Baseline de comparaison** : [À COMPLÉTER — ex : un modèle "naïf" qui prédit toujours "pas de retard", pour juger si le modèle apporte une réelle valeur ajoutée]

---

## 6. Sauvegarde et réutilisation du modèle

Le modèle entraîné est sérialisé avec `joblib` (`src/models/`) accompagné de :
- La version des features utilisées (schéma d'entrée attendu).
- La date d'entraînement et les métriques associées (traçabilité — bonne pratique MLOps minimale).

Ce modèle est ensuite **consommé** par l'API FastAPI prévue en Phase 4 (`src/api/`), qui expose un endpoint de prédiction — faisant le lien entre ce rendu et le critère officiel "Déploiement" du Rapport final.
