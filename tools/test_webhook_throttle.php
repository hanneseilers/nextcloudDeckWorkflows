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
check('...also when it can not be told whether a run is going on', $throttle->claimRun(null) === false);
check('...and while a run is in progress', $throttle->claimRun(true) === false);
check('but with no run in progress a ping always starts one', $throttle->claimRun(false) === true);
$now += WebhookThrottle::RUN_INTERVAL + 1;
check('a run may be started again after the interval', $throttle->claimRun() === true);

// -- the run lock probe (same flock main.py's RunLock takes) ----------------------
$lockFile = sys_get_temp_dir() . '/ncdw_run_' . bin2hex(random_bytes(4)) . '.lock';
check('no lock file yet: no run in progress', WebhookThrottle::runInProgress($lockFile) === false);
$held = fopen($lockFile, 'c');
flock($held, LOCK_EX | LOCK_NB);
check('a held exclusive lock means a run is in progress', WebhookThrottle::runInProgress($lockFile) === true);
flock($held, LOCK_UN);
fclose($held);
check('released: no run in progress', WebhookThrottle::runInProgress($lockFile) === false);
check('an unusable path means unknown', WebhookThrottle::runInProgress('/nonexistent-dir/run.lock') === null);
@unlink($lockFile);

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

// -- the status page's warning threshold -----------------------------------------------------
use NextcloudDeckWorkflows\HealthStatus;

$w = webhooksFor($dir, "{}\n");
check('health: the default warning threshold is 12 hours', (new Config($dir))->healthStaleMinutes() === 720.0 && HealthStatus::DEFAULT_STALE_MINUTES === 720.0);
file_put_contents($dir . '/settings.yaml', "health_stale_minutes: 40\n");
check('health: a configured value overrides the default', (new Config($dir))->healthStaleMinutes() === 40.0);
file_put_contents($dir . '/settings.yaml', "health_stale_minutes: 0\n");
check('health: a nonsense value (0) falls back to the default', (new Config($dir))->healthStaleMinutes() === 720.0);
foreach ([[1, '1 Minute'], [40, '40 Minuten'], [60, '1 Stunde'], [90, '1 Stunde 30 Minuten'], [720, '12 Stunden'], [1440, '1 Tag'], [1560, '1 Tag 2 Stunden'], [2880, '2 Tage']] as [$min, $text]) {
    check("health: $min minutes read as '$text'", HealthStatus::durationText($min) === $text);
}
$stale = new HealthStatus($db, 720.0);
check('health: the threshold is named in the warning text', $stale->staleAfterText() === '12 Stunden');

@unlink($db);
array_map('unlink', glob($dir . '/*') ?: []);
@rmdir($dir);
echo $failures === 0 ? "ALL PASSED\n" : "$failures FAILED\n";
exit($failures === 0 ? 0 : 1);
