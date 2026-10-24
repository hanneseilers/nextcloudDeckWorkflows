<?php

namespace NextcloudDeckWorkflows;

/**
 * Writes/reads "Testlauf" requests in automation/var/state.sqlite3's
 * test_runs table (schema owned by automation/adapters/persistence/
 * sqlite_state_store.py - this is the one place the website writes into
 * that database, everywhere else it only reads). main.py's next
 * invocation (manual or cron) picks up a pending request, actually runs
 * the chosen workflow against the chosen real card, and writes the result
 * back onto the same row.
 */
class TestRunStore
{
    public function __construct(private readonly string $dbPath)
    {
    }

    public function isAvailable(): bool
    {
        return is_file($this->dbPath);
    }

    public function enqueue(string $workflowId, int $cardId): string
    {
        $testRunId = bin2hex(random_bytes(16));
        $pdo = $this->connect();
        // A test run can be requested before `python -m automation.main` ever
        // ran (it creates this table) - create it here, same schema, so the
        // request is simply waiting for that first run instead of failing.
        $pdo->exec(
            'CREATE TABLE IF NOT EXISTS test_runs ('
            . 'id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, card_id INTEGER NOT NULL, '
            . 'status TEXT NOT NULL, run_id TEXT, error TEXT, created_at TEXT NOT NULL, completed_at TEXT)'
        );
        $stmt = $pdo->prepare(
            "INSERT INTO test_runs (id, workflow_id, card_id, status, created_at) "
            . "VALUES (:id, :workflow_id, :card_id, 'pending', :created_at)"
        );
        $stmt->execute([
            ':id' => $testRunId,
            ':workflow_id' => $workflowId,
            ':card_id' => $cardId,
            ':created_at' => gmdate('Y-m-d\TH:i:s\+00:00'),
        ]);
        return $testRunId;
    }

    /** @return array{id: string, workflow_id: string, card_id: int, status: string, run_id: ?string, error: ?string, created_at: string, completed_at: ?string}|null */
    public function get(string $testRunId): ?array
    {
        if (!$this->isAvailable()) {
            return null;
        }
        $pdo = $this->connect();
        try {
            $stmt = $pdo->prepare('SELECT * FROM test_runs WHERE id = :id');
            $stmt->execute([':id' => $testRunId]);
            $row = $stmt->fetch(\PDO::FETCH_ASSOC);
        } catch (\PDOException $e) {
            return null; // the table doesn't exist yet - nothing was requested
        }
        if ($row === false) {
            return null;
        }
        $row['card_id'] = (int) $row['card_id'];
        return $row;
    }

    private function connect(): \PDO
    {
        $dir = dirname($this->dbPath);
        if (!is_dir($dir)) {
            mkdir($dir, 0775, true);
        }
        $pdo = new \PDO('sqlite:' . $this->dbPath);
        $pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        // Waits instead of immediately failing with "database is locked" if
        // automation/main.py happens to be mid-write at the same moment -
        // a rare, short-lived overlap, not a sustained contention scenario.
        $pdo->exec('PRAGMA busy_timeout = 5000');
        return $pdo;
    }
}
