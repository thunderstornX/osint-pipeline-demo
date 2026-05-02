-- Schema for the OSINT pipeline demo.
--
-- One table: records. The content_hash is a SHA-256 hex digest computed
-- over the canonical (sort_keys) JSON of the extracted fields. The
-- UNIQUE constraint enables ON CONFLICT DO NOTHING idempotency.

CREATE TABLE IF NOT EXISTS records (
    id            BIGSERIAL    PRIMARY KEY,
    source        TEXT         NOT NULL,
    content_hash  CHAR(64)     NOT NULL UNIQUE,
    fields        JSONB        NOT NULL,
    raw_excerpt   TEXT         NOT NULL,
    inserted_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS records_source_inserted_at_idx
    ON records (source, inserted_at DESC);

CREATE INDEX IF NOT EXISTS records_fields_gin_idx
    ON records USING GIN (fields);
