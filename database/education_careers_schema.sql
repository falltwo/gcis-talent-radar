CREATE TABLE IF NOT EXISTS education_career_supplements (
    department_id TEXT NOT NULL,
    title TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('direct', 'related')),
    source_url TEXT NOT NULL,
    PRIMARY KEY (department_id, title, source_url)
);

CREATE TABLE IF NOT EXISTS education_career_aliases (
    alias TEXT PRIMARY KEY,
    title TEXT NOT NULL
);
