<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\ModuleRegistry;

$config = Config::fromRepoRoot();
$modules = ModuleRegistry::fromRepoRoot();

function h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}

// Same four event types automation/core/domain/models.py::EventType defines.
$eventTypes = [
    'card_created' => 'Karte erstellt',
    'card_moved' => 'Karte verschoben',
    'card_updated' => 'Karte geändert',
    'card_deleted' => 'Karte gelöscht',
];
?>
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Neuer Workflow — Nextcloud Deck Workflows</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header>
    <h1>Neuer Workflow</h1>
    <a href="index.php">&larr; Übersicht</a>
</header>

<?php if (empty($config->instances())): ?>
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
    <select id="board" disabled required>
        <option value="">– zuerst Instanz wählen –</option>
    </select>
</label>

<label>Spalte
    <select id="stack" disabled required>
        <option value="">– zuerst Board wählen –</option>
    </select>
</label>
</fieldset>

<fieldset>
<legend>Wann?</legend>
<label>Event
    <select id="event-type" required>
        <?php foreach ($eventTypes as $value => $label): ?>
        <option value="<?= h($value) ?>"><?= h($label) ?></option>
        <?php endforeach; ?>
    </select>
</label>
</fieldset>

<fieldset>
<legend>Workflow</legend>
<label>Name
    <input type="text" id="name" required>
</label>
<label>Id (technischer Name, Dateiname in <code>workflows/</code>)
    <input type="text" id="workflow-id" pattern="[a-z0-9\-]+" required>
</label>
</fieldset>

<fieldset>
<legend>Was passiert? (Module in Reihenfolge)</legend>
<div id="steps"></div>
<button type="button" id="add-step">+ Schritt hinzufügen</button>
</fieldset>

<button type="submit" class="button">Workflow speichern</button>
</form>

<script id="modules-data" type="application/json"><?= $modules->rawModulesJson() ?></script>
<script src="assets/builder.js"></script>
<?php endif; ?>

</body>
</html>
