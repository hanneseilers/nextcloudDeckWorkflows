<?php
// Standalone check for TemplateStore (no PHPUnit in this project, see AGENTS.md):
//   php tools/test_template_store.php
declare(strict_types=1);

require __DIR__ . '/../website/vendor/autoload.php';

use NextcloudDeckWorkflows\TemplateStore;
use NextcloudDeckWorkflows\WorkflowRepository;

$failures = 0;
function check(string $name, bool $ok): void
{
    global $failures;
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . "\n";
    if (!$ok) {
        $failures++;
    }
}
function throws(callable $fn, string $class = \Throwable::class): bool
{
    try {
        $fn();
    } catch (\Throwable $e) {
        return $e instanceof $class;
    }
    return false;
}
function rrmdir(string $dir): void
{
    foreach (glob($dir . '/{,.}*', GLOB_BRACE) ?: [] as $entry) {
        if (in_array(basename($entry), ['.', '..'], true)) {
            continue;
        }
        is_dir($entry) && !is_link($entry) ? rrmdir($entry) : unlink($entry);
    }
    @rmdir($dir);
}

$root = sys_get_temp_dir() . '/ncdw_tpl_' . bin2hex(random_bytes(4));
mkdir($root . '/config', 0775, true);
$config = $root . '/config';
$store = new TemplateStore($config);

// -- names ------------------------------------------------------------------------
foreach (['willkommen', 'Ticket-Eingang', 'mail 2', 'Übersicht_1', 'a', str_repeat('x', 60)] as $name) {
    check("valid name '$name'", TemplateStore::validName($name));
}
foreach (['', ' ', '../secret', 'a/b', 'a\\b', 'a.b', '..', '.hidden', str_repeat('x', 61), "a\nb", '-start', ' lead', 'trail ', "a\0b"] as $name) {
    check('refused name ' . json_encode($name), !TemplateStore::validName($name));
}

// -- create / read / save -------------------------------------------------------------
check('no templates at first (folder missing)', $store->names() === []);
$store->create('willkommen', "Subject: Hallo\r\n\r\nText\r\nzwei");
check('the folder was created', is_dir($config . '/text_templates'));
$read = $store->read('willkommen');
check('CRLF is stored as LF', $read !== null && $read['content'] === "Subject: Hallo\n\nText\nzwei");
check('the file is the plain .txt the automation reads', file_get_contents($config . '/text_templates/willkommen.txt') === "Subject: Hallo\n\nText\nzwei");
check('creating an existing name is refused', throws(fn () => $store->create('willkommen', 'x'), \RuntimeException::class));
$v1 = $store->read('willkommen')['version'];
$store->save('willkommen', 'neu');
check('version: changes with the text, same text = same version', $store->read('willkommen')['version'] !== $v1
    && $store->read('willkommen')['version'] === sha1('neu'));
check('save overwrites', $store->read('willkommen')['content'] === 'neu');
check('save of a missing template is refused', throws(fn () => $store->save('gibtsnicht', 'x'), \RuntimeException::class));
check('no temp files are left behind', glob($config . '/text_templates/.*.tmp') === []);
$store->save('willkommen', "Grüße – Æ 😀\n");
check('umlauts and emoji survive', $store->read('willkommen')['content'] === "Grüße – Æ 😀\n");

// -- refusals -------------------------------------------------------------------------
check('invalid UTF-8 refused', throws(fn () => $store->save('willkommen', "bad \xff byte"), \InvalidArgumentException::class));
check('too large refused', throws(fn () => $store->save('willkommen', str_repeat('a', TemplateStore::MAX_BYTES + 1)), \InvalidArgumentException::class));
check('a NUL byte refused', throws(fn () => $store->save('willkommen', "a\0b"), \InvalidArgumentException::class));
file_put_contents($root . '/geheim.txt', 'nicht lesen');
foreach (['../../geheim', '../geheim', '/etc/passwd', 'a/../../geheim'] as $evil) {
    check("path-like name '$evil' reaches no file: read", $store->read($evil) === null);
    check("path-like name '$evil' reaches no file: create", throws(fn () => $store->create($evil, 'x'), \InvalidArgumentException::class));
    check("path-like name '$evil' reaches no file: delete", throws(fn () => $store->delete($evil)));
    check("path-like name '$evil' reaches no file: rename", throws(fn () => $store->rename('willkommen', $evil), \InvalidArgumentException::class));
}
check('the outside file is untouched', file_get_contents($root . '/geheim.txt') === 'nicht lesen');
file_put_contents($config . '/text_templates/bad.name.txt', 'x');
file_put_contents($config . '/text_templates/.versteckt.txt', 'x');
symlink($root . '/geheim.txt', $config . '/text_templates/link.txt');
check('files with unusable names and symlinks are not listed', $store->names() === ['willkommen']);
check('a symlink is not readable as a template', $store->read('link') === null);

// -- rename / delete ---------------------------------------------------------------------
$store->rename('willkommen', 'Begrüßung');
check('rename moves the file', $store->names() === ['Begrüßung'] && !is_file($config . '/text_templates/willkommen.txt'));
$store->create('zweite', 'z');
check('rename onto an existing name refused', throws(fn () => $store->rename('zweite', 'Begrüßung'), \RuntimeException::class));
check('rename of a missing template refused', throws(fn () => $store->rename('nix', 'neu'), \RuntimeException::class));
$store->rename('zweite', 'zweite');
check('rename to the same name is a no-op', $store->exists('zweite'));
$store->delete('zweite');
check('delete removes the file', !$store->exists('zweite'));
check('delete of a missing template refused', throws(fn () => $store->delete('zweite'), \RuntimeException::class));

// -- the old e-mail template folder ----------------------------------------------------------
mkdir($config . '/email_templates');
file_put_contents($config . '/email_templates/alt.txt', "Subject: Alt\n\nText");
file_put_contents($config . '/email_templates/Begrüßung.txt', 'ALT-DOPPELT');
file_put_contents($config . '/email_templates/kaputt.name.txt', 'x');
check('a template only in the old folder is listed and readable before it is moved',
    in_array('alt', $store->names(), true) && $store->read('alt')['content'] === "Subject: Alt\n\nText");
check('the new folder wins over an old file of the same name', $store->read('Begrüßung')['content'] === "Grüße – Æ 😀\n");
check('migrateLegacy moves exactly the ones without a clash', $store->migrateLegacy() === 1
    && is_file($config . '/text_templates/alt.txt') && !is_file($config . '/email_templates/alt.txt'));
check('...and leaves a clashing and an unusable file alone, the folder stays',
    is_file($config . '/email_templates/Begrüßung.txt') && is_file($config . '/email_templates/kaputt.name.txt'));
$store->delete('Begrüßung');
check('delete removes the old copy of the same name too (no resurrection)', !$store->exists('Begrüßung') && !is_file($config . '/email_templates/Begrüßung.txt'));
unlink($config . '/email_templates/kaputt.name.txt');
check('migrateLegacy removes the old folder once it is empty', $store->migrateLegacy() === 0 && !is_dir($config . '/email_templates'));
$store->delete('alt');

// -- e-mail subject line ----------------------------------------------------------------------
check('split: subject + body', TemplateStore::splitEmail("Subject: Hi\n\nBody\n\nmore") === ['subject' => 'Hi', 'body' => "Body\n\nmore"]);
check('split: no subject', TemplateStore::splitEmail("Nur Text\n\nzwei") === ['subject' => '', 'body' => "Nur Text\n\nzwei"]);
check('split: a leading blank line means no subject', TemplateStore::splitEmail("\nSubject: x\n\nText")['subject'] === '');
foreach ([['Hi', "Body\n\nmore"], ['', 'Nur Text'], ['', "Subject: im Text\n\nrest"], ['Betreff', '']] as [$subject, $body]) {
    $back = TemplateStore::splitEmail(TemplateStore::joinEmail($subject, $body));
    check('join/split round trip ' . json_encode([$subject, $body]), $back['subject'] === $subject && ltrim($back['body'], "\n") === ltrim($body, "\n"));
}
check('a subject with a line break becomes one line', TemplateStore::joinEmail("a\nb", 'x') === "Subject: a b\n\nx");

// -- placeholders ---------------------------------------------------------------------------------
check('placeholders: $name and ${name}, once each, in order',
    TemplateStore::placeholders('Hallo $name, ${ort}! $name $$nicht $_x1 und $1 $') === ['name', 'ort', '_x1']);
check('placeholders: none', TemplateStore::placeholders('Kein Platzhalter, 5 $ und $$') === []);

// -- usages / renaming references ------------------------------------------------------------------
$store->create('willkommen', 'w');
$store->create('Kurztext', 'k');
$repo = new WorkflowRepository($root . '/workflows');
$base = ['enabled' => true, 'nextcloud_instance' => 'prod', 'board_id' => 1, 'trigger' => ['event' => 'card_created']];
$repo->save($base + ['id' => 'a', 'name' => 'Eins', 'actions' => [
    ['module' => 'send_email', 'id' => 'm', 'params' => ['to' => 'x@y.z', 'template' => 'willkommen']],
    ['type' => 'if', 'condition' => ['left' => 1, 'op' => 'eq', 'right' => 1],
        'then' => [['module' => 'send_email', 'params' => ['template' => 'willkommen']]],
        'else' => [['module' => 'send_email', 'params' => ['template' => 'andere']]]],
]]);
$repo->save($base + ['id' => 'b', 'name' => 'Zwei', 'actions' => [
    ['module' => 'add_comment', 'params' => ['message' => '', 'text_template' => 'Kurztext']],
    ['module' => 'format_text', 'params' => ['template' => 'willkommen', 'text_template' => 'Kurztext', 'values' => []]],
    ['module' => 'send_email', 'params' => ['template' => ['$ref' => 'x.y']]],
]]);
$repo->save($base + ['id' => 'c', 'name' => 'Drei', 'actions' => [['module' => 'log_action', 'params' => ['message' => 'willkommen']]]]);
check('usages: send_email, nested steps included', $store->usages($repo, 'willkommen') === [['id' => 'a', 'name' => 'Eins']]);
check('usages: format_text and add_comment, a workflow counted once', $store->usages($repo, 'Kurztext') === [['id' => 'b', 'name' => 'Zwei']]);
check('usages: a template used nowhere', $store->usages($repo, 'frei') === []);
$changed = $store->renameReferences($repo, 'willkommen', 'Begrüßung2');
$a = $repo->get('a');
check('renameReferences: changes the matching steps (also nested), reports the workflows', $changed === 1
    && $a['actions'][0]['params']['template'] === 'Begrüßung2'
    && $a['actions'][1]['then'][0]['params']['template'] === 'Begrüßung2'
    && $a['actions'][1]['else'][0]['params']['template'] === 'andere');
check('renameReferences: leaves other parameters (an inline template text!) and workflows alone',
    $repo->get('c')['actions'][0]['params']['message'] === 'willkommen'
    && $repo->get('b')['actions'][1]['params']['template'] === 'willkommen');
check('renameReferences: the workflow stays where it was', $repo->folderOf('a') === '');

rrmdir($root);
echo $failures === 0 ? "ALL PASSED\n" : "$failures FAILED\n";
exit($failures === 0 ? 0 : 1);
