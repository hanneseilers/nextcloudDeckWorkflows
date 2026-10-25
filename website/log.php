<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\LogReader;

// The automation's log - what you would otherwise look up on the console.
$config = Config::fromRepoRoot();
$reader = new LogReader(dirname($config->stateDbPath()));
$available = $reader->available();

$file = isset($_GET['file'], LogReader::FILES[$_GET['file']]) ? (string) $_GET['file'] : 'automation';
$levelChoices = ['' => 'alles', 'WARNING' => 'Warnungen und Fehler', 'ERROR' => 'nur Fehler'];
$requestedLevel = (string) ($_GET['level'] ?? '');
$level = array_key_exists($requestedLevel, $levelChoices) ? $requestedLevel : '';
$query = mb_substr(trim((string) ($_GET['q'] ?? '')), 0, 100);
$countChoices = [100, 300, 1000];
$requested = (int) ($_GET['n'] ?? 300);
$count = in_array($requested, $countChoices, true) ? $requested : 300;
$autoRefresh = ($_GET['refresh'] ?? '') === '1';

$log = $reader->read($file, $count, $level === '' ? null : $level, $query);
?>
<?php Layout::start('Log', 'Log', 'log'); ?>

<form method="get" class="filters">
    <label>Datei
        <select name="file" onchange="this.form.submit()">
            <?php foreach (LogReader::FILES as $key => [$name, $label]): ?>
            <option value="<?= h($key) ?>" <?= $file === $key ? 'selected' : '' ?>><?= h($label) ?><?= isset($available[$key]) ? '' : ' (noch nicht vorhanden)' ?></option>
            <?php endforeach; ?>
        </select>
    </label>
    <label>Anzeigen
        <select name="level" onchange="this.form.submit()">
            <?php foreach ($levelChoices as $value => $label): ?>
            <option value="<?= h($value) ?>" <?= $level === $value ? 'selected' : '' ?>><?= h($label) ?></option>
            <?php endforeach; ?>
        </select>
    </label>
    <label>Suche
        <input type="search" name="q" value="<?= h($query) ?>" placeholder="Text, Workflow-Id, Karte …" maxlength="100">
    </label>
    <label>Einträge
        <select name="n" onchange="this.form.submit()">
            <?php foreach ($countChoices as $choice): ?>
            <option value="<?= $choice ?>" <?= $count === $choice ? 'selected' : '' ?>><?= $choice ?></option>
            <?php endforeach; ?>
        </select>
    </label>
    <label class="checkbox"><input type="checkbox" name="refresh" value="1" <?= $autoRefresh ? 'checked' : '' ?> onchange="this.form.submit()"> alle 5 s aktualisieren</label>
    <button type="submit">Aktualisieren</button>
    <?php if ($level !== '' || $query !== ''): ?><a href="log.php?file=<?= h(rawurlencode($file)) ?>">Filter zurücksetzen</a><?php endif; ?>
</form>

<?php if (!isset($available[$file])): ?>
    <p class="notice">
    <?php if ($file === 'automation'): ?>
        Noch keine Log-Datei - sie entsteht beim ersten Lauf von <code>python -m automation.main</code>
        (<code>automation/var/automation.log</code>, wird automatisch auf 1 MB begrenzt und rotiert).
    <?php else: ?>
        Keine <code>cron.log</code> gefunden - sie entsteht nur, wenn der Cron-Job seine Ausgabe dorthin umleitet
        (<code>… &gt;&gt; automation/var/cron.log 2&gt;&amp;1</code>, so schlägt es <code>install.sh</code> vor). Sie enthält auch
        Fehler, die vor dem Start des Loggings passieren, z. B. ein fehlendes Python-Paket.
    <?php endif; ?>
    </p>
<?php else: ?>
    <p class="muted small">
        <?= h($available[$file]['label']) ?> - <?= h(number_format($available[$file]['size'] / 1024, 1, ',', '.')) ?> KB,
        zuletzt geschrieben <?= Layout::dateTime(gmdate('c', $available[$file]['modified'])) ?>.
        Neueste Einträge oben; Uhrzeiten wie im Server-Log (Serverzeit).
        <?php if ($log['total'] > count($log['entries'])): ?>
            <?= count($log['entries']) ?> von <?= (int) $log['total'] ?> passenden Einträgen.
        <?php endif; ?>
    </p>
    <?php if (empty($log['entries'])): ?>
        <p><?= $level !== '' || $query !== '' ? 'Keine Einträge für diesen Filter.' : 'Die Datei ist leer.' ?></p>
    <?php else: ?>
    <div class="log-view" role="log">
    <?php foreach ($log['entries'] as $entry): ?>
        <div class="log-entry log-<?= h(strtolower($entry['level'])) ?>">
            <span class="log-time"><?= h($entry['time']) ?></span>
            <span class="log-level"><?= h($entry['level']) ?></span>
            <span class="log-text"><?= h($entry['text']) ?></span>
        </div>
    <?php endforeach; ?>
    </div>
    <?php endif; ?>
<?php endif; ?>

<?php if ($autoRefresh): ?>
<script>setTimeout(function () { location.reload(); }, 5000);</script>
<?php endif; ?>

<?php Layout::end(); ?>
