<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\WorkflowRepository;

// POST: moves one workflow into another folder (the overview's "Verschieben").
Csrf::requireValidPost();

$workflows = new WorkflowRepository(Config::fromRepoRoot()->workflowsDir());
$id = (string) ($_POST['id'] ?? '');
$back = '';

try {
    $back = WorkflowRepository::normalizeFolder((string) ($_POST['folder'] ?? ''));
    $target = WorkflowRepository::normalizeFolder((string) ($_POST['target'] ?? ''));
    $workflow = $workflows->get($id);
    if ($workflow === null) {
        throw new \RuntimeException("Workflow '$id' nicht gefunden.");
    }
    $workflows->moveWorkflow($id, $target);
    Layout::flash('ok', "'" . ($workflow['name'] ?? $id) . "' verschoben nach " . ($target === '' ? 'Hauptordner' : "'" . $target . "'") . '.');
} catch (\InvalidArgumentException | \RuntimeException $e) {
    Layout::flash('error', $e->getMessage());
}

header('Location: ' . Layout::folderUrl($back));
