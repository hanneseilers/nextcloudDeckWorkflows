<?php

/**
 * Receives a "something changed on this board" ping - configure Nextcloud
 * (via its own Flow/Webhooks admin settings - a server-admin task, outside
 * this project's control, and not something verified against a live
 * instance here) to call this URL, with `instance`/`board_id` baked into
 * the URL itself and the secret sent as a header:
 *
 *   https://your-site/website/webhook.php?instance=prod&board_id=42
 *   X-Webhook-Secret: <webhooks.secret from config/settings.yaml>
 *
 * The secret is accepted in the header only - a secret in the URL ends up in
 * access logs. Requests must arrive over HTTPS (webhooks.require_https), the
 * secret must be long enough (Config::MIN_WEBHOOK_SECRET_LENGTH), and wrong
 * attempts as well as the number of pings are rate limited
 * (WebhookThrottle).
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

use NextcloudDeckWorkflows\AutomationRunner;
use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\WebhookPingStore;
use NextcloudDeckWorkflows\WebhookThrottle;

header('Content-Type: application/json');
header('Cache-Control: no-store');

function webhookReply(int $status, array $body, array $headers = []): never
{
    http_response_code($status);
    foreach ($headers as $header) {
        header($header);
    }
    echo json_encode($body);
    exit;
}

/** Whether this request came in over HTTPS (also behind a proxy that terminates it). */
function webhookIsHttps(): bool
{
    $https = strtolower((string) ($_SERVER['HTTPS'] ?? ''));
    if ($https !== '' && $https !== 'off') {
        return true;
    }
    if ((string) ($_SERVER['SERVER_PORT'] ?? '') === '443') {
        return true;
    }
    // Shared hosting commonly puts a proxy in front that sets this. A client
    // could send it itself over plain HTTP - but that only exposes its own request.
    return strtolower((string) ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')) === 'https'
        || strtolower((string) ($_SERVER['HTTP_X_FORWARDED_SSL'] ?? '')) === 'on';
}

try {
    $config = Config::fromRepoRoot();
    $webhooks = $config->webhooks();

    if ($webhooks === null || !$webhooks['enabled'] || $webhooks['secret_problem'] !== null) {
        // Deliberately a generic 404 (not "here's why") - don't help a
        // scanning attacker distinguish "not configured" from "wrong secret".
        // An empty/short secret is treated the same as "not configured" rather
        // than falling through to hash_equals('', $providedSecret) below, which
        // would otherwise accept an empty-string secret from anyone - silently
        // turning a misconfiguration (webhooks enabled, no/weak secret set) into
        // an unauthenticated or guessable endpoint. The reason is shown on the
        // status page (health.php) instead.
        webhookReply(404, ['error' => 'Not found']);
    }

    if ($webhooks['require_https'] && !webhookIsHttps()) {
        webhookReply(403, ['error' => 'HTTPS required']);
    }

    $throttle = new WebhookThrottle($config->stateDbPath());
    $client = hash('sha256', (string) ($_SERVER['REMOTE_ADDR'] ?? ''));

    $wait = $throttle->retryAfterForFailures($client);
    if ($wait > 0) {
        // Too many wrong attempts: not even looked at, whatever the secret.
        webhookReply(429, ['error' => 'Too many failed attempts'], ['Retry-After: ' . $wait]);
    }

    // Header only; ?secret= in the URL is deliberately ignored.
    $providedSecret = (string) ($_SERVER['HTTP_X_WEBHOOK_SECRET'] ?? '');
    if ($providedSecret === '' || !hash_equals($webhooks['secret'], $providedSecret)) {
        $throttle->recordFailure($client);
        webhookReply(403, ['error' => 'Invalid or missing secret (send it in the X-Webhook-Secret header)']);
    }

    $instanceName = (string) ($_GET['instance'] ?? '');
    $boardId = (int) ($_GET['board_id'] ?? 0);
    if ($config->instance($instanceName) === null || $boardId <= 0) {
        webhookReply(400, ['error' => 'Missing or unknown instance/board_id']);
    }

    $wait = $throttle->admitValid();
    if ($wait > 0) {
        webhookReply(429, ['error' => 'Too many requests'], ['Retry-After: ' . $wait]);
    }

    // Always recorded - the next run polls this board even if no run is started below.
    (new WebhookPingStore($config->stateDbPath()))->recordPing($instanceName, $boardId);

    // Best-effort only: try to make automation/main.py react immediately
    // instead of waiting for the next cron tick - while a run is going on
    // not more often than every WebhookThrottle::RUN_INTERVAL seconds,
    // however many pings arrive (main.py queues one run behind it).
    // proc_open/exec are commonly disabled on shared hosting - if this
    // silently does nothing, the ping above is still recorded correctly and
    // gets picked up on the next regular cron invocation regardless, just
    // not instantly.
    if ($throttle->claimRun(WebhookThrottle::runInProgress(dirname($config->stateDbPath()) . '/run.lock'))) {
        AutomationRunner::triggerNow();
    }

    webhookReply(202, ['ok' => true]);
} catch (\Throwable $e) {
    error_log('webhook.php: ' . $e->getMessage());
    webhookReply(500, ['error' => 'Internal error']);
}
