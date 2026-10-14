<?php

/**
 * Receives a "something changed on this board" ping - configure Nextcloud
 * (via its own Flow/Webhooks admin settings - a server-admin task, outside
 * this project's control, and not something verified against a live
 * instance here) to call this URL, with `instance`/`board_id` baked into
 * the URL itself:
 *
 *   https://your-site/website/webhook.php?secret=...&instance=prod&board_id=42
 *
 * Deliberately does not try to parse anything Nextcloud sends in the
 * request body - the exact webhook payload shape isn't something this
 * project can verify, so instance/board_id come from the URL the admin
 * configures instead, and the body (whatever it is) is ignored entirely.
 * This just records that a ping happened; automation/main.py's next
 * invocation (cron, or the best-effort immediate trigger attempted below)
 * is what actually decides whether to poll - see
 * core/domain/webhook_gate.should_poll_now.
 */

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\WebhookPingStore;

header('Content-Type: application/json');

$config = Config::fromRepoRoot();
$webhooks = $config->webhooks();

if ($webhooks === null || !$webhooks['enabled']) {
    // Deliberately a generic 404 (not "here's why") - don't help a
    // scanning attacker distinguish "not configured" from "wrong secret".
    http_response_code(404);
    echo json_encode(['error' => 'Not found']);
    exit;
}

$providedSecret = (string) ($_GET['secret'] ?? $_SERVER['HTTP_X_WEBHOOK_SECRET'] ?? '');
if (!hash_equals($webhooks['secret'], $providedSecret)) {
    http_response_code(403);
    echo json_encode(['error' => 'Invalid secret']);
    exit;
}

$instanceName = (string) ($_GET['instance'] ?? '');
$boardId = (int) ($_GET['board_id'] ?? 0);
if ($config->instance($instanceName) === null || $boardId <= 0) {
    http_response_code(400);
    echo json_encode(['error' => 'Missing or unknown instance/board_id']);
    exit;
}

(new WebhookPingStore($config->stateDbPath()))->recordPing($instanceName, $boardId);

// Best-effort only: try to make automation/main.py react immediately
// instead of waiting for the next cron tick. proc_open/exec are commonly
// disabled on shared hosting - if this silently does nothing, the ping
// above is still recorded correctly and gets picked up on the next
// regular cron invocation regardless, just not instantly.
triggerImmediateAutomationRun();

http_response_code(202);
echo json_encode(['ok' => true]);

function triggerImmediateAutomationRun(): void
{
    try {
        if (!function_exists('proc_open')) {
            return;
        }
        $repoRoot = dirname(__DIR__);
        $python = is_file("$repoRoot/.venv/bin/python") ? "$repoRoot/.venv/bin/python" : 'python3';
        // The trailing `&` backgrounds the real work at the shell level,
        // detached from this PHP process, so `sh -c` itself returns
        // almost immediately regardless of how long the automation run
        // takes - this call must not make the webhook response slow.
        $shellCommand = 'cd ' . escapeshellarg($repoRoot) . ' && '
            . escapeshellarg($python) . ' -m automation.main > /dev/null 2>&1 &';
        $process = @proc_open(
            ['/bin/sh', '-c', $shellCommand],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
            $pipes
        );
        if (is_resource($process)) {
            foreach ($pipes as $pipe) {
                fclose($pipe);
            }
            proc_close($process);
        }
    } catch (\Throwable $e) {
        // Never let this optional accelerator affect the webhook response -
        // the ping is already safely recorded above either way.
    }
}
