-- VdkTree v0.7.0 — PostgreSQL schema for shared objects, notes, photos, audit and future imports.
-- This script is idempotent and operates on the DATABASE_URL PostgreSQL database.

CREATE TABLE IF NOT EXISTS inventory_objects (
    id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL CHECK (object_type IN
        ('tree','shrub','lawn','flowerbed','natural_community')),
    geometry_type TEXT NOT NULL CHECK (geometry_type IN ('Point','Polygon')),
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    geometry_geojson TEXT,
    confirmation_status TEXT CHECK (confirmation_status IN ('proposed','confirmed')),
    created_by TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    observed_on TEXT,
    confirmed_by TEXT,
    confirmed_at INTEGER,
    source_type TEXT NOT NULL DEFAULT 'citizen'
        CHECK (source_type IN ('citizen','moderator','admin','bulk_import')),
    import_batch_id TEXT,
    import_source TEXT,
    external_id TEXT,
    inventory_number TEXT UNIQUE,
    CHECK (
       (object_type IN ('tree','shrub') AND geometry_type='Point'
        AND lat IS NOT NULL AND lon IS NOT NULL
        AND lat BETWEEN 42 AND 44 AND lon BETWEEN 130 AND 134
        AND geometry_geojson IS NULL AND confirmation_status IS NOT NULL)
       OR
       (object_type IN ('lawn','flowerbed','natural_community') AND geometry_type='Polygon'
        AND lat IS NULL AND lon IS NULL AND geometry_geojson IS NOT NULL
        AND confirmation_status IS NULL)
    ),
    CHECK (
       (confirmation_status='confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
       OR (confirmation_status='proposed' AND confirmed_by IS NULL AND confirmed_at IS NULL)
       OR confirmation_status IS NULL
    ),
    UNIQUE (import_source, external_id)
);
CREATE INDEX IF NOT EXISTS inventory_object_geo_idx ON inventory_objects(lat,lon);
CREATE INDEX IF NOT EXISTS inventory_object_type_state_idx ON inventory_objects(object_type,confirmation_status);
CREATE INDEX IF NOT EXISTS inventory_object_creator_idx ON inventory_objects(created_by, created_at);
CREATE INDEX IF NOT EXISTS inventory_object_created_idx ON inventory_objects(created_at);

-- Citizen-observable data. All fields are optional except linked object ID.
-- A layperson's visible_condition is NOT a 6-grade technical sanitary diagnosis.
CREATE TABLE IF NOT EXISTS inventory_basic (
    object_id TEXT PRIMARY KEY REFERENCES inventory_objects(id) ON DELETE CASCADE,
    species_common TEXT,
    approx_height_band TEXT CHECK (approx_height_band IN
        ('unknown','under_2m','2_5m','5_10m','over_10m')),
    approx_diameter_cm DOUBLE PRECISION CHECK (approx_diameter_cm IS NULL OR
        (approx_diameter_cm > 0 AND approx_diameter_cm <= 1000)),
    visible_condition TEXT CHECK (visible_condition IN
        ('unknown','looks_healthy','damaged','dry')),
    visible_damage_json TEXT,
    comment TEXT NOT NULL DEFAULT '' CHECK (length(comment) <= 1000)
);

-- Professional data from regulation §5, appendix 2, table 2.4.
CREATE TABLE IF NOT EXISTS inventory_expert (
    object_id TEXT PRIMARY KEY REFERENCES inventory_objects(id) ON DELETE CASCADE,
    plot_number TEXT,
    biogroup_number TEXT,
    plant_number TEXT,
    planting_type TEXT,
    life_form TEXT,
    botanical_species TEXT,
    quantity INTEGER CHECK (quantity IS NULL OR quantity > 0),
    trunk_diameter_130_cm DOUBLE PRECISION CHECK (trunk_diameter_130_cm IS NULL OR trunk_diameter_130_cm > 0),
    height_m DOUBLE PRECISION CHECK (height_m IS NULL OR height_m > 0),
    approx_age_years INTEGER CHECK (approx_age_years IS NULL OR approx_age_years >= 0),
    sanitary_condition_score INTEGER CHECK (sanitary_condition_score BETWEEN 1 AND 6),
    dieback_category TEXT,
    defects TEXT,
    care_recommendations TEXT,
    slope_protection INTEGER CHECK (slope_protection IN (0,1)),
    trunk_lean_degrees DOUBLE PRECISION CHECK (trunk_lean_degrees BETWEEN 0 AND 90),
    crown_asymmetry TEXT,
    endemic_or_relict INTEGER CHECK (endemic_or_relict IN (0,1))
);

-- Areas from appendix 2 tables 2.3 / 2.5, and regulation's natural communities.
-- A GeoJSON polygon must be validated (and later area computed) by the server.
CREATE TABLE IF NOT EXISTS inventory_area_details (
    object_id TEXT PRIMARY KEY REFERENCES inventory_objects(id) ON DELETE CASCADE,
    area_m2 DOUBLE PRECISION CHECK (area_m2 IS NULL OR area_m2 > 0),
    lawn_type TEXT CHECK (lawn_type IN ('ordinary','meadow','parterre','slope','inert')),
    area_condition TEXT CHECK (area_condition IN ('good','satisfactory','poor')),
    annual_m2 DOUBLE PRECISION CHECK (annual_m2 IS NULL OR annual_m2 >= 0),
    perennial_m2 DOUBLE PRECISION CHECK (perennial_m2 IS NULL OR perennial_m2 >= 0),
    bulbous_m2 DOUBLE PRECISION CHECK (bulbous_m2 IS NULL OR bulbous_m2 >= 0),
    roses_m2 DOUBLE PRECISION CHECK (roses_m2 IS NULL OR roses_m2 >= 0),
    mixed_m2 DOUBLE PRECISION CHECK (mixed_m2 IS NULL OR mixed_m2 >= 0),
    community_type TEXT CHECK (community_type IN ('forest','meadow','waterside'))
);

-- Independent user notes. One object can have many open clarification requests.
-- The badge is DERIVED from EXISTS(status='open'), never a third main status.
CREATE TABLE IF NOT EXISTS inventory_clarifications (
    id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES inventory_objects(id) ON DELETE CASCADE,
    author_id TEXT NOT NULL,
    message TEXT NOT NULL CHECK (length(trim(message)) BETWEEN 1 AND 1500),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
    created_at INTEGER NOT NULL,
    closed_by TEXT,
    closed_at INTEGER,
    resolution TEXT,
    CHECK ((status='open' AND closed_by IS NULL AND closed_at IS NULL)
           OR (status='closed' AND closed_by IS NOT NULL AND closed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS inventory_open_clarifications_idx
ON inventory_clarifications(object_id, status, created_at);

-- Photos are stored in PostgreSQL BYTEA, so BotHost container rebuilds do not erase them.
CREATE TABLE IF NOT EXISTS inventory_photos (
    id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES inventory_objects(id) ON DELETE CASCADE,
    uploaded_by TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    content BYTEA NOT NULL,
    created_at INTEGER NOT NULL
);

-- Every change is auditable, including administrator correction of confirmed items.
CREATE TABLE IF NOT EXISTS inventory_audit (
    id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES inventory_objects(id) ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS inventory_audit_history_idx ON inventory_audit(object_id, created_at);

-- Future administrative streaming/bulk CSV/Excel import log.
CREATE TABLE IF NOT EXISTS inventory_import_batches (
    id TEXT PRIMARY KEY,
    created_by TEXT NOT NULL,
    filename TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('uploaded','validated','importing','finished','failed')),
    total_rows INTEGER NOT NULL DEFAULT 0,
    imported_rows INTEGER NOT NULL DEFAULT 0,
    rejected_rows INTEGER NOT NULL DEFAULT 0,
    report_json TEXT,
    started_at INTEGER NOT NULL,
    completed_at INTEGER
);

-- Useful future map query: every object remains publicly visible.
-- SELECT o.*, EXISTS (
--   SELECT 1 FROM inventory_clarifications n
--   WHERE n.object_id=o.id AND n.status='open'
-- ) AS needs_clarification FROM inventory_objects o;
