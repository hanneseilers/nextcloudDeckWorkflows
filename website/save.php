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

// Optional: an empty/missing stack_id means "any column on this board",
// matching Trigger.stack_id = None on the Python side.
$stackId = null;
if (($payload['stack_id'] ?? null) !== null && $payload['stack_id'] !== '') {
    $stackId = filter_var($payload['stack_id'], FILTER_VALIDATE_INT);
    if ($stackId === false || $stackId <= 0) {
        $errors[] = "Ungültige Spalten-Id '" . h((string) $payload['stack_id']) . "'.";
    }
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

/** Recursively validates/normalizes a step list, including nested if/then/else. */
function processSteps(array $steps, ModuleRegistry $modules, array &$errors, array &$seenStepIds): array
{
    $knownOps = ['eq', 'ne', 'lt', 'gt', 'contains', 'beginswith', 'endswith'];
    $result = [];

    foreach ($steps as $index => $step) {
        if (($step['type'] ?? null) === 'if') {
            $condition = is_array($step['condition'] ?? null) ? $step['condition'] : [];
            $op = (string) ($condition['op'] ?? '');
            if (!in_array($op, $knownOps, true)) {
                $errors[] = 'Schritt ' . ($index + 1) . ": unbekannter Vergleichsoperator '$op'.";
            }
            $result[] = [
                'type' => 'if',
                'condition' => [
                    'left' => $condition['left'] ?? null,
                    'op' => $op,
                    'right' => $condition['right'] ?? null,
                ],
                'then' => processSteps(is_array($step['then'] ?? null) ? $step['then'] : [], $modules, $errors, $seenStepIds),
                'else' => processSteps(is_array($step['else'] ?? null) ? $step['else'] : [], $modules, $errors, $seenStepIds),
            ];
            continue;
        }

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

        $entry = ['module' => $moduleName];
        if ($stepId !== '') {
            $entry['id'] = $stepId;
        }
        $entry['params'] = is_array($step['params'] ?? null) ? $step['params'] : [];
        $result[] = $entry;
    }

    return $result;
}

$steps = $payload['steps'] ?? null;
if (!is_array($steps) || count($steps) === 0) {
    $errors[] = 'Bitte mindestens einen Schritt hinzufügen.';
    $steps = [];
}

$seenStepIds = [];
$actions = processSteps($steps, $modules, $errors, $seenStepIds);

if (!empty($errors)) {
    fail($errors);
}

$trigger = ['event' => $event];
if ($stackId !== null) {
    $trigger['stack_id'] = $stackId;
}

$workflow = [
    'id' => $id,
    'name' => $name,
    'enabled' => true,
    'nextcloud_instance' => $instanceName,
    'board_id' => $boardId,
    'trigger' => $trigger,
    'actions' => $actions,
];

$workflows->save($workflow);

header('Location: index.php');
