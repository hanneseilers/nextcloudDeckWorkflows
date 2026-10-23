<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\EventTypes;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\ModuleRegistry;
use NextcloudDeckWorkflows\WorkflowRepository;

$config = Config::fromRepoRoot();
$modules = ModuleRegistry::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

$workflowList = $workflows->listAll();
$csrfToken = Csrf::token();
?>
<?php Layout::start('Übersicht', 'Workflows', 'index'); ?>

<?php if (empty($config->instances())): ?>
    <p class="notice">Keine Nextcloud-Instanz konfiguriert. Lege <code>config/nextcloud.yaml</code> an
    (Vorlage: <code>config/nextcloud.example.yaml</code>).</p>
<?php endif; ?>

<?php if (!$modules->isAvailable()): ?>
    <p class="notice">Noch keine Modul-Liste gefunden. Führe einmal
    <code>python -m automation.main --list-modules</code> aus, oder warte auf den nächsten Cron-Lauf
    (schreibt automatisch <code>automation/var/modules.json</code>).</p>
<?php endif; ?>

<?php
$multipleInstances = count($config->instances()) > 1;
$moduleLabel = static fn (string $name): string => (string) ($modules->get($name)['label'] ?? $name);
// "Kommentar hinzufügen → Wenn/Sonst → …" - the workflow at a glance.
$summarize = static function (array $steps) use ($moduleLabel): string {
    $parts = array_map(
        static fn ($step) => is_array($step) && ($step['type'] ?? null) === 'if' ? 'Wenn/Sonst' : $moduleLabel((string) ($step['module'] ?? '?')),
        $steps
    );
    return $parts === [] ? 'keine Schritte' : implode(' → ', $parts);
};
?>
<?php if (empty($workflowList)): ?>
    <div class="empty-state">
        <h2>Noch keine Workflows</h2>
        <p>Ein Workflow reagiert auf etwas, das in einem Deck-Board passiert (z. B. „Karte erstellt"),
        oder läuft zu einer festen Uhrzeit - und führt dann Schritte aus, etwa einen Kommentar schreiben,
        eine Fälligkeit setzen oder eine E-Mail senden.</p>
        <p><a class="button with-icon" href="new.php"><?= Layout::icon('plus') ?> Ersten Workflow anlegen</a></p>
        <p class="muted">Eine Schritt-für-Schritt-Anleitung steht in <code>TUTORIAL.md</code>.</p>
    </div>
<?php else: ?>
<table class="workflow-table">
<thead>
<tr>
    <th>Workflow</th>
    <th>Board</th>
    <th>Wann</th>
    <th>Status</th>
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
        $column = $workflow['stack_title'] ?? (isset($trigger['stack_id']) ? 'Spalte ' . $trigger['stack_id'] : null);
        $triggerLabel = h(EventTypes::label((string) ($trigger['event'] ?? '?')))
            . ($column !== null ? ' <span class="muted">in „' . h((string) $column) . '"</span>' : '');
    }
    $enabled = (bool) ($workflow['enabled'] ?? true);
    $name = (string) ($workflow['name'] ?? $workflow['id']);
    $board = (string) ($workflow['board_title'] ?? ('Board ' . ($workflow['board_id'] ?? '?')));
?>
<tr class="<?= $enabled ? '' : 'is-disabled' ?>">
    <td>
        <a class="workflow-name" href="new.php?id=<?= urlencode((string) $workflow['id']) ?>"><?= h($name) ?></a>
        <div class="muted small"><?= h($summarize($workflow['actions'] ?? [])) ?></div>
    </td>
    <td><?= h($board) ?><?php if ($multipleInstances): ?> <span class="muted small">(<?= h((string) ($workflow['nextcloud_instance'] ?? '')) ?>)</span><?php endif; ?></td>
    <td><?= $triggerLabel ?></td>
    <td><span class="badge <?= $enabled ? 'badge-on' : 'badge-off' ?>"><?= $enabled ? 'aktiv' : 'pausiert' ?></span></td>
    <td class="actions">
        <a class="button icon-btn" title="Bearbeiten" aria-label="Bearbeiten" href="new.php?id=<?= urlencode((string) $workflow['id']) ?>"><?= Layout::icon('edit') ?></a>
        <a class="button icon-btn" title="Testlauf" aria-label="Testlauf" href="test_run.php?workflow_id=<?= urlencode((string) $workflow['id']) ?>"><?= Layout::icon('play') ?></a>
        <form method="post" action="duplicate.php" class="inline">
            <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
            <?= Csrf::field() ?>
            <button type="submit" class="icon-btn" title="Duplizieren" aria-label="Duplizieren"><?= Layout::icon('copy') ?></button>
        </form>
        <form method="post" action="toggle.php" class="inline">
            <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
            <input type="hidden" name="enabled" value="<?= $enabled ? '0' : '1' ?>">
            <?= Csrf::field() ?>
            <?php $toggleLabel = $enabled ? 'Pausieren' : 'Aktivieren'; ?>
            <button type="submit" class="icon-btn <?= $enabled ? 'is-on' : 'is-off' ?>" title="<?= $toggleLabel ?>" aria-label="<?= $toggleLabel ?>"><?= Layout::icon('power') ?></button>
        </form>
        <form method="post" action="delete.php" class="inline" data-confirm="<?= h('Workflow „' . $name . '" wirklich löschen?') ?>"
              onsubmit="return confirm(this.dataset.confirm);">
            <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
            <?= Csrf::field() ?>
            <button type="submit" class="danger icon-btn" title="Löschen" aria-label="Löschen"><?= Layout::icon('trash') ?></button>
        </form>
    </td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
<?php endif; ?>

<?php Layout::end(); ?>
