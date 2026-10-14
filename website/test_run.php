<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\WorkflowRepository;

$config = Config::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$workflowId = (string) ($_GET['workflow_id'] ?? '');
$workflow = $workflows->get($workflowId);

function h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}
?>
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Testlauf — Nextcloud Deck Workflows</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header>
    <h1>Testlauf: <?= h($workflow['name'] ?? $workflowId) ?></h1>
    <a href="index.php">&larr; Übersicht</a>
</header>

<?php if ($workflow === null): ?>
    <p class="notice error">Workflow '<?= h($workflowId) ?>' nicht gefunden.</p>
<?php else: ?>

<p class="notice">Der Testlauf führt diesen Workflow <strong>wirklich</strong> aus - z. B. werden
E-Mails tatsächlich verschickt, Kommentare wirklich hinzugefügt oder Karten wirklich geändert -
gegen die unten gewählte, echte Karte. Es ist keine Simulation. Das Ergebnis erscheint danach in
der <a href="history.php">Historie</a>.</p>

<div id="error-banner" class="notice error" hidden></div>

<form method="post" action="start_test_run.php" id="test-run-form">
<?= Csrf::field() ?>
<input type="hidden" name="workflow_id" value="<?= h($workflowId) ?>">
<input type="hidden" name="card_id" id="card-id">
<label>Karte (auf Board <?= h((string) $workflow['board_id']) ?>)
    <span id="card-field" class="muted">– lädt –</span>
</label>
<button type="submit" class="button">Testlauf anfragen</button>
</form>

<script>
  window.TEST_RUN_INSTANCE = <?= json_encode($workflow['nextcloud_instance']) ?>;
  window.TEST_RUN_BOARD_ID = <?= json_encode($workflow['board_id']) ?>;
</script>
<script src="assets/typeahead.js"></script>
<script src="assets/test_run.js"></script>
<?php endif; ?>

</body>
</html>
