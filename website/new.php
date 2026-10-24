<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Layout;
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

// Folders: a new workflow starts in the folder the overview was showing (?folder=),
// an existing one in its own - changing the dropdown moves it on save.
$repository = new WorkflowRepository($config->workflowsDir());
$allFolders = $repository->listFolders();
try {
    $currentFolder = $isEdit
        ? ($repository->folderOf($editId) ?? '')
        : WorkflowRepository::normalizeFolder((string) ($_GET['folder'] ?? ''));
} catch (\InvalidArgumentException $e) {
    $currentFolder = '';
}
if ($currentFolder !== '' && !in_array($currentFolder, $allFolders, true)) {
    $currentFolder = '';
}

?>
<?php Layout::start($isEdit ? 'Workflow bearbeiten' : 'Neuer Workflow', $isEdit ? 'Workflow bearbeiten: ' . (string) $existingWorkflow['name'] : 'Neuer Workflow'); ?>

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
<legend>1. Name</legend>
<label>Wie soll der Workflow heißen?
    <input type="text" id="name" required placeholder="z. B. Neue Tickets bestätigen">
</label>
<?php if (!empty($allFolders)): ?>
<label>Ordner
    <select id="folder"><?= Layout::folderOptions($allFolders, $currentFolder) ?></select>
</label>
<?php else: ?>
<input type="hidden" id="folder" value="">
<?php endif; ?>
<details class="advanced">
    <summary>Erweitert</summary>
    <label>Id (technischer Name, Dateiname in <code>workflows/</code> - wird aus dem Namen erzeugt)
        <input type="text" id="workflow-id" pattern="[a-z0-9\-]+" <?= $isEdit ? 'readonly' : '' ?>>
    </label>
</details>
</fieldset>

<fieldset>
<legend>2. Wo? Auf welchem Board</legend>

<label>Nextcloud-Instanz
    <select id="instance" required>
        <option value="">– wählen –</option>
        <?php foreach ($config->instances() as $name => $instance): ?>
        <option value="<?= h($name) ?>"><?= h($name) ?> (<?= h($instance['url']) ?>)</option>
        <?php endforeach; ?>
    </select>
</label>

<label>Board
    <span id="board-field" class="muted">– zuerst Instanz wählen –</span>
    <input type="hidden" id="board">
</label>

<label id="stack-label">Spalte (optional - leer = jede Spalte)
    <span id="stack-field" class="muted">– zuerst Board wählen –</span>
    <input type="hidden" id="stack">
</label>
</fieldset>

<fieldset>
<legend>3. Wann? Was löst den Workflow aus</legend>
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
Schritte ohne Kartenbezug (z. B. „E-Mail senden", „Zufallszahl erzeugen", „Berechnen").</p>
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
<legend>4. Was passiert? Schritte in Reihenfolge</legend>
<div class="card-info-bar">
    <button type="button" id="card-info-btn" class="icon-btn info-btn" aria-expanded="false" aria-controls="card-info"
        title="Welche Daten der auslösenden Karte kann ich verwenden?">i</button>
    <span>Daten der auslösenden Karte</span>
</div>
<div id="card-info" class="step-outputs card-info" hidden></div>
<div id="steps"></div>
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

<?php Layout::end(); ?>
