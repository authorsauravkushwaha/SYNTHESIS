-- SYNTHESIS — reference PostgreSQL/PostGIS schema (section 29–31 of the vision).
-- The MVP runs in-memory; this schema is the production target the API maps onto.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE source (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,              -- satellite | ais | sensor | official | news | weather_model | ...
    historical_reliability NUMERIC(3,2) NOT NULL CHECK (historical_reliability BETWEEN 0 AND 1),
    known_limitations TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE entity (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    entity_type     TEXT NOT NULL,              -- port | road | power_grid | industrial_zone | waterway | ...
    domain          TEXT NOT NULL,              -- weather | maritime | energy | infrastructure | trade | economy
    geom            GEOMETRY(Point, 4326)
);

CREATE TABLE evidence (
    id              TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES source(id),
    statement       TEXT NOT NULL,
    classification  TEXT NOT NULL,              -- DIRECT OBSERVATION | DERIVED FACT | INFERENCE | HYPOTHESIS | FORECAST | SPECULATION
    domain          TEXT NOT NULL,
    reliability     NUMERIC(3,2) NOT NULL,
    independence    TEXT NOT NULL DEFAULT 'independent',
    observed_at     TIMESTAMPTZ NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    geom            GEOMETRY(Point, 4326),
    -- tamper-evident chain: hash = sha256(prev_hash || '|' || canonical_payload)
    chain_seq       BIGINT UNIQUE NOT NULL,
    prev_hash       CHAR(64) NOT NULL,
    content_hash    CHAR(64) NOT NULL,
    version         INT NOT NULL DEFAULT 1      -- new versions append; history is never rewritten
);

CREATE TABLE event (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    domain          TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    status          TEXT NOT NULL DEFAULT 'active',
    summary         TEXT,
    location_name   TEXT,
    geom            GEOMETRY(Point, 4326),
    detected_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE event_evidence (
    event_id        TEXT REFERENCES event(id),
    evidence_id     TEXT REFERENCES evidence(id),
    PRIMARY KEY (event_id, evidence_id)
);

CREATE TABLE hypothesis (
    id              TEXT PRIMARY KEY,
    event_id        TEXT NOT NULL REFERENCES event(id),
    label           TEXT NOT NULL,              -- A | B | C ...
    claim           TEXT NOT NULL,
    mechanism       JSONB NOT NULL DEFAULT '[]',
    assumptions     JSONB NOT NULL DEFAULT '[]',
    falsifiers      JSONB NOT NULL DEFAULT '[]',
    confidence      NUMERIC(3,2) NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE hypothesis_evidence (
    hypothesis_id   TEXT REFERENCES hypothesis(id),
    evidence_id     TEXT REFERENCES evidence(id),
    role            TEXT NOT NULL CHECK (role IN ('supporting','contradicting')),
    PRIMARY KEY (hypothesis_id, evidence_id, role)
);

-- causal edges of the temporal world graph (impact cones)
CREATE TABLE relationship (
    id              BIGSERIAL PRIMARY KEY,
    event_id        TEXT REFERENCES event(id),
    source_node     TEXT NOT NULL,
    target_node     TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN
                    ('observed','strongly_supported','plausible','uncertain','contradicted','unknown')),
    mechanism       TEXT NOT NULL,
    lag_window      TEXT,
    confidence      NUMERIC(3,2) NOT NULL,
    valid_from      TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to        TIMESTAMPTZ                 -- temporal validity, never deleted
);

CREATE TABLE watchpoint (
    id              TEXT PRIMARY KEY,
    hypothesis_id   TEXT NOT NULL REFERENCES hypothesis(id),
    label           TEXT NOT NULL,
    signal          TEXT NOT NULL,
    direction       TEXT NOT NULL
);

CREATE TABLE forecast (
    id              TEXT PRIMARY KEY,
    hypothesis_id   TEXT NOT NULL REFERENCES hypothesis(id),
    prediction      TEXT NOT NULL,
    probability     NUMERIC(3,2) NOT NULL,
    forecast_window TEXT NOT NULL,
    expected_indicators JSONB NOT NULL DEFAULT '[]',
    model_version   TEXT NOT NULL,              -- forecasts stay pinned to their model version
    created_at      TIMESTAMPTZ NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE outcome (
    forecast_id     TEXT PRIMARY KEY REFERENCES forecast(id),
    observed        TEXT NOT NULL,
    verdict         TEXT NOT NULL,              -- CORRECT DIRECTION | PARTIALLY CORRECT | FAILED
    brier           NUMERIC(6,4) NOT NULL,
    observed_at     TIMESTAMPTZ NOT NULL,
    calibration_note TEXT
);

CREATE TABLE contradiction (
    id              TEXT PRIMARY KEY,
    event_id        TEXT REFERENCES event(id),
    topic           TEXT NOT NULL,
    claim_a         JSONB NOT NULL,
    claim_b         JSONB NOT NULL,
    independent_observation TEXT,
    status          TEXT NOT NULL DEFAULT 'UNRESOLVED'
                    CHECK (status IN ('UNRESOLVED','PARTIALLY_RESOLVED','RESOLVED')),
    resolution_note TEXT
);

CREATE TABLE model_registry (
    model_id        TEXT NOT NULL,
    version         TEXT NOT NULL,
    training_lineage TEXT,
    eval_metrics    JSONB,
    security_review TEXT,
    released_at     TIMESTAMPTZ,
    known_limitations TEXT,
    approved_use_cases JSONB,
    rollback_version TEXT,
    PRIMARY KEY (model_id, version)
);

CREATE TABLE audit_event (
    id              BIGSERIAL PRIMARY KEY,
    actor           TEXT NOT NULL,              -- user id or agent id
    action          TEXT NOT NULL,
    object_type     TEXT NOT NULL,
    object_id       TEXT,
    at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    detail          JSONB
);

CREATE INDEX evidence_observed_idx ON evidence (observed_at DESC);
CREATE INDEX evidence_geom_idx     ON evidence USING GIST (geom);
CREATE INDEX event_geom_idx        ON event USING GIST (geom);
CREATE INDEX relationship_evt_idx  ON relationship (event_id);
CREATE INDEX audit_at_idx          ON audit_event (at DESC);
