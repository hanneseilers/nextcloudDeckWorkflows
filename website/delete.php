<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\WorkflowRepository;

if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !Csrf::verify($_POST['csrf_token'] ?? null)) {
    http_response_code(400);
    echo 'Invalid request.';
    exit;
}

$config = Config::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$id = (string) ($_POST['id'] ?? '');
if ($id !== '') {
    $workflows->delete($id);
}

header('Location: index.php');
