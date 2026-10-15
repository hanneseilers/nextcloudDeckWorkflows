<?php

namespace NextcloudDeckWorkflows;

/**
 * Writes into automation/var/state.sqlite3's board_activity table (schema
 * owned by automation/adapters/persistence/sqlite_state_store.py) - the
 * one place the website records a webhook ping; main.py's
 * core/domain/webhook_gate.should_poll_now is what actually reacts to it.
 */
class WebhookPingStore
{
    public function __construct(private readonly string $dbPath)
    {
    }

    public function recordPing(string $instance, int $boardId): void
    {
        // UTC, matching main.py's datetime.now(timezone.utc) exactly - a
        // naive/local timestamp here would silently desync from what
        // should_poll_now compares against (this exact mismatch was caught
        // once already while building the Python side - see its commit).
        $nowIso = (new \DateTimeImmutable('now', new \DateTimeZone('UTC')))->format('Y-m-d\TH:i:s.uP');

        $pdo = new \PDO('sqlite:' . $this->dbPath);
        $pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        $pdo->exec('PRAGMA busy_timeout = 5000');
        // A webhook can be configured and fire before `python -m
        // automation.main` has ever run once - e.g. right after a fresh
        // deploy - in which case state.sqlite3 (or this table) doesn't
        // exist yet. Mirrors SqliteStateStore's own schema exactly so
        // whichever side gets there first just creates it; the other side's
        // later CREATE TABLE IF NOT EXISTS is then a no-op.
        $pdo->exec(
            'CREATE TABLE IF NOT EXISTS board_activity ('
            . 'instance TEXT NOT NULL, board_id INTEGER NOT NULL, '
            . 'last_ping_at TEXT, last_polled_at TEXT, '
            . 'PRIMARY KEY (instance, board_id))'
        );
        $stmt = $pdo->prepare(
            'INSERT INTO board_activity (instance, board_id, last_ping_at) VALUES (:instance, :board_id, :now) '
            . 'ON CONFLICT(instance, board_id) DO UPDATE SET last_ping_at = excluded.last_ping_at'
        );
        $stmt->execute([':instance' => $instance, ':board_id' => $boardId, ':now' => $nowIso]);
    }
}
