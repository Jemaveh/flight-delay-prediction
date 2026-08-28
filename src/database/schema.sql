-- Schéma en étoile du projet Airlines Delay Prediction
-- Horodatages stockés en TIMESTAMPTZ (UTC)

CREATE TABLE IF NOT EXISTS dim_date (
    date_id INTEGER PRIMARY KEY,              -- YYYYMMDD
    date DATE NOT NULL UNIQUE,
    jour_semaine SMALLINT NOT NULL,           -- ISO : 1 = lundi -7 = dimanche
    mois SMALLINT NOT NULL,
    est_ferie BOOLEAN
);

CREATE TABLE IF NOT EXISTS dim_airport (
    airport_id SERIAL PRIMARY KEY,
    code_iata CHAR(3) NOT NULL,
    code_icao CHAR(4) NOT NULL,
    ville TEXT,
    pays TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    CONSTRAINT uq_dim_airport_icao UNIQUE (code_icao)
);

CREATE TABLE IF NOT EXISTS dim_weather (
    weather_id SERIAL PRIMARY KEY,
    airport_id INTEGER NOT NULL REFERENCES dim_airport (airport_id),
    date_id INTEGER NOT NULL REFERENCES dim_date (date_id),
    horodatage_observation TIMESTAMPTZ NOT NULL,
    temperature_celsius DOUBLE PRECISION,
    feels_like_celsius DOUBLE PRECISION,
    humidity SMALLINT,
    pressure INTEGER,
    wind_speed DOUBLE PRECISION,
    wind_gust DOUBLE PRECISION,
    rain_1h DOUBLE PRECISION,
    visibility INTEGER,
    description_ciel TEXT,
    CONSTRAINT uq_dim_weather_observation UNIQUE (airport_id, horodatage_observation)
);

CREATE TABLE IF NOT EXISTS dim_news_sentiment (
    sentiment_id SERIAL PRIMARY KEY,
    date_id INTEGER NOT NULL REFERENCES dim_date (date_id),
    nb_articles INTEGER NOT NULL,
    mots_cles TEXT,
    score_sentiment DOUBLE PRECISION,         -- NULL tant que le score n'est pas calculé
    CONSTRAINT uq_dim_news_sentiment_date UNIQUE (date_id)
);

CREATE TABLE IF NOT EXISTS fact_flights (
    flight_id SERIAL PRIMARY KEY,
    icao24 VARCHAR(12) NOT NULL,
    callsign VARCHAR(16),
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ,
    est_departure_airport VARCHAR(4),
    est_arrival_airport VARCHAR(4),
    date_id INTEGER NOT NULL REFERENCES dim_date (date_id),
    airport_origin_id INTEGER REFERENCES dim_airport (airport_id),
    airport_dest_id INTEGER REFERENCES dim_airport (airport_id),
    weather_origin_id INTEGER REFERENCES dim_weather (weather_id),
    weather_dest_id INTEGER REFERENCES dim_weather (weather_id),
    retard_minutes DOUBLE PRECISION,          -- NULL si le proxy n'est pas calculable
    CONSTRAINT chk_fact_flights_chronologie CHECK (
        last_seen IS NULL OR last_seen >= first_seen
    )
);

-- Identité d'un vol observé (COALESCE pour les origines encore inconnues)
CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_flights_identite
    ON fact_flights (icao24, first_seen, (COALESCE(est_departure_airport, '')));

CREATE TABLE IF NOT EXISTS ingestion_log (
    log_id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    fichier_source TEXT,
    horodatage_debut TIMESTAMPTZ NOT NULL,
    horodatage_fin TIMESTAMPTZ,
    lignes_lues INTEGER,
    lignes_rejetees INTEGER,
    lignes_inserees INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fact_flights_date_id
    ON fact_flights (date_id);
CREATE INDEX IF NOT EXISTS idx_fact_flights_airport_origin_id
    ON fact_flights (airport_origin_id);
CREATE INDEX IF NOT EXISTS idx_fact_flights_airport_dest_id
    ON fact_flights (airport_dest_id);
CREATE INDEX IF NOT EXISTS idx_fact_flights_weather_origin_id
    ON fact_flights (weather_origin_id);
CREATE INDEX IF NOT EXISTS idx_fact_flights_weather_dest_id
    ON fact_flights (weather_dest_id);

CREATE INDEX IF NOT EXISTS idx_dim_weather_airport_id
    ON dim_weather (airport_id);
CREATE INDEX IF NOT EXISTS idx_dim_weather_date_id
    ON dim_weather (date_id);

CREATE INDEX IF NOT EXISTS idx_dim_news_sentiment_date_id
    ON dim_news_sentiment (date_id);
