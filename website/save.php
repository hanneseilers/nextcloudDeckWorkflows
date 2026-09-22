<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\ModuleRegistry;
use NextcloudDeckWorkflows\WorkflowRepository;

function h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}

function fail(array $errors): void
{
    http_response_code(400);
    echo '<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">'
        . '<title>Workflow konnte nicht gespeichert werden</title>'
        . '<link rel="stylesheet" href="assets/style.css"></head><body>'
        . '<header><h1>Workflow konnte nicht gespeichert werden</h1></header>'
        . '<div class="notice error"><ul>';
    foreach ($errors as $error) {
        echo '<li>' . h($error) . '</li>';
    }
    echo '</ul></div><p><a href="new.php">&larr; Zurück und erneut versuchen</a></p></body></html>';
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !Csrf::verify($_POST['csrf_token'] ?? null)) {
    fail(['Ungültige Anfrage (CSRF-Token fehlt oder abgelaufen).']);
}

$payload = json_decode((string) ($_POST['payload'] ?? ''), true);
if (!is_array($payload)) {
    fail(['Kein gültiges Formular-Payload empfangen.']);
}

$config = Config::fromRepoRoot();
$modules = ModuleRegistry::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$errors = [];
$knownEvents = ['card_created', 'card_moved', 'card_updated', 'card_deleted'];

$instanceName = (string) ($payload['instance'] ?? '');
if ($config->instance($instanceName) === null) {
    $errors[] = "Unbekannte Nextcloud-Instanz '$instanceName'.";
}

$event = (string) ($payload['event'] ?? '');
if (!in_array($event, $knownEvents, true)) {
    $errors[] = "Unbekanntes Event '$event'.";
}

$boardId = filter_var($payload['board_id'] ?? null, FILTER_VALIDATE_INT);
if ($boardId === false || $boardId === null || $boardId <= 0) {
    $errors[] = 'Bitte ein Board auswählen.';
}

$stackId = filter_var($payload['stack_id'] ?? null, FILTER_VALIDATE_INT);
if ($stackId === false || $stackId === null || $stackId <= 0) {
    $errors[] = 'Bitte eine Spalte auswählen.';
}

$name = trim((string) ($payload['name'] ?? ''));
if ($name === '') {
    $errors[] = 'Bitte einen Namen angeben.';
}

$id = trim((string) ($payload['id'] ?? ''));
if (!preg_match('/^[a-z0-9\-]+$/', $id)) {
    $errors[] = "Ungültige Workflow-Id '$id' (nur a-z, 0-9 und -).";
} elseif ($workflows->exists($id)) {
    $errors[] = "Ein Workflow mit der Id '$id' existiert bereits.";
}

$steps = $payload['steps'] ?? null;
if (!is_array($steps) || count($steps) === 0) {
    $errors[] = 'Bitte mindestens einen Schritt hinzufügen.';
    $steps = [];
}

$actions = [];
$seenStepIds = [];
foreach ($steps as $index => $step) {
    $moduleName = (string) ($step['module'] ?? '');
    if ($modules->get($moduleName) === null) {
        $errors[] = 'Schritt ' . ($index + 1) . ": unbekanntes Modul '$moduleName'.";
        continue;
    }

    $stepId = trim((string) ($step['id'] ?? ''));
    if ($stepId !== '') {
        if (isset($seenStepIds[$stepId])) {
            $errors[] = "Schritt-Id '$stepId' wird mehrfach verwendet.";
        }
        $seenStepIds[$stepId] = true;
    }

    $params = is_array($step['params'] ?? null) ? $step['params'] : [];

    $entry = ['module' => $moduleName];
    if ($stepId !== '') {
        $entry['id'] = $stepId;
    }
    $entry['params'] = $params;
    $actions[] = $entry;
}

if (!empty($errors)) {
    fail($errors);
}

$workflow = [
    'id' => $id,
    'name' => $name,
    'enabled' => true,
    'nextcloud_instance' => $instanceName,
    'board_id' => $boardId,
    'trigger' => ['event' => $event, 'stack_id' => $stackId],
    'actions' => $actions,
];

$workflows->save($workflow);

header('Location: index.php');
