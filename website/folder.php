<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\WorkflowRepository;

// POST: folder actions of the overview - create, rename, move, delete.
Csrf::requireValidPost();

$workflows = new WorkflowRepository(Config::fromRepoRoot()->workflowsDir());
$action = (string) ($_POST['action'] ?? '');
$current = (string) ($_POST['folder'] ?? ''); // the folder the overview was showing
$target = '';

try {
    $current = WorkflowRepository::normalizeFolder($current);
    $target = $current;
    switch ($action) {
        case 'create':
            $path = $workflows->createFolder($current, (string) ($_POST['name'] ?? ''));
            Layout::flash('ok', "Ordner '" . basename($path) . "' angelegt.");
            break;
        case 'rename':
            $path = WorkflowRepository::normalizeFolder((string) ($_POST['path'] ?? ''));
            $new = $workflows->renameFolder($path, (string) ($_POST['name'] ?? ''));
            // Standing inside (or below) the renamed folder: follow it.
            if ($current === $path || str_starts_with($current, $path . '/')) {
                $target = $new . substr($current, strlen($path));
            }
            Layout::flash('ok', "Ordner umbenannt in '" . basename($new) . "'.");
            break;
        case 'move':
            $path = WorkflowRepository::normalizeFolder((string) ($_POST['path'] ?? ''));
            $new = $workflows->moveFolder($path, (string) ($_POST['target'] ?? ''));
            if ($current === $path || str_starts_with($current, $path . '/')) {
                $target = $new . substr($current, strlen($path));
            }
            Layout::flash('ok', "Ordner '" . basename($new) . "' verschoben.");
            break;
        case 'delete':
            $path = WorkflowRepository::normalizeFolder((string) ($_POST['path'] ?? ''));
            $workflows->deleteFolder($path);
            if ($current === $path || str_starts_with($current, $path . '/')) {
                $target = str_contains($path, '/') ? dirname($path) : '';
            }
            Layout::flash('ok', "Ordner '" . basename($path) . "' gelöscht.");
            break;
        default:
            http_response_code(400);
            echo 'Unbekannte Aktion.';
            exit;
    }
} catch (\InvalidArgumentException | \RuntimeException $e) {
    Layout::flash('error', $e->getMessage());
}

header('Location: ' . Layout::folderUrl($target));
