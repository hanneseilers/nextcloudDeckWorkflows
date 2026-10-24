<?php

namespace NextcloudDeckWorkflows;

/**
 * Rate limits for website/webhook.php, kept in automation/var/state.sqlite3
 * (own table, only ever touched from PHP) so they hold across requests.
 *
 *  - wrong/missing secret: FAIL_LIMIT attempts per FAIL_WINDOW seconds per
 *    client, then the client is refused before its secret is even looked at
 *    (stops guessing; the client key is a hash of the IP, no IP is stored).
 *  - valid pings: VALID_LIMIT per VALID_WINDOW seconds in total - a runaway
 *    or abused sender can't hammer the database.
 *  - automation runs started by a ping: at most one per RUN_INTERVAL seconds
 *    while a run is in progress
 *    (main.py queues one more behind it, so further starts are wasted
 *    processes); with none in progress a ping always starts one, so a change
 *    arriving right after a finished run doesn't wait for the next cron tick.
 *    The ping itself is always recorded, so a skipped start loses nothing.
 *
 * Times are plain epoch seconds - they never leave PHP, so there is no
 * UTC/local question as with the timestamps shared with the Python side.
 */
class WebhookThrottle
{
    public const FAIL_LIMIT = 10;
    public const FAIL_WINDOW = 600;
    public const VALID_LIMIT = 60;
    public const VALID_WINDOW = 60;
    public const RUN_INTERVAL = 2;

    private ?\PDO $pdo = null;

    /** @param (callable(): int)|null $clock epoch seconds - injectable for tests */
    public function __construct(private readonly string $dbPath, private $clock = null)
    {
    }

    /** Seconds the client has to wait (0 = may try). */
    public function retryAfterForFailures(string $clientKey): int
    {
        return $this->retryAfter('fail', $clientKey, self::FAIL_LIMIT, self::FAIL_WINDOW);
    }

    public function recordFailure(string $clientKey): void
    {
        $this->transaction(function (\PDO $pdo, int $now) use ($clientKey): void {
            $this->insert($pdo, 'fail', $clientKey, $now);
        });
    }

    /** Counts a valid ping: 0 = admitted, otherwise the seconds to wait. */
    public function admitValid(): int
    {
        return $this->transaction(function (\PDO $pdo, int $now): int {
            $wait = $this->waitFor($pdo, 'ok', '', self::VALID_LIMIT, self::VALID_WINDOW, $now);
            if ($wait === 0) {
                $this->insert($pdo, 'ok', '', $now);
            }
            return $wait;
        });
    }

    /**
     * Whether an automation run is going on right now: probes the run lock
     * (automation/var/run.lock, held by main.py for the whole run) without
     * keeping it. null = can't tell (no flock, file not usable).
     */
    public static function runInProgress(string $lockPath): ?bool
    {
        if (!function_exists('flock')) {
            return null;
        }
        $handle = @fopen($lockPath, 'c');
        if ($handle === false) {
            return null;
        }
        try {
            if (flock($handle, LOCK_SH | LOCK_NB, $wouldBlock)) {
                flock($handle, LOCK_UN);
                return false;
            }
            return $wouldBlock ? true : null;
        } finally {
            fclose($handle);
        }
    }

    /**
     * True (and remembered) if an automation run may be started now. With
     * no run in progress, always: a ping that arrives right after a finished
     * run must not wait for the next cron tick. While one is going on (or
     * that can't be told), at most every RUN_INTERVAL seconds - main.py
     * queues a run behind a running one (--wait-lock, a single waiter), so
     * more starts than that are wasted processes. A flood of pings is
     * limited by admitValid() anyway.
     *
     * @param bool|null $runInProgress runInProgress()'s answer
     */
    public function claimRun(?bool $runInProgress = null): bool
    {
        return $this->transaction(function (\PDO $pdo, int $now) use ($runInProgress): bool {
            if ($runInProgress !== false && $this->waitFor($pdo, 'run', '', 1, self::RUN_INTERVAL, $now) > 0) {
                return false;
            }
            $this->insert($pdo, 'run', '', $now);
            return true;
        });
    }

    private function retryAfter(string $kind, string $key, int $limit, int $window): int
    {
        return $this->transaction(fn (\PDO $pdo, int $now): int => $this->waitFor($pdo, $kind, $key, $limit, $window, $now));
    }

    private function waitFor(\PDO $pdo, string $kind, string $key, int $limit, int $window, int $now): int
    {
        // The `limit` newest events in the window: if all of them are there,
        // the limit is reached until the oldest of them leaves the window.
        $stmt = $pdo->prepare(
            'SELECT at FROM webhook_events WHERE kind = :kind AND key = :key AND at > :since ORDER BY at DESC LIMIT :limit'
        );
        $stmt->bindValue(':kind', $kind);
        $stmt->bindValue(':key', $key);
        $stmt->bindValue(':since', $now - $window, \PDO::PARAM_INT);
        $stmt->bindValue(':limit', $limit, \PDO::PARAM_INT);
        $stmt->execute();
        $times = $stmt->fetchAll(\PDO::FETCH_COLUMN);
        if (count($times) < $limit) {
            return 0;
        }
        return max(1, (int) end($times) + $window - $now);
    }

    private function insert(\PDO $pdo, string $kind, string $key, int $now): void
    {
        $pdo->prepare('INSERT INTO webhook_events (kind, key, at) VALUES (:kind, :key, :at)')
            ->execute([':kind' => $kind, ':key' => $key, ':at' => $now]);
        // Nothing is looked at for longer than the longest window.
        $pdo->prepare('DELETE FROM webhook_events WHERE at < :old')->execute([':old' => $now - self::FAIL_WINDOW - 60]);
    }

    /**
     * @template T
     * @param callable(\PDO, int): T $work
     * @return T
     */
    private function transaction(callable $work): mixed
    {
        $pdo = $this->connect();
        $now = $this->clock !== null ? ($this->clock)() : time();
        // IMMEDIATE: two simultaneous pings can't both pass a limit.
        $pdo->exec('BEGIN IMMEDIATE');
        try {
            $result = $work($pdo, $now);
            $pdo->exec('COMMIT');
            return $result;
        } catch (\Throwable $e) {
            $pdo->exec('ROLLBACK');
            throw $e;
        }
    }

    private function connect(): \PDO
    {
        if ($this->pdo === null) {
            $dir = dirname($this->dbPath);
            if (!is_dir($dir)) {
                @mkdir($dir, 0775, true);
            }
            $pdo = new \PDO('sqlite:' . $this->dbPath);
            $pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
            $pdo->exec('PRAGMA busy_timeout = 5000');
            $pdo->exec(
                'CREATE TABLE IF NOT EXISTS webhook_events ('
                . 'kind TEXT NOT NULL, key TEXT NOT NULL, at INTEGER NOT NULL)'
            );
            $pdo->exec('CREATE INDEX IF NOT EXISTS webhook_events_lookup ON webhook_events (kind, key, at)');
            $this->pdo = $pdo;
        }
        return $this->pdo;
    }
}
