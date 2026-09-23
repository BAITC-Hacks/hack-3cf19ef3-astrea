CREATE TABLE IF NOT EXISTS purchase_orders (
    id              BIGSERIAL PRIMARY KEY,
    supplier        TEXT        NOT NULL CHECK (supplier IN ('IEK', 'SE')),
    approved_by     TEXT        NOT NULL,
    approved_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_as_of      DATE        NOT NULL,
    forecast_method TEXT        NOT NULL,
    params          JSONB       NOT NULL,
    line_count      INTEGER     NOT NULL,
    total_qty       INTEGER     NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    order_id         BIGINT  NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    sku_code         TEXT    NOT NULL,
    article          TEXT,
    name             TEXT,
    unit             TEXT,
    category         TEXT,
    moq              INTEGER NOT NULL,
    recommended_qty  INTEGER NOT NULL,
    approved_qty     INTEGER NOT NULL CHECK (approved_qty >= 0),
    urgency          TEXT,
    stock_unknown    BOOLEAN NOT NULL,
    explanation      TEXT    NOT NULL,
    comment          TEXT,
    PRIMARY KEY (order_id, sku_code)
);
