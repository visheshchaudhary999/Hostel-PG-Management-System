-- Hostel / PG Management System: database schema (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rooms (
    id        INTEGER PRIMARY KEY,
    number    TEXT    NOT NULL UNIQUE,
    block     TEXT    NOT NULL CHECK (block IN ('Boys', 'Girls')),
    floor     INTEGER NOT NULL CHECK (floor BETWEEN 0 AND 20),
    capacity  INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 4),
    rent      INTEGER NOT NULL CHECK (rent > 0),          -- rupees per bed per month
    ac        INTEGER NOT NULL DEFAULT 0 CHECK (ac IN (0, 1))
);

CREATE TABLE IF NOT EXISTS residents (
    id             INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL,
    gender         TEXT    NOT NULL CHECK (gender IN ('M', 'F')),
    phone          TEXT    NOT NULL UNIQUE,
    email          TEXT    NOT NULL UNIQUE,
    course         TEXT    NOT NULL DEFAULT '',
    guardian_name  TEXT    NOT NULL DEFAULT '',
    guardian_phone TEXT    NOT NULL DEFAULT '',
    address        TEXT    NOT NULL DEFAULT '',
    room_id        INTEGER REFERENCES rooms(id),          -- NULL after the resident leaves
    joined_on      TEXT    NOT NULL,                      -- YYYY-MM-DD
    left_on        TEXT,
    deposit        INTEGER NOT NULL DEFAULT 0 CHECK (deposit >= 0),
    status         TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'left'))
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('warden', 'resident')),
    resident_id   INTEGER REFERENCES residents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS invoices (
    id          INTEGER PRIMARY KEY,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    month       TEXT    NOT NULL,                         -- YYYY-MM
    room_number TEXT    NOT NULL,                         -- room at the time of billing
    rent        INTEGER NOT NULL CHECK (rent >= 0),
    late_fee    INTEGER NOT NULL DEFAULT 0 CHECK (late_fee >= 0),
    due_on      TEXT    NOT NULL,
    UNIQUE (resident_id, month)
);

CREATE TABLE IF NOT EXISTS payments (
    id         INTEGER PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    amount     INTEGER NOT NULL CHECK (amount > 0),
    mode       TEXT    NOT NULL CHECK (mode IN ('Cash', 'UPI', 'Card', 'Bank transfer')),
    paid_on    TEXT    NOT NULL,
    receipt_no TEXT    UNIQUE
);

CREATE TABLE IF NOT EXISTS complaints (
    id          INTEGER PRIMARY KEY,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    category    TEXT    NOT NULL,
    description TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved')),
    remark      TEXT    NOT NULL DEFAULT '',
    created_on  TEXT    NOT NULL,
    resolved_on TEXT
);

CREATE TABLE IF NOT EXISTS notices (
    id        INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    body      TEXT NOT NULL,
    posted_on TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_residents_room ON residents(room_id);
CREATE INDEX IF NOT EXISTS idx_invoices_month ON invoices(month);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
