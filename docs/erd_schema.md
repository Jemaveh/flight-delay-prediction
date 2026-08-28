# ERD — schéma en étoile (Airlines Delay Prediction)

Source de vérité : `src/database/schema.sql` (tables réellement créées). 

**Grain de** `fact_flights` : un vol observé OpenSky `/flights/departure` ou `/flights/arrival` (`icao24` + `first_seen` + origine). Ce n'est **pas** un snapshot `/states/all`.

`dim_news_sentiment` se joint aux faits **via** `date_id` : il n'existe pas de FK `sentiment_id` sur `fact_flights`. `ingestion_log` est un journal technique, hors étoile.

## Fichiers


| Fichier                | Usage                                                         |
| ---------------------- | ------------------------------------------------------------- |
| `docs/erd_schema.dbml` | Source dbdiagram.io (PNG de soutenance)                       |
| `docs/erd_schema.md`   | Ce fichier : Mermaid + mode d'emploi                          |
| `docs/erd_schema.svg`  | Diagramme vectoriel versionnable, ouvrable dans un navigateur |


## Exporter un PNG ([dbdiagram.io](http://dbdiagram.io))

1. Ouvrir [https://dbdiagram.io](https://dbdiagram.io) (compte gratuit suffisant).
2. Nouveau diagramme, coller le contenu de `docs/erd_schema.dbml` (recharger si un ancien collage est encore ouvert).
3. Export → PNG (ou PDF). Enregistrer sous `docs/erd_schema.png`.

Opérateurs DBML 9+ (doc [relationships](https://dbml.dbdiagram.io/docs/#relationships)) : `>` many-to-one (FK NOT NULL), `>?` many-to-optional-one (FK nullable), `-` one-to-one (`date_id` UNIQUE sur `dim_news_sentiment`). Une seule `Ref` par couple, pas de `ref:` inline. Les NULL dest / météo / aéroport hors hubs restent volontaires dans Postgres ; ce n'est pas un défaut du schéma.

GitHub, GitLab et la plupart des visionneuses Markdown rendent aussi le bloc Mermaid ci-dessous.

```mermaid
erDiagram
    dim_date ||--o{ fact_flights : date_id
    dim_airport |o--o{ fact_flights : airport_origin_id
    dim_airport |o--o{ fact_flights : airport_dest_id
    dim_weather |o--o{ fact_flights : weather_origin_id
    dim_weather |o--o{ fact_flights : weather_dest_id
    dim_airport ||--o{ dim_weather : airport_id
    dim_date ||--o{ dim_weather : date_id
    dim_date ||--o| dim_news_sentiment : date_id

    dim_date {
        INTEGER date_id PK "YYYYMMDD"
        DATE date UK
        SMALLINT jour_semaine "ISO 1=lundi"
        SMALLINT mois
        BOOLEAN est_ferie
    }

    dim_airport {
        SERIAL airport_id PK
        CHAR_3 code_iata
        CHAR_4 code_icao UK
        TEXT ville
        TEXT pays
        DOUBLE latitude
        DOUBLE longitude
    }

    dim_weather {
        SERIAL weather_id PK
        INTEGER airport_id FK
        INTEGER date_id FK
        TIMESTAMPTZ horodatage_observation
        DOUBLE temperature_celsius
        DOUBLE feels_like_celsius
        SMALLINT humidity
        INTEGER pressure
        DOUBLE wind_speed
        DOUBLE wind_gust
        DOUBLE rain_1h
        INTEGER visibility
        TEXT description_ciel
    }

    dim_news_sentiment {
        SERIAL sentiment_id PK
        INTEGER date_id FK "UNIQUE"
        INTEGER nb_articles
        TEXT mots_cles
        DOUBLE score_sentiment "NULL tant que BERT n a pas tourne"
    }

    fact_flights {
        SERIAL flight_id PK
        VARCHAR_12 icao24
        VARCHAR_16 callsign
        TIMESTAMPTZ first_seen
        TIMESTAMPTZ last_seen
        VARCHAR_4 est_departure_airport
        VARCHAR_4 est_arrival_airport
        INTEGER date_id FK
        INTEGER airport_origin_id FK
        INTEGER airport_dest_id FK
        INTEGER weather_origin_id FK
        INTEGER weather_dest_id FK
        DOUBLE retard_minutes "NULL si proxy non calculable"
    }

    ingestion_log {
        SERIAL log_id PK
        TEXT source
        TEXT fichier_source
        TIMESTAMPTZ horodatage_debut
        TIMESTAMPTZ horodatage_fin
        INTEGER lignes_lues
        INTEGER lignes_rejetees
        INTEGER lignes_inserees
    }
```



