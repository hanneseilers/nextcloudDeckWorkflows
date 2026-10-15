<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\EventTypes;
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

// Feather-style line icons; the German text lives only in title/aria-label.
function icon(string $name): string
{
    $paths = [
        'edit' => '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
        'play' => '<polygon points="5 3 19 12 5 21 5 3"/>',
        'copy' => '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
        'power' => '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>',
        'activity' => '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
        'clock' => '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        'plus' => '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
        'trash' => '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    ];
    return '<svg class="icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
        . 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' . $paths[$name] . '</svg>';
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
    <div>
        <a class="button with-icon" href="health.php"><?= icon('activity') ?> Status</a>
        <a class="button with-icon" href="history.php"><?= icon('clock') ?> Historie</a>
        <a class="button with-icon" href="new.php"><?= icon('plus') ?> Neuer Workflow</a>
    </div>
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
    if (isset($trigger['schedule'])) {
        $weekdayNames = ['', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
        $weekdays = $trigger['schedule']['weekdays'] ?? [];
        $triggerLabel = 'Zeitplan ' . h((string) ($trigger['schedule']['time'] ?? '?'))
            . ($weekdays !== [] ? ' (' . h(implode(',', array_map(fn ($d) => $weekdayNames[$d] ?? $d, $weekdays))) . ')' : ' (täglich)');
    } else {
        $triggerLabel = h(EventTypes::label((string) ($trigger['event'] ?? '?')))
            . (isset($trigger['stack_id']) ? ' (Spalte ' . h((string) $trigger['stack_id']) . ')' : '');
    }
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
        <a class="button icon-btn" title="Bearbeiten" aria-label="Bearbeiten" href="new.php?id=<?= urlencode((string) $workflow['id']) ?>"><?= icon('edit') ?></a>
        <a class="button icon-btn" title="Testlauf" aria-label="Testlauf" href="test_run.php?workflow_id=<?= urlencode((string) $workflow['id']) ?>"><?= icon('play') ?></a>
        <form method="post" action="duplicate.php" class="inline">
            <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
            <?= Csrf::field() ?>
            <button type="submit" class="icon-btn" title="Duplizieren" aria-label="Duplizieren"><?= icon('copy') ?></button>
        </form>
        <form method="post" action="toggle.php" class="inline">
            <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
            <input type="hidden" name="enabled" value="<?= $enabled ? '0' : '1' ?>">
            <?= Csrf::field() ?>
            <?php $toggleLabel = $enabled ? 'Deaktivieren' : 'Aktivieren'; ?>
            <button type="submit" class="icon-btn <?= $enabled ? 'is-on' : 'is-off' ?>" title="<?= $toggleLabel ?>" aria-label="<?= $toggleLabel ?>"><?= icon('power') ?></button>
        </form>
        <form method="post" action="delete.php" class="inline"
              onsubmit="return confirm('Workflow \'<?= h((string) $workflow['id']) ?>\' wirklich löschen?');">
            <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
            <?= Csrf::field() ?>
            <button type="submit" class="danger icon-btn" title="Löschen" aria-label="Löschen"><?= icon('trash') ?></button>
        </form>
    </td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
<?php endif; ?>

</body>
</html>
