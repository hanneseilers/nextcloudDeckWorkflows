<?php
// Standalone check for WebhookThrottle and Config's webhook secret rules (no
// PHPUnit in this project, see AGENTS.md): php tools/test_webhook_throttle.php
declare(strict_types=1);

require __DIR__ . '/../website/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\WebhookThrottle;

$failures = 0;
function check(string $name, bool $ok): void
{
    global $failures;
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . "\n";
    if (!$ok) {
        $failures++;
    }
}

$db = sys_get_temp_dir() . '/ncdw_throttle_' . bin2hex(random_bytes(4)) . '.sqlite3';
$now = 1_000_000;
$throttle = new WebhookThrottle($db, function () use (&$now): int { return $now; });

// -- wrong secrets -----------------------------------------------------------
check('a fresh client may try', $throttle->retryAfterForFailures('ip-a') === 0);
for ($i = 0; $i < WebhookThrottle::FAIL_LIMIT - 1; $i++) {
    $throttle->recordFailure('ip-a');
    $now += 1;
}
check('still allowed one failure below the limit', $throttle->retryAfterForFailures('ip-a') === 0);
$throttle->recordFailure('ip-a');
$wait = $throttle->retryAfterForFailures('ip-a');
check('blocked at the limit, with a sensible wait', $wait > 0 && $wait <= WebhookThrottle::FAIL_WINDOW);
check('another client is not affected', $throttle->retryAfterForFailures('ip-b') === 0);
$now += WebhookThrottle::FAIL_WINDOW + 1;
check('the block ends once the oldest failures left the window', $throttle->retryAfterForFailures('ip-a') === 0);

// -- valid pings -------------------------------------------------------------
$admitted = 0;
for ($i = 0; $i < WebhookThrottle::VALID_LIMIT + 5; $i++) {
    if ($throttle->admitValid() === 0) {
        $admitted++;
    }
}
check('valid pings: exactly the limit is admitted per window', $admitted === WebhookThrottle::VALID_LIMIT);
check('a refused ping is told to wait', $throttle->admitValid() > 0);
$now += WebhookThrottle::VALID_WINDOW + 1;
check('valid pings are admitted again after the window', $throttle->admitValid() === 0);

// -- automation runs ---------------------------------------------------------
check('first ping may start a run', $throttle->claimRun() === true);
check('a second one right after may not', $throttle->claimRun() === false);
$now += WebhookThrottle::RUN_INTERVAL - 1;
check('still not just before the interval is over', $throttle->claimRun() === false);
$now += 2;
check('a run may be started again after the interval', $throttle->claimRun() === true);

// -- old rows are removed ----------------------------------------------------
$now += 7200;
$throttle->recordFailure('ip-c');
$rows = (int) (new PDO('sqlite:' . $db))->query('SELECT COUNT(*) FROM webhook_events')->fetchColumn();
check('rows older than the longest window are deleted', $rows === 1);

// -- concurrency: two instances of the class on one file share the limit ---------
$other = new WebhookThrottle($db, function () use (&$now): int { return $now; });
$now += 1000;
$a = 0;
for ($i = 0; $i < WebhookThrottle::VALID_LIMIT; $i++) {
    if (($i % 2 === 0 ? $throttle : $other)->admitValid() === 0) {
        $a++;
    }
}
check('the limit is shared through the database', $a === WebhookThrottle::VALID_LIMIT && $other->admitValid() > 0);

// -- Config: the secret rules -------------------------------------------------
$dir = sys_get_temp_dir() . '/ncdw_cfg_' . bin2hex(random_bytes(4));
mkdir($dir);
file_put_contents($dir . '/nextcloud.yaml', "instances: []\n");
function webhooksFor(string $dir, string $yaml): ?array
{
    file_put_contents($dir . '/settings.yaml', $yaml);
    return (new Config($dir))->webhooks();
}
$good = str_repeat('a1B2', 8); // 32 characters
$w = webhooksFor($dir, "webhooks:\n  enabled: true\n  secret: \"$good\"\n");
check('a long secret is accepted, HTTPS required by default', $w !== null && $w['secret_problem'] === null && $w['require_https'] === true);
$w = webhooksFor($dir, "webhooks:\n  enabled: true\n  require_https: false\n  secret: \"$good\"\n");
check('require_https can be switched off (local testing)', $w['require_https'] === false);
$w = webhooksFor($dir, "webhooks:\n  enabled: true\n  secret: \"kurz\"\n");
check('a short secret is a problem', is_string($w['secret_problem']) && str_contains($w['secret_problem'], (string) Config::MIN_WEBHOOK_SECRET_LENGTH));
$w = webhooksFor($dir, "webhooks:\n  enabled: true\n  secret: \"CHANGE_ME_TO_A_LONG_RANDOM_STRING\"\n");
check('the example placeholder is a problem', is_string($w['secret_problem']));
$w = webhooksFor($dir, "webhooks:\n  enabled: true\n  secret: \"\"\n");
check('an empty secret is a problem', is_string($w['secret_problem']));
$w = webhooksFor($dir, "webhooks:\n  enabled: true\n  secret: 123456\n");
check('a short unquoted number (YAML makes it an int) is refused, not compared', is_string($w['secret_problem']) && $w['secret'] === '');

@unlink($db);
array_map('unlink', glob($dir . '/*') ?: []);
@rmdir($dir);
echo $failures === 0 ? "ALL PASSED\n" : "$failures FAILED\n";
exit($failures === 0 ? 0 : 1);
