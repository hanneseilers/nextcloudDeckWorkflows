<?php

namespace NextcloudDeckWorkflows;

/**
 * Reads automation/var/state.sqlite3's heartbeat (written by main.py's
 * run() on every successful completion) and simple aggregate statistics
 * from execution_log - for the website's health.php.
 */
class HealthStatus
{
    /**
     * @param float $staleAfterMinutes How old the heartbeat may be before the
     *   run counts as stopped - config/settings.yaml `health_stale_minutes`.
     *   The default (15) fits a job started every few minutes; a host that
     *   only starts it hourly or daily (STRATO's cron) needs a larger value.
     */
    public function __construct(
        private readonly string $dbPath,
        private readonly float $staleAfterMinutes = 15.0
    ) {
    }

    public function isAvailable(): bool
    {
        return is_file($this->dbPath);
    }

    /** The raw ISO timestamp main.py last finished a run, or null if never/unknown. */
    public function lastRunAt(): ?string
    {
        if (!$this->isAvailable()) {
            return null;
        }
        try {
            $row = $this->connect()->query('SELECT last_run_at FROM heartbeat WHERE id = 1')->fetch(\PDO::FETCH_ASSOC);
        } catch (\PDOException $e) {
            return null; // e.g. heartbeat table doesn't exist yet (automation/main.py never ran)
        }
        return $row ? $row['last_run_at'] : null;
    }

    public function minutesSinceLastRun(): ?float
    {
        $lastRunAt = $this->lastRunAt();
        if ($lastRunAt === null) {
            return null;
        }
        try {
            $last = new \DateTimeImmutable($lastRunAt);
        } catch (\Exception $e) {
            return null;
        }
        // Explicit UTC "now", independent of this PHP installation's default
        // timezone - $lastRunAt already carries its own UTC offset (written
        // by Python as datetime.now(timezone.utc).isoformat()), so only this
        // side needs pinning down.
        $now = new \DateTimeImmutable('now', new \DateTimeZone('UTC'));
        $seconds = $now->getTimestamp() - $last->getTimestamp();
        return $seconds / 60;
    }

    /** True if we have a heartbeat and it's recent enough. */
    public function isHealthy(): bool
    {
        $minutes = $this->minutesSinceLastRun();
        return $minutes !== null && $minutes <= $this->staleAfterMinutes;
    }

    /**
     * Aggregate run counts since `$sinceIso`, overall and per workflow - one
     * run (grouped by run_id) counts as failed if any of its actions failed.
     *
     * @return array{total: int, successful: int, failed: int, per_workflow: array<string, array{total: int, failed: int}>}
     */
    public function stats(string $sinceIso): array
    {
        $empty = ['total' => 0, 'successful' => 0, 'failed' => 0, 'per_workflow' => []];
        if (!$this->isAvailable()) {
            return $empty;
        }

        try {
            $stmt = $this->connect()->prepare(
                'SELECT workflow_id, MIN(success) AS run_success FROM execution_log '
                . 'WHERE created_at >= :since AND run_id IS NOT NULL GROUP BY run_id'
            );
            $stmt->execute([':since' => $sinceIso]);
            $runs = $stmt->fetchAll(\PDO::FETCH_ASSOC);
        } catch (\PDOException $e) {
            return $empty;
        }

        $result = $empty;
        foreach ($runs as $run) {
            $succeeded = (bool) $run['run_success'];
            $result['total']++;
            $result[$succeeded ? 'successful' : 'failed']++;

            $workflowId = $run['workflow_id'];
            $result['per_workflow'][$workflowId] ??= ['total' => 0, 'failed' => 0];
            $result['per_workflow'][$workflowId]['total']++;
            if (!$succeeded) {
                $result['per_workflow'][$workflowId]['failed']++;
            }
        }
        return $result;
    }

    /**
     * Recent webhook pings (most recent first), per board - lets an admin
     * confirm Nextcloud's webhook configuration is actually reaching
     * website/webhook.php, independent of whether main.py has acted on
     * them yet.
     *
     * @return array<int, array{instance: string, board_id: int, last_ping_at: string}>
     */
    public function recentWebhookPings(int $limit = 20): array
    {
        if (!$this->isAvailable()) {
            return [];
        }
        try {
            $stmt = $this->connect()->prepare(
                'SELECT instance, board_id, last_ping_at FROM board_activity '
                . 'WHERE last_ping_at IS NOT NULL ORDER BY last_ping_at DESC LIMIT :limit'
            );
            $stmt->bindValue(':limit', $limit, \PDO::PARAM_INT);
            $stmt->execute();
            return $stmt->fetchAll(\PDO::FETCH_ASSOC);
        } catch (\PDOException $e) {
            return [];
        }
    }

    private function connect(): \PDO
    {
        $pdo = new \PDO('sqlite:' . $this->dbPath);
        $pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        $pdo->exec('PRAGMA busy_timeout = 5000');
        return $pdo;
    }
}
