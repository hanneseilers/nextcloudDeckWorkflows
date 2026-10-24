<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\EventTypes;
use NextcloudDeckWorkflows\ExecutionLog;
use NextcloudDeckWorkflows\ModuleRegistry;
use NextcloudDeckWorkflows\TestRunStore;
use NextcloudDeckWorkflows\WorkflowRepository;

$config = Config::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());
$executionLog = new ExecutionLog($config->stateDbPath());

$moduleLabels = [];
foreach (ModuleRegistry::fromRepoRoot()->all() as $module) {
    $moduleLabels[$module['name']] = $module['label'] ?? $module['name'];
}

$pendingTestRun = null;
if (isset($_GET['test_run_id'])) {
    $pendingTestRun = (new TestRunStore($config->stateDbPath()))->get((string) $_GET['test_run_id']);
}

const PAGE_SIZE = 50;
$workflowFilter = isset($_GET['workflow_id']) && $_GET['workflow_id'] !== '' ? (string) $_GET['workflow_id'] : null;
$statusFilter = in_array($_GET['status'] ?? '', ['failed', 'ok'], true) ? (string) $_GET['status'] : null;
$page = max(1, (int) ($_GET['page'] ?? 1));
// One extra run tells whether there is an older page.
$runs = $executionLog->recentRuns(PAGE_SIZE + 1, $workflowFilter, $statusFilter, ($page - 1) * PAGE_SIZE);
$hasOlder = count($runs) > PAGE_SIZE;
$runs = array_slice($runs, 0, PAGE_SIZE);
$filterQuery = static fn (array $overrides = []): string => http_build_query(array_filter(
    array_merge(['workflow_id' => $workflowFilter, 'status' => $statusFilter], $overrides),
    static fn ($value) => $value !== null && $value !== ''
));

// Workflow names/trigger kind are looked up once per page view, not per
// row - ids no longer in workflows/ (deleted since) just fall back to
// showing the id and the stored event type.
$workflowNames = [];
$scheduleWorkflowIds = [];
foreach ($workflows->listAll() as $workflow) {
    $workflowNames[$workflow['id']] = $workflow['name'] ?? $workflow['id'];
    if (isset($workflow['trigger']['schedule'])) {
        $scheduleWorkflowIds[$workflow['id']] = true;
    }
}

?>
<?php Layout::start('Historie', 'Ausführungs-Historie', 'history'); ?>

<?php if ($pendingTestRun !== null && in_array($pendingTestRun['status'], ['pending', 'running'], true)): ?>
    <p class="notice">
    <?php if ($pendingTestRun['status'] === 'running'): ?>
        Testlauf läuft gerade ...
    <?php else: ?>
        Testlauf angefragt - er wird gleich ausgeführt, spätestens beim nächsten Lauf von
        <code>python -m automation.main</code> (Cron oder manuell).
    <?php endif; ?>
    Die Seite aktualisiert sich selbst.</p>
    <script>setTimeout(function () { location.reload(); }, 3000);</script>
<?php elseif ($pendingTestRun !== null && $pendingTestRun['status'] === 'error'): ?>
    <p class="notice error">Testlauf fehlgeschlagen: <?= h((string) $pendingTestRun['error']) ?></p>
<?php elseif ($pendingTestRun !== null && $pendingTestRun['status'] === 'done'): ?>
    <p class="notice">Testlauf abgeschlossen - Ergebnis in der Liste unten.</p>
<?php endif; ?>

<?php if (!$executionLog->isAvailable()): ?>
    <p class="notice">Noch keine <code>automation/var/state.sqlite3</code> gefunden - sie entsteht
    beim ersten Lauf von <code>python -m automation.main</code>.</p>
<?php else: ?>

<form method="get" class="filters">
    <label>Workflow
        <select name="workflow_id" onchange="this.form.submit()">
            <option value="">– alle –</option>
            <?php foreach ($workflowNames as $id => $name): ?>
            <option value="<?= h($id) ?>" <?= $workflowFilter === $id ? 'selected' : '' ?>><?= h($name) ?></option>
            <?php endforeach; ?>
        </select>
    </label>
    <label>Ergebnis
        <select name="status" onchange="this.form.submit()">
            <option value="">– alle –</option>
            <option value="failed" <?= $statusFilter === 'failed' ? 'selected' : '' ?>>nur Fehler</option>
            <option value="ok" <?= $statusFilter === 'ok' ? 'selected' : '' ?>>nur erfolgreiche</option>
        </select>
    </label>
    <noscript><button type="submit">Filtern</button></noscript>
    <?php if ($workflowFilter !== null || $statusFilter !== null): ?>
        <a href="history.php">Filter zurücksetzen</a>
    <?php endif; ?>
</form>

<?php if (empty($runs)): ?>
    <p><?= $page > 1 ? 'Keine älteren Ausführungen.' : 'Keine Ausführungen' . ($workflowFilter !== null || $statusFilter !== null ? ' für diesen Filter' : ' protokolliert') . '.' ?></p>
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
    <td><?= Layout::dateTime($run['created_at']) ?></td>
    <td>
        <a href="history.php?<?= h($filterQuery(['workflow_id' => $run['workflow_id']])) ?>">
            <?= h($workflowNames[$run['workflow_id']] ?? $run['workflow_id']) ?>
        </a>
    </td>
    <td><?= isset($scheduleWorkflowIds[$run['workflow_id']]) ? 'Zeitplan' : h(EventTypes::label($run['event_type'])) ?></td>
    <td><?= isset($scheduleWorkflowIds[$run['workflow_id']]) ? '–' : (int) $run['card_id'] ?></td>
    <td><?= $run['success'] ? 'Erfolg' : 'Fehler' ?></td>
    <td>
        <ul class="run-actions">
        <?php foreach ($run['actions'] as $action): ?>
            <li class="<?= $action['success'] ? 'action-ok' : 'action-failed' ?>">
                <?= $action['success'] ? '✓' : '✗' ?> <span title="<?= h($action['module']) ?>"><?= h($moduleLabels[$action['module']] ?? $action['module']) ?></span>
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
<p class="pager">
    <?php if ($page > 1): ?><a class="button" href="history.php?<?= h($filterQuery(['page' => $page - 1 > 1 ? $page - 1 : null])) ?>">&larr; Neuere</a><?php endif; ?>
    <?php if ($hasOlder): ?><a class="button" href="history.php?<?= h($filterQuery(['page' => $page + 1])) ?>">Ältere &rarr;</a><?php endif; ?>
</p>
<?php endif; ?>
<?php endif; ?>

<?php Layout::end(); ?>
