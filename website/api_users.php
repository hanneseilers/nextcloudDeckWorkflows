<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\NextcloudApi;

header('Content-Type: application/json');

$config = Config::fromRepoRoot();
$instanceName = (string) ($_GET['instance'] ?? '');
$query = trim((string) ($_GET['query'] ?? ''));
$instance = $config->instance($instanceName);

if ($instance === null) {
    http_response_code(400);
    echo json_encode(['error' => "Unknown Nextcloud instance '$instanceName'"]);
    exit;
}

// Mirrors the builder's own 3-character throttle - also enforced here so a
// request bypassing the browser can't trigger a (likely huge) unfiltered
// user listing.
if (mb_strlen($query) < 3) {
    echo json_encode(['users' => []]);
    exit;
}

try {
    $api = new NextcloudApi($instance['url'], $instance['username'], $instance['app_password']);
    echo json_encode(['users' => $api->searchUsers($query)]);
} catch (\Throwable $e) {
    http_response_code(502);
    echo json_encode(['error' => 'Could not reach Nextcloud: ' . $e->getMessage()]);
}
