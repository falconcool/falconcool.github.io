
CREATE TABLE IF NOT EXISTS services (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    price_from INTEGER NOT NULL CHECK (price_from >= 0)
);

CREATE TABLE IF NOT EXISTS appointments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    name       TEXT    NOT NULL CHECK (length(name) BETWEEN 2 AND 100),
    phone      TEXT    NOT NULL CHECK (length(phone) = 11),
    pet        TEXT    NOT NULL CHECK (pet IN ('Кошка', 'Собака', 'Другое')),
    service_id INTEGER NOT NULL REFERENCES services(id),
    status     TEXT    NOT NULL DEFAULT 'new'
               CHECK (status IN ('new', 'confirmed', 'done', 'cancelled'))
);
