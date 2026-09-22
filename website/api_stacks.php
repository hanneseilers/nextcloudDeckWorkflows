<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\NextcloudApi;

header('Content-Type: application/json');

$config = Config::fromRepoRoot();
$instanceName = (string) ($_GET['instance'] ?? '');
$boardId = (int) ($_GET['board_id'] ?? 0);
$instance = $config->instance($instanceName);

if ($instance === null || $boardId <= 0) {
    http_response_code(400);
    echo json_encode(['error' => 'Missing or unknown instance/board_id']);
    exit;
}

try {
    $api = new NextcloudApi($instance['url'], $instance['username'], $instance['app_password']);
    echo json_encode(['stacks' => $api->listStacks($boardId)]);
} catch (\Throwable $e) {
    http_response_code(502);
    echo json_encode(['error' => 'Could not reach Nextcloud: ' . $e->getMessage()]);
}
