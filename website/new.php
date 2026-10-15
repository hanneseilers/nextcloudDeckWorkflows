<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\EventTypes;
use NextcloudDeckWorkflows\ModuleRegistry;
use NextcloudDeckWorkflows\WorkflowRepository;

$config = Config::fromRepoRoot();
$modules = ModuleRegistry::fromRepoRoot();
$eventTypes = EventTypes::labels();

$editId = (string) ($_GET['id'] ?? '');
$existingWorkflow = null;
if ($editId !== '') {
    try {
        $existingWorkflow = (new WorkflowRepository($config->workflowsDir()))->get($editId);
    } catch (\InvalidArgumentException $e) {
        $existingWorkflow = null;
    }
}
$isEdit = $editId !== '' && $existingWorkflow !== null;

function h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}
?>
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title><?= $isEdit ? 'Workflow bearbeiten' : 'Neuer Workflow' ?> — Nextcloud Deck Workflows</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header>
    <h1><?= $isEdit ? 'Workflow bearbeiten: ' . h((string) $existingWorkflow['name']) : 'Neuer Workflow' ?></h1>
    <a href="index.php">&larr; Übersicht</a>
</header>

<?php if ($editId !== '' && $existingWorkflow === null): ?>
    <p class="notice error">Workflow '<?= h($editId) ?>' nicht gefunden.</p>
<?php elseif (empty($config->instances())): ?>
    <p class="notice">Keine Nextcloud-Instanz konfiguriert. Lege <code>config/nextcloud.yaml</code> an
    (Vorlage: <code>config/nextcloud.example.yaml</code>), bevor du einen Workflow anlegst.</p>
<?php elseif (!$modules->isAvailable()): ?>
    <p class="notice">Noch keine Modul-Liste gefunden. Führe einmal
    <code>python -m automation.main --list-modules</code> aus, oder warte auf den nächsten Cron-Lauf.</p>
<?php else: ?>

<div id="error-banner" class="notice error" hidden></div>

<form method="post" action="save.php" id="workflow-form">
<?= Csrf::field() ?>
<input type="hidden" name="payload" id="payload">

<fieldset>
<legend>Wo?</legend>

<label>Nextcloud-Instanz
    <select id="instance" required>
        <option value="">– wählen –</option>
        <?php foreach ($config->instances() as $name => $instance): ?>
        <option value="<?= h($name) ?>"><?= h($name) ?> (<?= h($instance['url']) ?>)</option>
        <?php endforeach; ?>
    </select>
</label>

<label>Board (Deck)
    <span id="board-field" class="muted">– zuerst Instanz wählen –</span>
    <input type="hidden" id="board">
</label>

<label id="stack-label">Spalte (optional - leer/"Alle Spalten" lässt den Workflow auf jede Spalte reagieren)
    <span id="stack-field" class="muted">– zuerst Board wählen –</span>
    <input type="hidden" id="stack">
</label>
</fieldset>

<fieldset>
<legend>Wann?</legend>
<label>Trigger-Art
    <select id="trigger-kind">
        <option value="event">Nextcloud-Event</option>
        <option value="schedule">Zeitplan (zeitbasiert)</option>
    </select>
</label>

<div id="event-trigger-fields">
<label>Event
    <select id="event-type" required>
        <?php foreach ($eventTypes as $value => $label): ?>
        <option value="<?= h($value) ?>"><?= h($label) ?></option>
        <?php endforeach; ?>
    </select>
</label>
</div>

<div id="schedule-trigger-fields" hidden>
<p class="muted">Läuft unabhängig von Karten-Events zur angegebenen Zeit - nutze dafür
Module ohne Kartenbezug (z. B. <code>send_email</code>, <code>log_action</code>,
<code>generate_random_number</code>, <code>calculate</code>).</p>
<label>Uhrzeit
    <input type="time" id="schedule-time">
</label>
<label>Wochentage (keine Auswahl = jeden Tag)
    <span class="weekday-checkboxes">
        <?php foreach (['1' => 'Mo', '2' => 'Di', '3' => 'Mi', '4' => 'Do', '5' => 'Fr', '6' => 'Sa', '7' => 'So'] as $iso => $label): ?>
        <label><input type="checkbox" class="schedule-weekday" value="<?= $iso ?>"> <?= $label ?></label>
        <?php endforeach; ?>
    </span>
</label>
</div>
</fieldset>

<fieldset>
<legend>Workflow</legend>
<label>Name
    <input type="text" id="name" required>
</label>
<label>Id (technischer Name, Dateiname in <code>workflows/</code>)
    <input type="text" id="workflow-id" pattern="[a-z0-9\-]+" required <?= $isEdit ? 'readonly' : '' ?>>
</label>
</fieldset>

<fieldset>
<legend>Was passiert? (Module in Reihenfolge)</legend>
<div id="steps"></div>
<button type="button" id="add-step">+ Schritt hinzufügen</button>
</fieldset>

<button type="submit" class="button"><?= $isEdit ? 'Änderungen speichern' : 'Workflow speichern' ?></button>
</form>

<script id="modules-data" type="application/json"><?= $modules->rawModulesJson() ?></script>
<?php if ($isEdit): ?>
<script id="existing-workflow-data" type="application/json"><?= json_encode($existingWorkflow, JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_HEX_AMP) ?></script>
<?php endif; ?>
<script src="assets/typeahead.js"></script>
<script src="assets/builder.js"></script>
<?php endif; ?>

</body>
</html>
