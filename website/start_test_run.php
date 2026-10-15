<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\TestRunStore;
use NextcloudDeckWorkflows\WorkflowRepository;

Csrf::requireValidPost('Ungültige Anfrage (CSRF-Token fehlt oder abgelaufen).');

$config = Config::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$workflowId = (string) ($_POST['workflow_id'] ?? '');
$cardId = (int) ($_POST['card_id'] ?? 0);

try {
    $workflowExists = $workflows->get($workflowId) !== null;
} catch (\InvalidArgumentException $e) {
    $workflowExists = false;
}
if (!$workflowExists || $cardId <= 0) {
    http_response_code(400);
    echo 'Workflow oder Karte ungültig.';
    exit;
}

$testRunStore = new TestRunStore($config->stateDbPath());
try {
    $testRunId = $testRunStore->enqueue($workflowId, $cardId);
} catch (\Throwable $e) {
    // Most likely: automation/var/state.sqlite3 (or its test_runs table)
    // doesn't exist yet because `python -m automation.main` has never run -
    // a real first-setup scenario, not a bug, so this gets a clear message
    // instead of a raw PHP error page.
    http_response_code(503);
    echo 'Testlauf konnte nicht angefragt werden: ' . htmlspecialchars($e->getMessage(), ENT_QUOTES, 'UTF-8')
        . '. Lief <code>python -m automation.main</code> schon mindestens einmal?';
    exit;
}

header('Location: history.php?workflow_id=' . urlencode($workflowId) . '&test_run_id=' . urlencode($testRunId));
