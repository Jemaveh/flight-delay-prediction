# Rendu 1 — Rapport de découverte et d'exploration des sources de données

> **Projet** : Airlines Delay Prediction — Titre RNCP 38919 (Data Engineer)  
> **Statut** : Final  
> **Correspond à** : Phase 1 du projet — Ingestion et Data Profiling

---

## 1. Introduction au projet

### 1.1 Contexte

- **Contexte métier / d'insertion du projet** : Après un Master en Biologie obtenu en 2019, j'ai travaillé plusieurs années dans la recherche scientifique en biologie végétale, où je concevais des protocoles expérimentaux et recueillais des données de terrain et de laboratoire. C'est au fil de ces expériences que j'ai identifié la phase du travail que je préférais réellement : le traitement et l'analyse de la donnée, plus que sa seule production. En 2022, en autodidacte, j'ai découvert Python en développant un script capable de reconnaître automatiquement sur des photographies la présence de maladies sur des feuilles de plantes et d'en calculer la surface, dans le cadre de mes expérimentations. Cette expérience a agi comme un déclencheur et m'a convaincue de me reconvertir dans la DATA.
  Je me suis d'abord formée et certifiée comme Data Analyst, un choix cohérent avec mon parcours scientifique initial. J'ai ensuite poursuivi jusqu'au niveau Master avec un parcours Data Engineer, une orientation qui correspondait davantage à mes affinités techniques et pour laquelle je constatais un besoin croissant dans la majorité des entreprises. Ce projet s'inscrit directement dans cette trajectoire : il est conçu comme une pièce de portfolio technique, en complément des missions réalisées durant mon alternance en entreprise, pour démontrer ma capacité à intervenir sur toute la chaîne de valeur — de l’ingestion des données complexes à la mise en production dans un contexte professionnel reconstitué.
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
  4. **Mise à disposition** : Rendre les données exploitables pour un cas d'usage concret (prédiction de retard, voir Rendu 3 — Machine Learning).
- **Niveau d'expertise de l'équipe vis-à-vis de l'ingestion/transformation/stockage** : Une expérience déjà significative en data/analytics précédait ce projet, ce qui a permis de concentrer l'effort d'apprentissage sur les compétences plus spécifiquement liées à l'ingénierie de données : conception de pipelines d'ingestion automatisés, architecture de stockage relationnelle et conteneurisation, moins pratiquées jusqu'ici.
- **Échanges avec des experts techniques ou métiers** : Ce projet a été mené en autonomie complète, sans échange complémentaire avec des experts du secteur aérien ou de la donnée en dehors du cadre d'encadrement standard de la formation.
- **Projet similaire connu** : De nombreux projets de prédiction de retards de vols existent sur Kaggle, notamment à partir des données du Bureau of Transportation Statistics américain. Ces projets ont servi de source d'inspiration pour la définition du périmètre et de l'approche de ce projet.

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
  - OpenSky → variable cible potentielle (retard estimé via écart horaire) + features (compagnie, aéroport origine/destination, altitude/vitesse).
  - OpenWeather → features météo (vent, précipitations, visibilité) sur les aéroports de départ/arrivée.
  - NewsAPI + BERT → score de sentiment agrégé par jour/zone, comme proxy de perturbation (grève, incident).
- **Formats manipulés** : JSON en sortie d'API (toutes les sources), converti en tabulaire (pandas DataFrame / Parquet) pour le stockage intermédiaire.
- **Contraintes et limitations rencontrées** :
  - **Rate limiting** : OpenWeather et NewsAPI limitent le nombre d'appels en offre gratuite (nécessite une stratégie de cache/pagination et un espacement des appels).
  - **Authentification** : OpenSky nécessite un compte (Basic Auth / OAuth2 selon version d'API).
  - **Qualité d'origine** : Les données OpenSky peuvent contenir des valeurs manquantes (aéronefs hors couverture des récepteurs ADS-B) ; les articles NewsAPI ne sont pas garantis pertinents à 100 % (nécessité de filtrage par mots-clés).

---



## 3. Préparation et nettoyage

- **Démarche retenue** : les règles de nettoyage sont identifiées au fil de l'exploration de chaque source, puis appliquées concrètement, à titre de démonstration, directement dans chaque notebook sur les données déjà chargées pour cette exploration (voir le détail avant/après par source ci-dessous). Cette démonstration reste volontairement locale à chaque notebook : un script de nettoyage réutilisable et généralisé (`src/processing/data_cleaning.py`), qui appliquera ces mêmes règles de façon automatisée aux 3 sources ensemble avant leur fusion dans le schéma en étoile, reste prévu pour la Phase 2 (Rendu 2), une fois ce schéma de fusion arrêté. L'écrire dès maintenant, avant de connaître précisément la structure de sortie attendue, obligerait probablement à le retravailler une fois ce schéma défini.
- **Mise à plat déjà appliquée sur les 3 sources** : au-delà du nettoyage à proprement parler, les 3 notebooks appliquent déjà une première transformation sur chaque source — la mise à plat du JSON imbriqué renvoyé par chaque API en DataFrame tabulaire (`pd.json_normalize` pour les champs `main.`*/`wind.*`/`sys.*` d'OpenWeather, reconstruction ligne par ligne pour les états OpenSky et les articles NewsAPI). Ce n'est pas seulement une étape prévue : c'est une transformation déjà réalisée dans les 3 notebooks, préalable au nettoyage lui-même.
- **Contrôles préalables d'intégrité du texte et des unités** : avant de définir la moindre règle de nettoyage, chaque notebook vérifie l'intégrité de ce qui arrive de l'API. Sur les colonnes textuelles des 3 sources, un contrôle d'encodage cherche les séquences de mojibake caractéristiques d'un texte UTF-8 relu en Latin-1 (`Ã©`, `Ã¨`, `Ã` , `Ãª`, `Ã¼`, `Ã§`, `â€`) ainsi que le caractère de remplacement U+FFFD, et affiche des libellés accentués comme preuve visuelle. S'y ajoutent, sur les textes d'articles, la recherche de balises et d'entités HTML résiduelles et la validation de la forme des URL ; et, sur les colonnes numériques, la confrontation des unités documentées aux ordres de grandeur réellement observés (vitesses et altitudes OpenSky, échelle de température et vitesse de vent OpenWeather). Aucun de ces contrôles n'a conduit à une correction : les 3 sources arrivent en UTF-8 correctement décodé et dans les unités annoncées, ce qui évite d'avoir à prévoir une étape de réparation d'encodage ou de conversion d'unités dans le pipeline. Le contrôle reste en place dans les notebooks pour être rejoué sur les captures suivantes.
- **Nettoyage identifié puis appliqué sur OpenSky** (voir `notebooks/01_exploration_opensky.ipynb` pour le détail statistique complet) :
  - Le champ `sensors` est vide dans 100 % des cas observés. **Appliqué** : colonne supprimée.
  - Des vitesses au sol physiquement impossibles ont été observées, toujours associées à des positions très anciennes (donnée périmée, pas une vraie vitesse de croisière). **Appliqué** : filtre combinant l'âge de la position (seuil de 300 secondes) et un seuil de vitesse plausible (400 m/s), qui retire quelques lignes par capture.
  - L'altitude barométrique (`baro_altitude`) est manquante pour la quasi-totalité des avions au sol, contre une infime minorité en vol : traitement différencié requis selon le statut `on_ground`. **Reste prévu en Phase 2** dans le script générique, cette logique conditionnelle étant plus structurante à traiter une fois les 3 sources fusionnées.
  - La colonne `callsign` affiche une complétude de 100 % au sens de pandas alors qu'une petite partie de ses valeurs sont des chaînes réduites à des espaces : le taux brut surestime la disponibilité de l'indicatif de vol. **Reste à généraliser** dans le script de nettoyage : conversion de ces chaînes vides en valeurs manquantes dès le chargement, avant tout calcul de complétude.
  - Certains zéros masquent une non-mesure plutôt qu'une valeur réelle (`velocity == 0` ou `baro_altitude == 0` sur un avion déclaré en vol), et l'écart entre `baro_altitude` et `geo_altitude` dépasse ponctuellement le kilomètre sur un même avion au même instant. **Reste à généraliser** : traiter ces zéros comme non renseignés et ajouter un contrôle de cohérence entre les deux altitudes, le filtre sur l'âge de la position n'écartant qu'une partie de ces cas.
- **Nettoyage identifié puis appliqué sur OpenWeather** (voir `notebooks/02_exploration_openweather.ipynb`) :
  - Les champs `rain.1h` et `wind.gust` sont absents de la réponse pour la majorité des aéroports : absence structurelle (le phénomène n'est renvoyé que lorsqu'il est mesuré). **Appliqué** : remplacement par zéro, les deux colonnes passant de 1/10 à 10/10 valeurs non nulles sur la capture explorée.
  - La visibilité est plafonnée à 10 000 mètres par l'API. **Appliqué à titre défensif** : plafonnement explicite de la colonne à 10 000 m dans le code (aucune valeur de la capture explorée ne dépassait déjà ce seuil).
- **Nettoyage identifié puis appliqué sur NewsAPI** (voir `notebooks/03_exploration_newsapi.ipynb`) :
  - Le champ `content` est systématiquement tronqué à environ 200 caractères sur le plan gratuit (confirmé à 213,9 caractères en moyenne sur 120 articles). **Appliqué** : colonne exclue, la capture explorée passant de 11 à 10 colonnes ; l'analyse de sentiment s'appuiera sur `title` et `description`, fournis en entier.
  - La recherche par mots-clés génériques peut remonter des articles hors sujet (tensions géopolitiques, actualité sans lien avec le trafic aérien commercial) : aucun critère simple et objectif de filtrage n'a été dégagé à ce stade, donc aucun filtre supplémentaire n'a été appliqué. Un raffinement des mots-clés ou un filtrage de pertinence **reste à prévoir en Phase 2**.
  - Le même article peut apparaître sous plusieurs URL distinctes (reprise par un agrégateur, ou même média servi sous deux domaines) : le contrôle de doublons par URL ne détecte pas ces cas, alors qu'une comparaison sur le titre normalisé (minuscules, sans ponctuation) les fait ressortir. **Reste à généraliser** : dédupliquer sur le titre normalisé en plus de l'URL, sans quoi un même événement serait compté plusieurs fois dans le signal d'actualité d'une journée.
  - La répartition par langue des articles est très déséquilibrée (une capture dominée à 80 % par l'anglais) : point à intégrer dans la conception du futur modèle d'analyse de sentiment, sans action de nettoyage associée.
- **Scripts d'ingestion / automatisation** : Voir le module `src/ingestion/` (`opensky_client.py`, `openweather_client.py`, `newsapi_client.py`) — chaque module encapsule les appels API, la gestion des erreurs et la sauvegarde brute horodatée dans `data/raw/`.
- **Transformations et enrichissements restant prévus en Phase 2** : le script de nettoyage réutilisable et généralisé (`src/processing/data_cleaning.py`), qui généralisera aux 3 sources combinées les règles démontrées ci-dessus (et ajoutera le traitement conditionnel de l'altitude selon `on_ground`), ainsi que l'analyse de sentiment (`src/processing/sentiment_analysis.py`), restent prévus pour la Phase 2, une fois le schéma de fusion arrêté.

---



## 4. Visualisations et analyses descriptives (Data Profiling)

> **Note méthodologique** : ce Data Profiling porte sur la **qualité de l'ingestion** (distributions, complétude, corrélations).

- **Visualisations techniques produites** : un rapport `ydata-profiling` par source, généré directement depuis chaque notebook d'exploration et sauvegardé dans `data/profiling_reports/` (`opensky_profiling_report.html`, `openweather_profiling_report.html`, `newsapi_profiling_report.html`), couvrant systématiquement pour chaque colonne les distributions, le taux de complétude, les valeurs distinctes et les corrélations. En complément, chaque notebook contient des visualisations ciblées répondant à des questions précises : taux de complétude par colonne, nuage de points géographique et répartition par pays d'origine pour OpenSky ; comparaison de la température et du vent par aéroport pour OpenWeather ; répartition des articles par langue de requête pour NewsAPI.
- **Familles de contrôles couvertes par notebook** : complétude et valeurs manquantes, bornes physiques et valeurs aberrantes, doublons (sur identifiant, sur URL, sur titre normalisé), symboles et encodage des caractères, cohérence des unités, fraîcheur et horodatages, cohérence entre colonnes corrélées. Chaque famille est traitée par une cellule dédiée dans le notebook de la source concernée, suivie de son interprétation.
- **Symboles et encodage des caractères** : contrôlé explicitement sur les colonnes textuelles des 3 sources, par recherche des séquences de mojibake typiques d'un texte UTF-8 relu en Latin-1 et du caractère de remplacement U+FFFD. Le contrôle est complété par l'affichage d'échantillons accentués servant de preuve visuelle : titres dans les différentes langues de requête pour NewsAPI, libellés météo francophones pour OpenWeather, jeu de caractères effectivement rencontré pour les indicatifs OpenSky. Aucun défaut de décodage relevé sur les captures explorées ; OpenSky se limite à l'ASCII (indicatifs en majuscules et chiffres, noms de pays en anglais), tandis qu'OpenWeather et NewsAPI renvoient des accents et une ponctuation typographique correctement formés.
- **Incohérences ou anomalies détectées** :
  - OpenSky : le champ `sensors` est vide à 100 %. Quelques altitudes barométriques légèrement négatives reviennent d'une capture à l'autre (sol sous le niveau de la mer, ou artefact ADS-B). Des vitesses au sol extrêmes apparaissent également, toujours associées à une position très ancienne : il s'agit d'une donnée périmée, pas d'une vraie vitesse de croisière. Les volumes et les extrêmes varient d'une capture à l'autre, mais les constats de qualité (unités, encodage, types d'anomalies) restent les mêmes. D'autres incohérences capteur ont été observées : un écart de plusieurs kilomètres peut exister entre `baro_altitude` et `geo_altitude` sur un même avion au même instant — à traiter comme une incohérence capteur, pas comme une vérité terrain ; des cas de `velocity == 0` alors que `on_ground == False` (vitesse sol nulle en vol) ; des zéros ponctuels sur les altitudes en vol, qui masquent probablement une non-mesure. Aucun doublon sur `icao24` en revanche : chaque capture est bien un instantané, avec une ligne par avion.
  - OpenWeather : aucune valeur hors bornes physiques détectée sur les cinq variables vérifiées (température, humidité, pression, vent, visibilité) ; deux champs (`rain.1h`, `wind.gust`) partiellement absents mais de façon structurelle, pas aléatoire. L'encodage français est conforme, de même que les unités (°C, m/s) demandées via `units=metric`, vérifiées sur les ordres de grandeur observés et pas seulement sur le paramètre d'appel. La cohérence entre `main.temp`, `main.feels_like` et l'encadrement `main.temp_min`/`main.temp_max` est vérifiée sans anomalie, avec un point de vigilance : l'encadrement peut être dégénéré (les trois valeurs égales) sur certains aéroports, ce qui le rend inexploitable comme feature à lui seul.
  - NewsAPI : aucun doublon d'URL entre les cinq requêtes mots-clés/langue sur la capture explorée, mais des titres identiques sous des URLs différentes (même article republicé, ou slug variant) — la déduplication future ne pourra pas se limiter à l'URL. Aucune balise ni entité HTML résiduelle dans les titres et descriptions, et aucune URL mal formée : le texte arrive déjà nettoyé côté fournisseur. Le champ `publishedAt` est bien en UTC ; le tampon de collecte était en heure locale naïve (bug corrigé dans le module d'ingestion, biais d'environ 2 h sur le calcul d'âge, impact limité au vu d'un âge moyen d'environ 6,8 jours). Une pollution par mots-clés a également été identifiée (des articles sur des tensions géopolitiques remontés par le mot-clé anglais générique "airspace closure", sans rapport avec des retards de vols commerciaux) et le champ `content` est systématiquement tronqué par l'API.
- **Conclusions pour la future organisation et modélisation des données** :
  - La granularité retenue diffère par nature de source : par avion et par instant pour OpenSky, par aéroport et par capture pour OpenWeather, par article pour NewsAPI — la jointure entre les trois sources se fera au niveau du couple (aéroport, date/heure) dans le schéma en étoile (Rendu 2), après agrégation temporelle de NewsAPI (ex : score de sentiment moyen par jour) plutôt qu'un rattachement article par article à un vol précis.
  - Colonnes déjà exclues lors du nettoyage démontré dans les notebooks : `sensors` (OpenSky, vide à 100 %), le champ `weather` brut d'OpenWeather (remplacé par `description_ciel`), et `content` de NewsAPI (tronqué, non exploitable comme texte). Le script générique de la Phase 2 reprendra ces mêmes exclusions de façon automatisée sur l'ensemble des captures.
  - La répartition par langue très déséquilibrée observée sur NewsAPI (dominée par l'anglais) devra être prise en compte lors du choix du modèle BERT d'analyse de sentiment (Rendu 3), sans que ce choix soit arrêté à ce stade du projet.

---



## 5. Modalités d'évaluation (rappel officiel)

> *"Mise en situation professionnelle reconstituée : à partir de sources de données réelles (API, web scraping, bases existantes…), le/la candidat(e) devra identifier, collecter et préparer les données pour qu'elles soient exploitables dans un pipeline de données."*

Ce rendu démontre la capacité à identifier des sources pertinentes, à les collecter de façon automatisée et à préparer leur exploitation future (Rendu 2).