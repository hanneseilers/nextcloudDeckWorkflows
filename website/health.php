<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\HealthStatus;
use NextcloudDeckWorkflows\WorkflowRepository;

$config = Config::fromRepoRoot();
$health = new HealthStatus($config->stateDbPath(), $config->cronIntervalMinutes());

// execution_log.created_at is written in UTC (Python's datetime.now(timezone.utc))
// - compute the cutoff in UTC too, independent of this PHP installation's
// default timezone.
$sinceIso = (new DateTimeImmutable('now', new DateTimeZone('UTC')))->modify('-24 hours')->format('Y-m-d\TH:i:s');
$stats = $health->stats($sinceIso);

// For a nicer "per Workflow" table than raw ids.
$workflows = new WorkflowRepository($config->workflowsDir());
$workflowNames = [];
foreach ($workflows->listAll() as $workflow) {
    $workflowNames[$workflow['id']] = $workflow['name'] ?? $workflow['id'];
}


// Machine-readable form for external uptime monitoring - checks the HTTP
// status code (200 healthy, 503 not) without needing to parse HTML.
if (($_GET['format'] ?? '') === 'json') {
    header('Content-Type: application/json');
    http_response_code($health->isHealthy() ? 200 : 503);
    echo json_encode([
        'ok' => $health->isHealthy(),                 // false only when "stopped" (then HTTP 503)
        'status' => $health->status(),                // ok | late | stopped
        'last_run_at' => $health->lastRunAt(),         // the cron job's last run
        'minutes_since_last_run' => $health->minutesSinceLastRun(),
        'expected_every_minutes' => $config->cronIntervalMinutes(),
        'late_after_minutes' => $health->lateAfterMinutes(),
        'stopped_after_minutes' => $health->stoppedAfterMinutes(),
        'last_24h' => $stats,
        'recent_webhook_pings' => ($config->webhooks()['enabled'] ?? false) ? $health->recentWebhookPings() : null,
    ]);
    exit;
}
?>
<?php Layout::start('Status', 'Status', 'health'); ?>

<?php if (!$health->isAvailable()): ?>
    <p class="notice">Noch keine <code>automation/var/state.sqlite3</code> gefunden - sie entsteht
    beim ersten Lauf von <code>python -m automation.main</code>.</p>
<?php else: ?>

<?php $ago = $health->lastRunAt() === null ? '' : h(HealthStatus::durationText((int) round($health->minutesSinceLastRun()))); ?>
<?php if ($health->status() === 'ok'): ?>
    <p class="notice" style="background:#e6f4ea;border-color:var(--accent);">
        ✓ Letzter Cron-Lauf: <?= Layout::dateTime($health->lastRunAt()) ?> (vor <?= $ago ?>).
        Erwartet: alle <?= h($health->intervalText()) ?>, der nächste etwa
        <?= Layout::dateTime($health->nextExpectedRunAt()?->format('c')) ?>.
    </p>
<?php elseif ($health->status() === 'late'): ?>
    <p class="notice" style="background:#fff8e1;border-color:#d4a017;">
        ⚠ Der Cron-Lauf ist verspätet: der letzte war <?= Layout::dateTime($health->lastRunAt()) ?> (vor <?= $ago ?>),
        erwartet wird alle <?= h($health->intervalText()) ?>. Kommt innerhalb von <?= h($health->stoppedAfterText()) ?>
        kein Lauf, meldet diese Seite „gestoppt“.
    </p>
<?php else: ?>
    <p class="notice error">
        ✗ Der Cron-Job ist länger als <?= h($health->stoppedAfterText()) ?> nicht gelaufen<?php if ($health->lastRunAt() !== null): ?>
        - der letzte Lauf war <?= Layout::dateTime($health->lastRunAt()) ?> (vor <?= $ago ?>)<?php endif; ?>.
        Erwartet wird alle <?= h($health->intervalText()) ?> - läuft er noch? Läufe, die die Website selbst anstößt
        (Webhook, Einmal-Link), zählen hier nicht mit.
    </p>
<?php endif; ?>

<p class="muted">Als einfacher Monitoring-Endpunkt (HTTP 200/503):
<code><?= h($_SERVER['PHP_SELF'] ?? 'health.php') ?>?format=json</code></p>

<h2>Letzte 24 Stunden</h2>
<p>
    <?= $stats['total'] ?> Lauf/Läufe insgesamt -
    <?= $stats['successful'] ?> erfolgreich,
    <?= $stats['failed'] ?> fehlgeschlagen.
</p>

<?php if (!empty($stats['per_workflow'])): ?>
<table>
<thead>
<tr>
    <th>Workflow</th>
    <th>Läufe</th>
    <th>Fehlgeschlagen</th>
</tr>
</thead>
<tbody>
<?php foreach ($stats['per_workflow'] as $workflowId => $counts): ?>
<tr class="<?= $counts['failed'] > 0 ? 'run-failed' : '' ?>">
    <td><?= h($workflowNames[$workflowId] ?? $workflowId) ?></td>
    <td><?= $counts['total'] ?></td>
    <td><?= $counts['failed'] ?></td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
<?php else: ?>
<p>Keine Ausführungen in den letzten 24 Stunden.</p>
<?php endif; ?>

<?php if ($config->webhooks()['enabled'] ?? false): ?>
<h2>Webhook-Pings</h2>
<?php if ($config->webhooks()['secret_problem'] !== null): ?>
<p class="notice error">Webhooks sind eingeschaltet, werden aber <strong>nicht angenommen</strong>:
<?= h((string) $config->webhooks()['secret_problem']) ?> Mit <code>./configure.sh settings</code> ein neues Secret erzeugen.</p>
<?php elseif (!$config->webhooks()['require_https']): ?>
<p class="notice">Webhooks werden auch über unverschlüsseltes HTTP angenommen (<code>webhooks.require_https: false</code>) -
nur für lokale Tests gedacht.</p>
<?php endif; ?>
<p class="muted">Bestätigt, dass Nextclouds Webhook-Konfiguration diese Seite tatsächlich erreicht
(unabhängig davon, ob <code>automation/main.py</code> den Ping schon verarbeitet hat).</p>
<?php $pings = $health->recentWebhookPings(); ?>
<?php if (empty($pings)): ?>
<p>Noch kein Webhook-Ping empfangen.</p>
<?php else: ?>
<table>
<thead><tr><th>Instanz</th><th>Board</th><th>Letzter Ping</th></tr></thead>
<tbody>
<?php foreach ($pings as $ping): ?>
<tr>
    <td><?= h($ping['instance']) ?></td>
    <td><?= (int) $ping['board_id'] ?></td>
    <td><?= Layout::dateTime($ping['last_ping_at']) ?></td>
</tr>
<?php endforeach; ?>
</tbody>
</table>
<?php endif; ?>
<?php endif; ?>

<?php endif; ?>

<?php Layout::end(); ?>
