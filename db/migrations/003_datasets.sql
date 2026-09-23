CREATE TABLE IF NOT EXISTS datasets (
    id          BIGSERIAL PRIMARY KEY,
    supplier    TEXT        NOT NULL CHECK (supplier IN ('IEK', 'SE')),
    uploaded_by BIGINT      REFERENCES users(id),
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_as_of  DATE        NOT NULL,
    storage_dir TEXT        NOT NULL,
    files       JSONB       NOT NULL,
    is_current  BOOLEAN     NOT NULL DEFAULT false
);

CREATE UNIQUE INDEX IF NOT EXISTS datasets_one_current
    ON datasets (supplier) WHERE is_current;

ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS dataset_ids JSONB NOT NULL DEFAULT '{}'::jsonb;
