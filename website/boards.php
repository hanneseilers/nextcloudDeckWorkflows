<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\NextcloudApi;

// Board inspection: look up the ids of boards, columns (stacks) and labels
// of a Nextcloud instance - e.g. for typing an id into a step directly or
// checking that a label really belongs to a board.
$config = Config::fromRepoRoot();
$instances = $config->instances();

$instanceName = (string) ($_GET['instance'] ?? '');
if ($instanceName === '' && count($instances) === 1) {
    $instanceName = (string) array_key_first($instances);
}
$instance = $instanceName !== '' ? $config->instance($instanceName) : null;
$boardId = ctype_digit((string) ($_GET['board'] ?? '')) ? (int) $_GET['board'] : 0;

$boards = [];
$stacks = [];
$labels = [];
$board = null;
$errors = [];

if ($instance !== null) {
    $api = new NextcloudApi($instance['url'], $instance['username'], $instance['app_password']);
    try {
        $boards = $api->listBoards();
        usort($boards, static fn (array $a, array $b) => [$a['archived'], mb_strtolower($a['title'])] <=> [$b['archived'], mb_strtolower($b['title'])]);
    } catch (\Throwable $e) {
        $errors[] = 'Boards konnten nicht geladen werden: ' . $e->getMessage();
    }
    foreach ($boards as $candidate) {
        if ($candidate['id'] === $boardId) {
            $board = $candidate;
        }
    }
    if ($board !== null) {
        // Separately, so one failing request still shows the other list.
        try {
            $stacks = $api->listStacks($boardId);
        } catch (\Throwable $e) {
            $errors[] = 'Spalten konnten nicht geladen werden: ' . $e->getMessage();
        }
        try {
            $labels = $api->listLabels($boardId);
        } catch (\Throwable $e) {
            $errors[] = 'Labels konnten nicht geladen werden: ' . $e->getMessage();
        }
    } elseif ($boardId > 0 && $errors === []) {
        $errors[] = "Board $boardId gibt es in dieser Instanz nicht (oder der Benutzer hat keinen Zugriff).";
    }
}

$boardUrl = static fn (int $id): string => 'boards.php?instance=' . rawurlencode($instanceName) . '&board=' . $id . '#board';
?>
<?php Layout::start('Boards', 'Boards', 'boards'); ?>

<p class="muted">Zeigt die Ids von Boards, Spalten und Labels - zum direkten Eintragen in einen Schritt
oder um zu prüfen, ob ein Label wirklich zum Board des Workflows gehört.</p>

<?php if ($instances === []): ?>
    <p class="notice error">Keine Nextcloud-Instanz konfiguriert - <code>config/nextcloud.yaml</code> fehlt oder ist leer.</p>
<?php else: ?>
<form method="get" class="filters">
    <label>Nextcloud-Instanz
        <select name="instance" onchange="this.form.submit()">
            <?php if ($instance === null): ?><option value="">– bitte wählen –</option><?php endif; ?>
            <?php foreach ($instances as $name => $entry): ?>
            <option value="<?= h($name) ?>" <?= $name === $instanceName ? 'selected' : '' ?>><?= h($name) ?> (<?= h($entry['url']) ?>)</option>
            <?php endforeach; ?>
        </select>
    </label>
    <button type="submit">Anzeigen</button>
</form>
<?php endif; ?>

<?php if ($instanceName !== '' && $instance === null): ?>
    <p class="notice error">Unbekannte Instanz „<?= h($instanceName) ?>".</p>
<?php endif; ?>

<?php foreach ($errors as $error): ?>
    <p class="notice error"><?= h($error) ?></p>
<?php endforeach; ?>

<?php if ($instance !== null && $boards !== []): ?>
<div class="inspect-grid">
<section>
    <h2>Boards</h2>
    <table class="inspect-table">
        <thead><tr><th>Id</th><th>Board</th></tr></thead>
        <tbody>
        <?php foreach ($boards as $entry): ?>
            <?php $classes = trim(($board !== null && $entry['id'] === $board['id'] ? 'is-selected ' : '') . ($entry['archived'] ? 'is-disabled' : '')); ?>
            <tr<?= $classes !== '' ? ' class="' . $classes . '"' : '' ?>>
                <td><code><?= $entry['id'] ?></code></td>
                <td><a href="<?= h($boardUrl($entry['id'])) ?>"><?= h($entry['title']) ?></a>
                    <?php if ($entry['archived']): ?><span class="badge badge-off">archiviert</span><?php endif; ?></td>
            </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
</section>

<section id="board">
<?php if ($board === null): ?>
    <p class="muted">Ein Board anklicken, um seine Spalten und Labels zu sehen.</p>
<?php else: ?>
    <h2><?= h($board['title']) ?> <span class="muted small">Board-Id <code><?= $board['id'] ?></code></span></h2>

    <h3>Spalten</h3>
    <?php if ($stacks === []): ?>
        <p class="muted">Keine Spalten.</p>
    <?php else: ?>
    <table class="inspect-table">
        <thead><tr><th>Id</th><th>Spalte</th><th>Karten</th></tr></thead>
        <tbody>
        <?php foreach ($stacks as $stack): ?>
            <tr><td><code><?= $stack['id'] ?></code></td><td><?= h($stack['title']) ?></td><td><?= $stack['card_count'] ?></td></tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <?php endif; ?>

    <h3>Labels</h3>
    <?php if ($labels === []): ?>
        <p class="muted">Dieses Board hat keine Labels.</p>
    <?php else: ?>
    <table class="inspect-table">
        <thead><tr><th>Id</th><th>Label</th></tr></thead>
        <tbody>
        <?php foreach ($labels as $label): ?>
            <tr><td><code><?= $label['id'] ?></code></td>
                <td><?php if (preg_match('/^[0-9a-fA-F]{6}$/', $label['color'])): ?><span class="label-swatch" style="background:#<?= h($label['color']) ?>"></span><?php endif; ?><?= h($label['title']) ?></td></tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <p class="muted small">Labels gehören immer zu genau einem Board - „Label hinzufügen" funktioniert nur mit einem Label
    vom Board der Karte.</p>
    <?php endif; ?>
<?php endif; ?>
</section>
</div>
<?php elseif ($instance !== null && $errors === []): ?>
    <p class="muted">Der Benutzer dieser Instanz hat keine Boards.</p>
<?php endif; ?>

<?php Layout::end(); ?>
