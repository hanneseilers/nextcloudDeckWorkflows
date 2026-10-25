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
     * @return array{status: string, success_message: string, confirm_message: string, require_confirmation: bool, error: ?string, expired: bool}|null
     *   null if there is no such link - or no database/table yet (nothing was ever created).
     */
    public function find(string $tokenHash): ?array
    {
        $pdo = $this->connect();
        if ($pdo === null) {
            return null;
        }
        $row = false;
        // confirm_message is a newer column: a database the automation has not migrated yet lacks it.
        foreach (['confirm_message', "'' AS confirm_message"] as $confirmColumn) {
            try {
                $stmt = $pdo->prepare(
                    "SELECT status, success_message, $confirmColumn, require_confirmation, error, expires_at FROM action_links WHERE token_hash = :h"
                );
                $stmt->execute([':h' => $tokenHash]);
                $row = $stmt->fetch(\PDO::FETCH_ASSOC);
                break;
            } catch (\PDOException $e) {
                continue;
            }
        }
        if ($row === false) {
            return null;
        }
        return [
            'status' => (string) $row['status'],
            'success_message' => (string) $row['success_message'],
            'confirm_message' => (string) $row['confirm_message'],
            'require_confirmation' => (bool) $row['require_confirmation'],
            'error' => $row['error'] !== null ? (string) $row['error'] : null,
            'expired' => $row['expires_at'] !== null && (string) $row['expires_at'] <= self::nowIso(),
        ];
    }

    /** Atomically uses the link up: true for exactly one caller, false for everyone else. */
    public function claim(string $tokenHash): bool
    {
        $pdo = $this->connect();
        if ($pdo === null) {
            return false;
        }
        try {
            // An expired link can't be claimed, even in a race with the expiry.
            $stmt = $pdo->prepare(
                "UPDATE action_links SET status = 'claimed', claimed_at = :now WHERE token_hash = :h AND status = 'open' "
                . "AND (expires_at IS NULL OR expires_at > :now)"
            );
            $stmt->execute([':now' => self::nowIso(), ':h' => $tokenHash]);
            return $stmt->rowCount() === 1;
        } catch (\PDOException $e) {
            return false;
        }
    }

    /**
     * UTC like every timestamp crossing the Python/PHP boundary, and in the
     * same shape Python writes expires_at in ("2026-10-31T13:05:00+00:00"),
     * so the two compare correctly as strings.
     */
    private static function nowIso(): string
    {
        return (new \DateTimeImmutable('now', new \DateTimeZone('UTC')))->format('Y-m-d\TH:i:sP');
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
