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

$csrfToken = Csrf::token();

// The folder being shown ("" = top level); an unknown or invalid one falls back to the top.
try {
    $folder = WorkflowRepository::normalizeFolder((string) ($_GET['folder'] ?? ''));
    $listing = $workflows->listFolder($folder);
} catch (\InvalidArgumentException | \RuntimeException $e) {
    $folder = '';
    $listing = $workflows->listFolder('');
    Layout::flash('error', 'Diesen Ordner gibt es nicht - zeige den Hauptordner.');
}
$workflowList = $listing['workflows'];
$subfolders = $listing['folders'];
$allFolders = $workflows->listFolders();
$totalWorkflows = count($workflows->listAll());
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
<nav class="breadcrumb" aria-label="Ordner">
    <?php if ($folder === ''): ?>
        <strong>Hauptordner</strong>
    <?php else: ?>
        <a href="index.php">Hauptordner</a>
        <?php $segments = explode('/', $folder); $walked = ''; ?>
        <?php foreach ($segments as $i => $segment): ?>
            <?php $walked = $walked === '' ? $segment : $walked . '/' . $segment; ?>
            <span class="muted">/</span>
            <?php if ($i === count($segments) - 1): ?><strong><?= h($segment) ?></strong>
            <?php else: ?><a href="<?= h(Layout::folderUrl($walked)) ?>"><?= h($segment) ?></a><?php endif; ?>
        <?php endforeach; ?>
    <?php endif; ?>
</nav>

<div class="toolbar">
    <a class="button with-icon" href="new.php<?= $folder === '' ? '' : '?folder=' . h(rawurlencode($folder)) ?>"><?= Layout::icon('plus') ?> Workflow hier anlegen</a>
    <form method="post" action="folder.php" class="inline-form">
        <input type="hidden" name="action" value="create">
        <input type="hidden" name="folder" value="<?= h($folder) ?>">
        <?= Csrf::field() ?>
        <input type="text" name="name" placeholder="Neuer Ordner" required maxlength="60" aria-label="Name des neuen Ordners">
        <button type="submit" class="with-icon"><?= Layout::icon('folder-plus') ?> Ordner anlegen</button>
    </form>
</div>

<?php if (!empty($subfolders)): ?>
<table class="folder-table">
<tbody>
<?php foreach ($subfolders as $sub): ?>
<tr>
    <td>
        <a class="folder-name" href="<?= h(Layout::folderUrl($sub['path'])) ?>"><?= Layout::icon('folder') ?> <?= h($sub['name']) ?></a>
        <span class="muted small">
            <?= (int) $sub['workflows'] ?> Workflow<?= $sub['workflows'] === 1 ? '' : 's' ?><?= $sub['folders'] > 0 ? ', ' . (int) $sub['folders'] . ' Unterordner' : '' ?>
        </span>
    </td>
    <td class="actions">
        <details class="popover">
            <summary class="button icon-btn" title="Umbenennen" aria-label="Umbenennen"><?= Layout::icon('edit') ?></summary>
            <form method="post" action="folder.php">
                <input type="hidden" name="action" value="rename">
                <input type="hidden" name="folder" value="<?= h($folder) ?>">
                <input type="hidden" name="path" value="<?= h($sub['path']) ?>">
                <?= Csrf::field() ?>
                <label>Neuer Name <input type="text" name="name" value="<?= h($sub['name']) ?>" required maxlength="60"></label>
                <button type="submit">Umbenennen</button>
            </form>
        </details>
        <details class="popover">
            <summary class="button icon-btn" title="Verschieben" aria-label="Verschieben"><?= Layout::icon('move') ?></summary>
            <form method="post" action="folder.php">
                <input type="hidden" name="action" value="move">
                <input type="hidden" name="folder" value="<?= h($folder) ?>">
                <input type="hidden" name="path" value="<?= h($sub['path']) ?>">
                <?= Csrf::field() ?>
                <label>Verschieben nach <select name="target"><?= Layout::folderOptions($allFolders, $folder, [$sub['path']]) ?></select></label>
                <button type="submit">Verschieben</button>
            </form>
        </details>
        <form method="post" action="folder.php" class="inline" data-confirm="<?= h("Ordner „" . $sub['name'] . "\" löschen? (Das geht nur, wenn er leer ist.)") ?>"
              onsubmit="return confirm(this.dataset.confirm);">
            <input type="hidden" name="action" value="delete">
            <input type="hidden" name="folder" value="<?= h($folder) ?>">
            <input type="hidden" name="path" value="<?= h($sub['path']) ?>">
            <?= Csrf::field() ?>
            <button type="submit" class="danger icon-btn" title="Ordner löschen (nur wenn leer)" aria-label="Ordner löschen"><?= Layout::icon('trash') ?></button>
        </form>
    </td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
<?php endif; ?>

<?php if (empty($workflowList) && empty($subfolders)): ?>
    <div class="empty-state">
        <?php if ($folder === '' && $totalWorkflows === 0): ?>
        <h2>Noch keine Workflows</h2>
        <p>Ein Workflow reagiert auf etwas, das in einem Deck-Board passiert (z. B. „Karte erstellt"),
        oder läuft zu einer festen Uhrzeit - und führt dann Schritte aus, etwa einen Kommentar schreiben,
        eine Fälligkeit setzen oder eine E-Mail senden. Mit Ordnern lassen sie sich ordnen.</p>
        <p class="muted">Eine Schritt-für-Schritt-Anleitung steht in <code>TUTORIAL.md</code>.</p>
        <?php else: ?>
        <h2>Dieser Ordner ist leer</h2>
        <p>Lege hier einen Workflow oder einen Unterordner an - oder verschiebe Workflows aus einem anderen Ordner hierher.</p>
        <?php endif; ?>
    </div>
<?php elseif (!empty($workflowList)): ?>
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
        <?php if (!empty($allFolders)): ?>
        <details class="popover">
            <summary class="button icon-btn" title="In einen anderen Ordner verschieben" aria-label="Verschieben"><?= Layout::icon('move') ?></summary>
            <form method="post" action="move_workflow.php">
                <input type="hidden" name="id" value="<?= h((string) $workflow['id']) ?>">
                <input type="hidden" name="folder" value="<?= h($folder) ?>">
                <?= Csrf::field() ?>
                <label>Verschieben nach <select name="target"><?= Layout::folderOptions($allFolders, $folder) ?></select></label>
                <button type="submit">Verschieben</button>
            </form>
        </details>
        <?php endif; ?>
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
