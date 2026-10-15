<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\WorkflowRepository;

Csrf::requireValidPost();

$config = Config::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$id = (string) ($_POST['id'] ?? '');
try {
    $original = $id !== '' ? $workflows->get($id) : null;
} catch (\InvalidArgumentException $e) {
    http_response_code(400);
    echo 'Ungültige Workflow-Id.';
    exit;
}

if ($original === null) {
    header('Location: index.php');
    exit;
}

// "<id>-kopie", then "-kopie-2", "-kopie-3", ... until a free id is found.
$newId = $original['id'] . '-kopie';
$suffix = 2;
while ($workflows->exists($newId)) {
    $newId = $original['id'] . '-kopie-' . $suffix;
    $suffix++;
}

$copy = $original;
$copy['id'] = $newId;
$copy['name'] = ($original['name'] ?? $original['id']) . ' (Kopie)';
// A duplicate must not silently go live with the exact same trigger as the
// original - force it off so the person can adjust (board/column/...)
// before enabling it themselves.
$copy['enabled'] = false;

$workflows->save($copy);

header('Location: new.php?id=' . urlencode($newId));
