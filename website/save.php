<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\EventTypes;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\ModuleRegistry;
use NextcloudDeckWorkflows\WorkflowRepository;


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
$modules->refreshIfStale(); // an outdated list (after an update) is renewed in the background
$workflows = new WorkflowRepository($config->workflowsDir());

$errors = [];
$knownEvents = array_keys(EventTypes::labels());

$instanceName = (string) ($payload['instance'] ?? '');
if ($config->instance($instanceName) === null) {
    $errors[] = "Unbekannte Nextcloud-Instanz '$instanceName'.";
}

$boardId = filter_var($payload['board_id'] ?? null, FILTER_VALIDATE_INT);
if ($boardId === false || $boardId === null || $boardId <= 0) {
    $errors[] = 'Bitte ein Board auswählen.';
}

// Exactly one of the two trigger shapes - event (+ optional stack_id) or
// schedule (time + optional weekdays) - matching Trigger on the Python side.
$event = null;
$stackId = null;
$schedule = null;

if (is_array($payload['schedule'] ?? null)) {
    $time = (string) ($payload['schedule']['time'] ?? '');
    if (!preg_match('/^([01]\d|2[0-3]):[0-5]\d$/', $time)) {
        $errors[] = "Ungültige Uhrzeit '$time' (erwartet HH:MM).";
    }
    $weekdays = array_values(array_filter(
        array_map('intval', is_array($payload['schedule']['weekdays'] ?? null) ? $payload['schedule']['weekdays'] : []),
        static fn (int $day) => $day >= 1 && $day <= 7
    ));
    $schedule = ['time' => $time];
    if ($weekdays !== []) {
        $schedule['weekdays'] = $weekdays;
    }
} else {
    $event = (string) ($payload['event'] ?? '');
    if (!in_array($event, $knownEvents, true)) {
        $errors[] = "Unbekanntes Event '$event'.";
    }

    // Optional: an empty/missing stack_id means "any column on this board",
    // matching Trigger.stack_id = None on the Python side.
    if (($payload['stack_id'] ?? null) !== null && $payload['stack_id'] !== '') {
        $stackId = filter_var($payload['stack_id'], FILTER_VALIDATE_INT);
        if ($stackId === false || $stackId <= 0) {
            $errors[] = "Ungültige Spalten-Id '" . h((string) $payload['stack_id']) . "'.";
        }
    }
}

$name = trim((string) ($payload['name'] ?? ''));
if ($name === '') {
    $errors[] = 'Bitte einen Namen angeben.';
}

// "edit" (an existing workflow's own form resubmits its own id, and must be
// allowed to overwrite it) vs "create" (default - a new, not-yet-used id).
$mode = (string) ($payload['mode'] ?? 'create');
$existing = null;

$id = trim((string) ($payload['id'] ?? ''));
if (!preg_match('/^[a-z0-9\-]+$/', $id)) {
    $errors[] = "Ungültige Workflow-Id '$id' (nur a-z, 0-9 und -).";
} elseif ($mode === 'edit') {
    $existing = $workflows->get($id);
    if ($existing === null) {
        $errors[] = "Workflow '$id' existiert nicht (kann nicht bearbeitet werden).";
    }
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
            $errors[] = 'Schritt ' . ($index + 1) . ": unbekanntes Modul '$moduleName'."
                . (!$modules->isFresh()
                    ? ' Die Modulliste ist veraltet (die Software wurde aktualisiert) und wird gerade erneuert - bitte in ein paar Sekunden noch einmal speichern.'
                    : '');
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

if ($schedule !== null) {
    $trigger = ['schedule' => $schedule];
} else {
    $trigger = ['event' => $event];
    if ($stackId !== null) {
        $trigger['stack_id'] = $stackId;
    }
}

$workflow = [
    'id' => $id,
    'name' => $name,
    // Editing a workflow must not silently re-enable/disable it - keep
    // whatever it already was. A brand new one starts enabled.
    'enabled' => $existing['enabled'] ?? true,
    'nextcloud_instance' => $instanceName,
    'board_id' => $boardId,
    'trigger' => $trigger,
    'actions' => $actions,
];

// Display-only names (shown in the overview instead of bare ids, without a
// Nextcloud request per page view); the automation ignores them.
foreach (['board_title' => $payload['board_title'] ?? null, 'stack_title' => $payload['stack_title'] ?? null] as $key => $title) {
    if (is_string($title) && trim($title) !== '') {
        $workflow[$key] = mb_substr(trim($title), 0, 200);
    }
}

// Folder: where a new workflow is created, or - for an existing one whose
// folder dropdown was changed - where it moves to. Absent = keep.
$folder = isset($payload['folder']) ? (string) $payload['folder'] : null;
try {
    $workflows->save($workflow, $folder);
} catch (\InvalidArgumentException | \RuntimeException $e) {
    fail([$e->getMessage()]);
}

header('Location: ' . Layout::folderUrl($workflows->folderOf($id) ?? ''));
