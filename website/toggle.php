<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\WorkflowRepository;

Csrf::requireValidPost();

$config = Config::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$id = (string) ($_POST['id'] ?? '');
$enabled = (bool) (int) ($_POST['enabled'] ?? '1');

try {
    $folder = $workflows->folderOf($id) ?? '';
    $workflows->setEnabled($id, $enabled);
} catch (\InvalidArgumentException $e) {
    http_response_code(400);
    echo 'Ungültige Workflow-Id.';
    exit;
}

header('Location: ' . Layout::folderUrl($folder));
