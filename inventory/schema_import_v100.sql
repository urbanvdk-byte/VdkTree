-- VdkTree v1.0.0: durable preview and import row staging. No imports start automatically.
CREATE TABLE IF NOT EXISTS inventory_import_rows (
    batch_id TEXT NOT NULL REFERENCES inventory_import_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL CHECK (row_number >= 2),
    row_state TEXT NOT NULL CHECK (row_state IN ('ready','invalid','duplicate','imported')),
    external_id TEXT,
    payload_json TEXT,
    errors_json TEXT NOT NULL DEFAULT '[]',
    created_object_id TEXT,
    PRIMARY KEY (batch_id,row_number)
);
CREATE INDEX IF NOT EXISTS inventory_import_rows_state_idx
    ON inventory_import_rows(batch_id,row_state);
CREATE INDEX IF NOT EXISTS inventory_import_batches_user_idx
    ON inventory_import_batches(created_by,started_at DESC);
