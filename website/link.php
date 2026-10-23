<?php

/**
 * One-time action link (see create_action_link). Deliberately public: the
 * long random token in the URL is the credential - if the rest of the site
 * sits behind HTTP Basic Auth, exempt this one file (website/README.md).
 *
 * The first visit uses the link up (atomic claim), then waits briefly for
 * automation/main.py to run the action and shows its outcome: the link's
 * own success text, or a generic error text (details stay in the history,
 * not on a page anyone holding the link can read). The action itself runs
 * in Python - this page only claims the link and asks for an immediate
 * run, so if that cannot be started (proc_open disabled) the page says the
 * action was accepted and will run with the next cron invocation.
 */

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\ActionLinkStore;
use NextcloudDeckWorkflows\AutomationRunner;
use NextcloudDeckWorkflows\Config;

const WAIT_SECONDS = 25;

header('Cache-Control: no-store');
header('X-Robots-Tag: noindex');
set_time_limit(WAIT_SECONDS + 15);


function page(int $status, string $kind, string $message, string $extra = ''): never
{
    http_response_code($status);
    echo '<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">'
        . '<meta name="viewport" content="width=device-width, initial-scale=1">'
        . '<meta name="robots" content="noindex"><title>Aktion</title>'
        . '<link rel="stylesheet" href="assets/style.css"></head><body>'
        . '<p class="notice' . ($kind === 'error' ? ' error' : '') . '" id="result" data-kind="' . h($kind) . '">'
        . nl2br(h($message)) . '</p>' . $extra . '</body></html>';
    exit;
}

$invalid = 'Dieser Link ist ungültig oder wurde bereits verwendet.';

$token = (string) ($_GET['h'] ?? '');
if (!preg_match('/^[A-Za-z0-9_-]{20,128}$/', $token)) {
    page(404, 'invalid', $invalid);
}
$tokenHash = hash('sha256', $token);

$store = new ActionLinkStore(Config::fromRepoRoot()->stateDbPath());
$link = $store->find($tokenHash);
if ($link === null || $link['status'] !== 'open') {
    page(410, 'invalid', $invalid);
}

if ($link['require_confirmation'] && $_SERVER['REQUEST_METHOD'] !== 'POST') {
    // GET only asks - link-preview/virus-scanner bots follow GETs, they don't submit forms.
    page(200, 'confirm', 'Soll die Aktion jetzt ausgeführt werden? Der Link kann nur einmal verwendet werden.',
        '<form method="post" action="link.php?h=' . h(rawurlencode($token)) . '"><button type="submit">Jetzt ausführen</button></form>');
}

if (!$store->claim($tokenHash)) {
    page(410, 'invalid', $invalid); // someone else used it in the meantime
}

AutomationRunner::triggerNow();

$deadline = microtime(true) + WAIT_SECONDS;
while (microtime(true) < $deadline) {
    $current = $store->find($tokenHash);
    if ($current !== null && $current['status'] === 'done') {
        page(200, 'success', $link['success_message']);
    }
    if ($current !== null && $current['status'] === 'error') {
        page(500, 'error', 'Die Aktion konnte nicht ausgeführt werden. Bitte wende dich an die Person, die dir den Link gegeben hat.');
    }
    usleep(500000);
}

page(202, 'pending', 'Die Aktion wurde angenommen und wird in Kürze ausgeführt.');
