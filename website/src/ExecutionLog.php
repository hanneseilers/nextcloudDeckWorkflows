<?php

namespace NextcloudDeckWorkflows;

/**
 * Read-only access to automation/var/state.sqlite3's execution_log table -
 * written by automation/adapters/persistence/sqlite_state_store.py
 * (SqliteStateStore.record()). One row per action within a workflow run;
 * every row of one run shares the same run_id, which is how this groups
 * them back together.
 */
class ExecutionLog
{
    public function __construct(private readonly string $dbPath)
    {
    }

    public function isAvailable(): bool
    {
        return is_file($this->dbPath);
    }

    /**
     * Most recent runs first (by their most recent row's insertion order),
     * each with its own list of per-action results.
     *
     * @return array<int, array{
     *     run_id: string, workflow_id: string, event_type: string, card_id: int,
     *     created_at: string, success: bool,
     *     actions: array<int, array{module: string, success: bool, error: ?string}>
     * }>
     */
    public function recentRuns(int $limit = 50, ?string $workflowId = null): array
    {
        if (!$this->isAvailable()) {
            return [];
        }

        $pdo = new \PDO('sqlite:' . $this->dbPath);
        $pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        $pdo->exec('PRAGMA busy_timeout = 5000');

        // Rows, not runs, carry workflow_id/event_type/card_id - but LIMIT
        // has to apply to *runs*, since a run can span several action rows.
        // Find the most recent $limit run ids first (MAX(id) as an
        // insertion-order anchor per run), then fetch every row for those.
        $runIdSql = 'SELECT run_id, MAX(id) AS last_id FROM execution_log WHERE run_id IS NOT NULL';
        if ($workflowId !== null) {
            $runIdSql .= ' AND workflow_id = :workflow_id';
        }
        $runIdSql .= ' GROUP BY run_id ORDER BY last_id DESC LIMIT :limit';

        $stmt = $pdo->prepare($runIdSql);
        $stmt->bindValue(':limit', $limit, \PDO::PARAM_INT);
        if ($workflowId !== null) {
            $stmt->bindValue(':workflow_id', $workflowId);
        }
        $stmt->execute();
        $runIds = array_column($stmt->fetchAll(\PDO::FETCH_ASSOC), 'run_id');

        if ($runIds === []) {
            return [];
        }

        $placeholders = implode(',', array_fill(0, count($runIds), '?'));
        $stmt = $pdo->prepare(
            "SELECT run_id, workflow_id, event_type, card_id, module, success, error, created_at "
            . "FROM execution_log WHERE run_id IN ($placeholders) ORDER BY id"
        );
        $stmt->execute($runIds);

        $runsById = [];
        foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
            $runId = $row['run_id'];
            if (!isset($runsById[$runId])) {
                $runsById[$runId] = [
                    'run_id' => $runId,
                    'workflow_id' => $row['workflow_id'],
                    'event_type' => $row['event_type'],
                    'card_id' => (int) $row['card_id'],
                    'created_at' => $row['created_at'],
                    'success' => true,
                    'actions' => [],
                ];
            }
            $actionSuccess = (bool) $row['success'];
            $runsById[$runId]['actions'][] = [
                'module' => (string) $row['module'],
                'success' => $actionSuccess,
                'error' => $row['error'],
            ];
            $runsById[$runId]['success'] = $runsById[$runId]['success'] && $actionSuccess;
        }

        // $runIds is already newest-first (from the ORDER BY last_id DESC
        // query above); the second query's rows came back oldest-row-first
        // per run (ORDER BY id, so actions display in execution order), so
        // re-apply the run ordering here rather than re-deriving it.
        $ordered = [];
        foreach ($runIds as $runId) {
            if (isset($runsById[$runId])) {
                $ordered[] = $runsById[$runId];
            }
        }
        return $ordered;
    }
}
