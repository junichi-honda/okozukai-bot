-- 仕様書 §5 のスキーマ。
-- created_at / decided_at は JST の 'YYYY-MM-DD HH:MM:SS' 文字列で保存する。
-- (D1/Workers は常に UTC なので SQLite の 'localtime' は JST にならない。
--  日付境界を JST で扱うため、書き込み側で JST 文字列に変換してから保存する。)

CREATE TABLE IF NOT EXISTS tasks (
    task_id                   TEXT PRIMARY KEY,
    label                     TEXT NOT NULL,
    amount                    INTEGER NOT NULL,
    allow_duplicate_same_day  INTEGER NOT NULL DEFAULT 0,
    active                    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       TEXT NOT NULL REFERENCES tasks(task_id),
    label         TEXT NOT NULL,
    amount        INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    slack_ts      TEXT,
    approved_by   TEXT,
    created_at    TEXT NOT NULL,
    decided_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_task_created
    ON requests (task_id, status, created_at);

CREATE TABLE IF NOT EXISTS ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    label       TEXT,
    request_id  INTEGER REFERENCES requests(id),
    created_by  TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ledger_created ON ledger (created_at);

-- 初期タスク(仕様書 §6: お風呂掃除・皿洗いは 1日1回まで)
INSERT OR IGNORE INTO tasks (task_id, label, amount, allow_duplicate_same_day, active)
VALUES ('A', 'お風呂掃除', 20, 0, 1),
       ('B', '皿洗い',     10, 0, 1);
