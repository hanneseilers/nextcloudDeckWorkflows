<?php

namespace NextcloudDeckWorkflows;

/**
 * The website's side of one-time action links: reads/claims rows of
 * automation/var/state.sqlite3's action_links table (schema owned by
 * automation/adapters/persistence/sqlite_state_store.py). Claiming is the
 * only write - main.py runs the claimed link and records the outcome.
 * Looks links up by the SHA-256 of the token; the token itself is never stored.
 */
class ActionLinkStore
{
    public function __construct(private readonly string $dbPath)
    {
    }

    /**
     * @return array{status: string, success_message: string, require_confirmation: bool, error: ?string}|null
     *   null if there is no such link - or no database/table yet (nothing was ever created).
     */
    public function find(string $tokenHash): ?array
    {
        $pdo = $this->connect();
        if ($pdo === null) {
            return null;
        }
        try {
            $stmt = $pdo->prepare(
                'SELECT status, success_message, require_confirmation, error FROM action_links WHERE token_hash = :h'
            );
            $stmt->execute([':h' => $tokenHash]);
            $row = $stmt->fetch(\PDO::FETCH_ASSOC);
        } catch (\PDOException $e) {
            return null;
        }
        if ($row === false) {
            return null;
        }
        return [
            'status' => (string) $row['status'],
            'success_message' => (string) $row['success_message'],
            'require_confirmation' => (bool) $row['require_confirmation'],
            'error' => $row['error'] !== null ? (string) $row['error'] : null,
        ];
    }

    /** Atomically uses the link up: true for exactly one caller, false for everyone else. */
    public function claim(string $tokenHash): bool
    {
        $pdo = $this->connect();
        if ($pdo === null) {
            return false;
        }
        // UTC, like every timestamp crossing the Python/PHP boundary.
        $nowIso = (new \DateTimeImmutable('now', new \DateTimeZone('UTC')))->format('Y-m-d\TH:i:s.uP');
        try {
            $stmt = $pdo->prepare(
                "UPDATE action_links SET status = 'claimed', claimed_at = :now WHERE token_hash = :h AND status = 'open'"
            );
            $stmt->execute([':now' => $nowIso, ':h' => $tokenHash]);
            return $stmt->rowCount() === 1;
        } catch (\PDOException $e) {
            return false;
        }
    }

    private function connect(): ?\PDO
    {
        if (!is_file($this->dbPath)) {
            return null; // don't let PDO create an empty database file as a side effect
        }
        $pdo = new \PDO('sqlite:' . $this->dbPath);
        $pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        $pdo->exec('PRAGMA busy_timeout = 5000');
        return $pdo;
    }
}
