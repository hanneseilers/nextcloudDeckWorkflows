<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\TemplateStore;

// JSON: the subject and text of one template, for the "i" next to a step's
// "Textvorlage" in the workflow editor. Read only.
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$store = TemplateStore::fromRepoRoot();
$name = trim((string) ($_GET['name'] ?? ''));
$template = TemplateStore::validName($name) ? $store->read($name) : null;

if ($template === null) {
    http_response_code(404);
    echo json_encode(['error' => 'Die Vorlage gibt es nicht (mehr).']);
    exit;
}

echo json_encode(
    ['name' => $template['name']] + TemplateStore::splitEmail($template['content']),
    JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
);
