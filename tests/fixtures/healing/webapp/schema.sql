-- Inventory fixture schema (synthetic).
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    stock INTEGER NOT NULL DEFAULT 0
);
