<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\NextcloudApi;

header('Content-Type: application/json');

$config = Config::fromRepoRoot();
$instanceName = (string) ($_GET['instance'] ?? '');
$instance = $config->instance($instanceName);

if ($instance === null) {
    http_response_code(400);
    echo json_encode(['error' => "Unknown Nextcloud instance '$instanceName'"]);
    exit;
}

try {
    $api = new NextcloudApi($instance['url'], $instance['username'], $instance['app_password']);
    echo json_encode(['calendars' => $api->listCalendars()]);
} catch (\Throwable $e) {
    http_response_code(502);
    echo json_encode(['error' => 'Could not reach Nextcloud: ' . $e->getMessage()]);
}
