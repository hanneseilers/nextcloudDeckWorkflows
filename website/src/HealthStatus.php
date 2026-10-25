<?php

namespace NextcloudDeckWorkflows;

/**
 * Reads automation/var/state.sqlite3's heartbeat (written by the CRON job's
 * runs of main.py on every successful completion - runs the website starts
 * itself don't count) and simple aggregate statistics from execution_log - for
 * the website's health.php.
 *
 * How old the heartbeat may be depends on how often the cron job is meant to
 * run (config/settings.yaml `cron_interval_minutes`, default 4 hours):
 *   - up to 1.5 x that: "ok"
 *   - up to 3 x that: "late" - a run was missed (a host may delay its cron jobs)
 *   - beyond: "stopped" (health.php answers 503)
 */
class HealthStatus
{
    public const DEFAULT_INTERVAL_MINUTES = 240.0; // every 4 hours
    public const LATE_FACTOR = 1.5;
    public const STOPPED_FACTOR = 3.0;

    public function __construct(
        private readonly string $dbPath,
        private readonly float $intervalMinutes = self::DEFAULT_INTERVAL_MINUTES
    ) {
    }

    public function intervalText(): string
    {
        return self::durationText((int) round($this->intervalMinutes));
    }

    /** After this many minutes without a cron run the status is "late". */
    public function lateAfterMinutes(): float
    {
        return $this->intervalMinutes * self::LATE_FACTOR;
    }

    /** After this many minutes without a cron run the status is "stopped". */
    public function stoppedAfterMinutes(): float
    {
        return $this->intervalMinutes * self::STOPPED_FACTOR;
    }

    /** 'ok' | 'late' | 'stopped' ('stopped' also when there was never a run). */
    public function status(): string
    {
        $minutes = $this->minutesSinceLastRun();
        if ($minutes === null || $minutes > $this->stoppedAfterMinutes()) {
            return 'stopped';
        }
        return $minutes > $this->lateAfterMinutes() ? 'late' : 'ok';
    }

    /** When the next cron run is expected (last run + interval), or null without a last run. */
    public function nextExpectedRunAt(): ?\DateTimeImmutable
    {
        $lastRunAt = $this->lastRunAt();
        if ($lastRunAt === null) {
            return null;
        }
        try {
            return (new \DateTimeImmutable($lastRunAt))->modify('+' . (int) round($this->intervalMinutes * 60) . ' seconds');
        } catch (\Exception $e) {
            return null;
        }
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

    /** The "stopped" threshold as text: "12 Stunden", "90 Minuten", "1 Tag 12 Stunden" ... */
    public function stoppedAfterText(): string
    {
        return self::durationText((int) round($this->stoppedAfterMinutes()));
    }

    public function lateAfterText(): string
    {
        return self::durationText((int) round($this->lateAfterMinutes()));
    }

    public static function durationText(int $minutes): string
    {
        if ($minutes < 60) {
            return $minutes . ' ' . ($minutes === 1 ? 'Minute' : 'Minuten');
        }
        $days = intdiv($minutes, 1440);
        $hours = intdiv($minutes % 1440, 60);
        $rest = $minutes % 60;
        $parts = [];
        if ($days > 0) {
            $parts[] = $days . ' ' . ($days === 1 ? 'Tag' : 'Tage');
        }
        if ($hours > 0) {
            $parts[] = $hours . ' ' . ($hours === 1 ? 'Stunde' : 'Stunden');
        }
        if ($rest > 0) {
            $parts[] = $rest . ' ' . ($rest === 1 ? 'Minute' : 'Minuten');
        }
        return implode(' ', $parts);
    }

    /** False only when the status is "stopped" - "late" is a warning, not an outage. */
    public function isHealthy(): bool
    {
        return $this->status() !== 'stopped';
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
