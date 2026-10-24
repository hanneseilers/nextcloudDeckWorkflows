<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\TemplateStore;
use NextcloudDeckWorkflows\WorkflowRepository;

// POST: the actions of the "Vorlagen" page - create, save, rename, delete.
Csrf::requireValidPost();

$store = TemplateStore::fromRepoRoot();
$workflows = new WorkflowRepository(Config::fromRepoRoot()->workflowsDir());
$action = (string) ($_POST['action'] ?? '');
$name = trim((string) ($_POST['name'] ?? ''));
$subject = (string) ($_POST['subject'] ?? '');
$body = (string) ($_POST['body'] ?? '');

$templateUrl = static fn (string $name): string => 'templates.php' . ($name === '' ? '' : '?name=' . rawurlencode($name));
$target = $templateUrl($name);

try {
    switch ($action) {
        case 'create':
            $target = 'templates.php?new=1';
            $store->create($name, TemplateStore::joinEmail($subject, $body));
            Layout::flash('ok', "Vorlage '$name' angelegt.");
            $target = $templateUrl($name);
            break;

        case 'save':
            // Someone else (or another tab) saved it since this form was loaded: don't overwrite blindly.
            $current = $store->read($name);
            if ($current !== null && !hash_equals($current['version'], (string) ($_POST['version'] ?? ''))) {
                throw new \RuntimeException(
                    "Die Vorlage '$name' wurde inzwischen geändert (anderer Tab?). Dein Text steht noch im Feld - "
                    . 'bitte die Seite neu laden, vergleichen und erneut speichern.'
                );
            }
            $store->save($name, TemplateStore::joinEmail($subject, $body));
            Layout::flash('ok', "Vorlage '$name' gespeichert.");
            break;

        case 'rename':
            $new = trim((string) ($_POST['new_name'] ?? ''));
            $used = $store->usages($workflows, $name);
            $store->rename($name, $new);
            $message = "Vorlage '$name' heißt jetzt '$new'.";
            if ($used !== [] && $name !== $new) {
                if (($_POST['update_references'] ?? '') === '1') {
                    $count = $store->renameReferences($workflows, $name, $new);
                    $message .= " $count Workflow" . ($count === 1 ? '' : 's') . ' angepasst.';
                } else {
                    $message .= ' Achtung: ' . count($used) . ' Workflow' . (count($used) === 1 ? '' : 's')
                        . " verwenden noch den alten Namen '$name'.";
                }
            }
            Layout::flash('ok', $message);
            $target = $templateUrl($new);
            break;

        case 'delete':
            $used = $store->usages($workflows, $name);
            if ($used !== []) {
                throw new \RuntimeException(
                    "Die Vorlage '$name' wird noch verwendet (" . implode(', ', array_column($used, 'name'))
                    . ') - dort zuerst eine andere Vorlage wählen.'
                );
            }
            $store->delete($name);
            Layout::flash('ok', "Vorlage '$name' gelöscht.");
            $target = 'templates.php';
            break;

        default:
            http_response_code(400);
            echo 'Unbekannte Aktion.';
            exit;
    }
} catch (\InvalidArgumentException | \RuntimeException $e) {
    Layout::flash('error', $e->getMessage());
    if ($action === 'create' || $action === 'save') {
        // Keep what was typed - a long text must not be lost over a typo in the name.
        $_SESSION['template_draft'] = ['name' => $name, 'new' => $action === 'create', 'subject' => $subject, 'body' => $body];
    }
}

header('Location: ' . $target);
