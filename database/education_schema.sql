-- Additive education directory; independent of the legacy forecasting marts.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS education_releases (
    release_id TEXT PRIMARY KEY,
    academic_year INTEGER NOT NULL,
    parser_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_as_of TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS education_active_release (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    release_id TEXT NOT NULL REFERENCES education_releases(release_id)
);
CREATE TABLE IF NOT EXISTS education_sources (
    release_id TEXT NOT NULL REFERENCES education_releases(release_id),
    source_key TEXT NOT NULL,
    url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    PRIMARY KEY (release_id, source_key)
);
CREATE TABLE IF NOT EXISTS education_institutions (
    release_id TEXT NOT NULL REFERENCES education_releases(release_id),
    institution_id TEXT NOT NULL,
    name TEXT NOT NULL,
    school_type TEXT NOT NULL,
    ownership TEXT NOT NULL,
    headquarters_address TEXT NOT NULL,
    website TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    in_taichung_scope INTEGER NOT NULL CHECK (in_taichung_scope IN (0,1)),
    PRIMARY KEY (release_id, institution_id)
);
CREATE TABLE IF NOT EXISTS education_campuses (
    release_id TEXT NOT NULL,
    campus_id TEXT NOT NULL,
    institution_id TEXT NOT NULL,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    city TEXT NOT NULL,
    district TEXT,
    postal_code TEXT,
    latitude REAL,
    longitude REAL,
    address_status TEXT NOT NULL CHECK (address_status IN ('OFFICIAL_REPORTED','PENDING')),
    coordinate_status TEXT NOT NULL DEFAULT 'PENDING',
    source_key TEXT NOT NULL,
    PRIMARY KEY (release_id, campus_id),
    FOREIGN KEY (release_id, institution_id) REFERENCES education_institutions(release_id, institution_id),
    FOREIGN KEY (release_id, source_key) REFERENCES education_sources(release_id, source_key),
    CHECK ((latitude IS NULL AND longitude IS NULL) OR (latitude IS NOT NULL AND longitude IS NOT NULL AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180))
);
CREATE TABLE IF NOT EXISTS education_departments (
    release_id TEXT NOT NULL,
    department_id TEXT NOT NULL,
    institution_id TEXT NOT NULL,
    department_code TEXT NOT NULL,
    name TEXT NOT NULL,
    college TEXT NOT NULL,
    website TEXT NOT NULL,
    source_key TEXT NOT NULL,
    registry_listed INTEGER NOT NULL CHECK (registry_listed IN (0,1)),
    PRIMARY KEY (release_id, department_id),
    UNIQUE (release_id, institution_id, department_code, name),
    FOREIGN KEY (release_id, institution_id) REFERENCES education_institutions(release_id, institution_id),
    FOREIGN KEY (release_id, source_key) REFERENCES education_sources(release_id, source_key)
);
CREATE TABLE IF NOT EXISTS education_department_campuses (
    release_id TEXT NOT NULL,
    department_id TEXT NOT NULL,
    campus_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK (relation_type IN ('SINGLE_OFFICIAL_CAMPUS','DEPARTMENT_CONTACT_ADDRESS','VERIFIED_TEACHING')),
    source_key TEXT NOT NULL,
    PRIMARY KEY (release_id, department_id, campus_id, relation_type),
    FOREIGN KEY (release_id, department_id) REFERENCES education_departments(release_id, department_id),
    FOREIGN KEY (release_id, campus_id) REFERENCES education_campuses(release_id, campus_id),
    FOREIGN KEY (release_id, source_key) REFERENCES education_sources(release_id, source_key)
);
CREATE TABLE IF NOT EXISTS education_review_tasks (
    release_id TEXT NOT NULL REFERENCES education_releases(release_id),
    task_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (release_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_education_campus_location ON education_campuses(release_id, city, district);
CREATE INDEX IF NOT EXISTS idx_education_department_school ON education_departments(release_id, institution_id);
CREATE INDEX IF NOT EXISTS idx_education_rel_campus ON education_department_campuses(release_id, campus_id, department_id);

-- Coordinates have their own provenance; the address source remains unchanged.
CREATE TABLE IF NOT EXISTS education_coordinate_evidence (
    release_id TEXT NOT NULL,
    campus_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    validation_source_key TEXT NOT NULL,
    source_feature_id INTEGER NOT NULL,
    source_feature_name TEXT NOT NULL,
    source_feature_period TEXT NOT NULL,
    source_crs TEXT NOT NULL,
    target_crs TEXT NOT NULL CHECK (target_crs = 'EPSG:4326'),
    method TEXT NOT NULL,
    point_type TEXT NOT NULL,
    projected_x REAL NOT NULL,
    projected_y REAL NOT NULL,
    verified_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    PRIMARY KEY (release_id, campus_id),
    FOREIGN KEY (release_id, campus_id) REFERENCES education_campuses(release_id, campus_id),
    FOREIGN KEY (release_id, source_key) REFERENCES education_sources(release_id, source_key),
    FOREIGN KEY (release_id, validation_source_key) REFERENCES education_sources(release_id, source_key)
);
