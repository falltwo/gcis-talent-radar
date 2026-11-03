-- Institution switchboards, independent of department and campus phone numbers.
CREATE TABLE IF NOT EXISTS education_institution_contacts (
    release_id TEXT NOT NULL,
    institution_id TEXT NOT NULL,
    contact_kind TEXT NOT NULL CHECK (contact_kind = 'INSTITUTION_SWITCHBOARD'),
    phone_display TEXT NOT NULL CHECK (length(phone_display) > 0),
    phone_e164 TEXT NOT NULL CHECK (phone_e164 LIKE '+886%'),
    source_url TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    source_period TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (release_id, institution_id, contact_kind),
    FOREIGN KEY (release_id, institution_id) REFERENCES education_institutions(release_id, institution_id)
);
