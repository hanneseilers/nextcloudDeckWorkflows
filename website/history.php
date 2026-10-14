<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\EventTypes;
use NextcloudDeckWorkflows\ExecutionLog;
use NextcloudDeckWorkflows\TestRunStore;
use NextcloudDeckWorkflows\WorkflowRepository;

$config = Config::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());
$executionLog = new ExecutionLog($config->stateDbPath());

$pendingTestRun = null;
if (isset($_GET['test_run_id'])) {
    $pendingTestRun = (new TestRunStore($config->stateDbPath()))->get((string) $_GET['test_run_id']);
}

$workflowFilter = isset($_GET['workflow_id']) ? (string) $_GET['workflow_id'] : null;
$runs = $executionLog->recentRuns(100, $workflowFilter !== '' ? $workflowFilter : null);

// Workflow names are looked up once per page view, not per row - ids no
// longer in workflows/ (deleted since) just fall back to showing the id.
$workflowNames = [];
foreach ($workflows->listAll() as $workflow) {
    $workflowNames[$workflow['id']] = $workflow['name'] ?? $workflow['id'];
}

function h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}
?>
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Ausführungs-Historie — Nextcloud Deck Workflows</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header>
    <h1>Ausführungs-Historie</h1>
    <a href="index.php">&larr; Übersicht</a>
</header>

<?php if ($pendingTestRun !== null && $pendingTestRun['status'] === 'pending'): ?>
    <p class="notice">Testlauf angefragt - wird beim nächsten Lauf von
    <code>python -m automation.main</code> verarbeitet (Cron oder manuell). Seite danach neu laden.</p>
<?php elseif ($pendingTestRun !== null && $pendingTestRun['status'] === 'error'): ?>
    <p class="notice error">Testlauf fehlgeschlagen: <?= h((string) $pendingTestRun['error']) ?></p>
<?php elseif ($pendingTestRun !== null && $pendingTestRun['status'] === 'done'): ?>
    <p class="notice">Testlauf abgeschlossen - Ergebnis in der Liste unten.</p>
<?php endif; ?>

<?php if (!$executionLog->isAvailable()): ?>
    <p class="notice">Noch keine <code>automation/var/state.sqlite3</code> gefunden - sie entsteht
    beim ersten Lauf von <code>python -m automation.main</code>.</p>
<?php else: ?>

<form method="get" class="inline">
    <label>Workflow
        <select name="workflow_id" onchange="this.form.submit()">
            <option value="">– alle –</option>
            <?php foreach ($workflowNames as $id => $name): ?>
            <option value="<?= h($id) ?>" <?= $workflowFilter === $id ? 'selected' : '' ?>><?= h($name) ?> (<?= h($id) ?>)</option>
            <?php endforeach; ?>
        </select>
    </label>
</form>

<?php if (empty($runs)): ?>
    <p>Noch keine Ausführungen protokolliert<?= $workflowFilter ? ' für diesen Workflow' : '' ?>.</p>
<?php else: ?>
<table>
<thead>
<tr>
    <th>Zeitpunkt</th>
    <th>Workflow</th>
    <th>Event</th>
    <th>Karte</th>
    <th>Status</th>
    <th>Schritte</th>
</tr>
</thead>
<tbody>
<?php foreach ($runs as $run): ?>
<tr class="<?= $run['success'] ? '' : 'run-failed' ?>">
    <td><?= h($run['created_at']) ?></td>
    <td>
        <a href="history.php?workflow_id=<?= urlencode($run['workflow_id']) ?>">
            <?= h($workflowNames[$run['workflow_id']] ?? $run['workflow_id']) ?>
        </a>
    </td>
    <td><?= h(EventTypes::label($run['event_type'])) ?></td>
    <td><?= (int) $run['card_id'] ?></td>
    <td><?= $run['success'] ? 'Erfolg' : 'Fehler' ?></td>
    <td>
        <ul class="run-actions">
        <?php foreach ($run['actions'] as $action): ?>
            <li class="<?= $action['success'] ? 'action-ok' : 'action-failed' ?>">
                <?= $action['success'] ? '✓' : '✗' ?> <?= h($action['module']) ?>
                <?php if (!$action['success'] && $action['error']): ?>
                    — <?= h($action['error']) ?>
                <?php endif; ?>
            </li>
        <?php endforeach; ?>
        </ul>
    </td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
<?php endif; ?>
<?php endif; ?>

</body>
</html>
