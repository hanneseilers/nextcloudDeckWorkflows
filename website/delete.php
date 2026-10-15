<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\WorkflowRepository;

Csrf::requireValidPost();

$config = Config::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$id = (string) ($_POST['id'] ?? '');
if ($id !== '') {
    try {
        $workflows->delete($id);
    } catch (\InvalidArgumentException $e) {
        http_response_code(400);
        echo 'Ungültige Workflow-Id.';
        exit;
    }
}

header('Location: index.php');
