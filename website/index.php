<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\ModuleRegistry;
use NextcloudDeckWorkflows\WorkflowRepository;

$config = Config::fromRepoRoot();
$modules = ModuleRegistry::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$workflowList = $workflows->listAll();
$csrfToken = Csrf::token();

function h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}
?>
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Nextcloud Deck Workflows</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header>
    <h1>Nextcloud Deck Workflows</h1>
    <a class="button" href="new.php">+ Neuer Workflow</a>
</header>

<?php if (empty($config->instances())): ?>
    <p class="notice">Keine Nextcloud-Instanz konfiguriert. Lege <code>config/nextcloud.yaml</code> an
    (Vorlage: <code>config/nextcloud.example.yaml</code>).</p>
<?php endif; ?>

<?php if (!$modules->isAvailable()): ?>
    <p class="notice">Noch keine Modul-Liste gefunden. Führe einmal
    <code>python -m automation.main --list-modules</code> aus, oder warte auf den nächsten Cron-Lauf
    (schreibt automatisch <code>automation/var/modules.json</code>).</p>
<?php endif; ?>

<?php if (empty($workflowList)): ?>
    <p>Noch keine Workflows angelegt.</p>
<?php else: ?>
<table>
<thead>
<tr>
    <th>Name</th>
    <th>Instanz</th>
    <th>Board</th>
    <th>Trigger</th>
    <th>Schritte</th>
    <th>Aktiv</th>
    <th></th>
</tr>
</thead>
<tbody>
<?php foreach ($workflowList as $workflow): ?>
<?php
    $trigger = $workflow['trigger'] ?? [];
    $triggerLabel = h((string) ($trigger['event'] ?? '?'))
        . (isset($trigger['stack_id']) ? ' (Spalte ' . h((string) $trigger['stack_id']) . ')' : '');
    $stepCount = count($workflow['actions'] ?? []);
    $enabled = (bool) ($workflow['enabled'] ?? true);
?>
<tr>
    <td><?= h((string) ($workflow['name'] ?? $workflow['id'])) ?></td>
    <td><?= h((string) ($workflow['nextcloud_instance'] ?? '')) ?></td>
    <td><?= h((string) ($workflow['board_id'] ?? '')) ?></td>
    <td><?= $triggerLabel ?></td>
    <td><?= $stepCount ?></td>
    <td><?= $enabled ? 'ja' : 'nein' ?></td>
    <td class="actions">
        <form method="post" action="toggle.php" class="inline">
            <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
            <input type="hidden" name="enabled" value="<?= $enabled ? '0' : '1' ?>">
            <?= Csrf::field() ?>
            <button type="submit"><?= $enabled ? 'Deaktivieren' : 'Aktivieren' ?></button>
        </form>
        <form method="post" action="delete.php" class="inline"
              onsubmit="return confirm('Workflow \'<?= h((string) $workflow['id']) ?>\' wirklich löschen?');">
            <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
            <?= Csrf::field() ?>
            <button type="submit" class="danger">Löschen</button>
        </form>
    </td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
<?php endif; ?>

</body>
</html>
