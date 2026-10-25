<?php
// Standalone check for ModuleRegistry's freshness test (no PHPUnit in this project, see AGENTS.md):
//   php tools/test_module_registry.php
declare(strict_types=1);

require __DIR__ . '/../website/vendor/autoload.php';

use NextcloudDeckWorkflows\ModuleRegistry;

$failures = 0;
function check(string $name, bool $ok): void
{
    global $failures;
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . "\n";
    if (!$ok) {
        $failures++;
    }
}

$root = sys_get_temp_dir() . '/ncdw_modreg_' . bin2hex(random_bytes(4));
foreach (['actions_registry', 'adapters/actions', 'core', 'var'] as $dir) {
    mkdir($root . '/automation/' . $dir, 0775, true);
}
$automation = $root . '/automation';
file_put_contents($automation . '/actions_registry/a.py', "x = 1\n");
file_put_contents($automation . '/adapters/actions/b.py', "y = 1\n");
$snapshot = $automation . '/var/modules.json';
$registry = new ModuleRegistry($snapshot);

check('no snapshot: not available, not fresh', !$registry->isAvailable() && !$registry->isFresh() && $registry->snapshotFingerprint() === '');

$fingerprint = $registry->currentFingerprint();
check('fingerprint is a sha1', preg_match('/^[0-9a-f]{40}$/', $fingerprint) === 1);
file_put_contents($snapshot, json_encode(['modules' => [['name' => 'x']], 'fingerprint' => $fingerprint]));
check('a snapshot written with the same code is fresh', $registry->isFresh() && $registry->snapshotFingerprint() === $fingerprint);

file_put_contents($automation . '/actions_registry/a.py', "x = 2\n"); // same size, other content
check('changed module code (same size!) makes it stale', !$registry->isFresh());
file_put_contents($automation . '/actions_registry/a.py', "x = 1\n");
check('...and back again it is fresh', $registry->isFresh());
file_put_contents($automation . '/actions_registry/new.py', '');
check('a new module file makes it stale', !$registry->isFresh());
unlink($automation . '/actions_registry/new.py');
file_put_contents($automation . '/core/c.py', "z = 1\n");
file_put_contents($automation . '/actions_registry/notes.txt', 'x');
check('other folders and non-.py files do not count', $registry->isFresh());

file_put_contents($snapshot, json_encode(['modules' => [['name' => 'x']]]));
check('a snapshot without a fingerprint (older version) is stale', !$registry->isFresh() && $registry->isAvailable());
file_put_contents($snapshot, '{not json');
check('a damaged snapshot is stale, not an error', !$registry->isFresh());
file_put_contents($snapshot, json_encode(['modules' => [], 'fingerprint' => 123]));
check('a fingerprint of the wrong type is stale', !$registry->isFresh());

// the same files give the same fingerprint when the tree lives elsewhere
$copy = sys_get_temp_dir() . '/ncdw_modreg_copy_' . bin2hex(random_bytes(4));
foreach (['actions_registry', 'adapters/actions', 'var'] as $dir) {
    mkdir($copy . '/automation/' . $dir, 0775, true);
}
copy($automation . '/actions_registry/a.py', $copy . '/automation/actions_registry/a.py');
copy($automation . '/adapters/actions/b.py', $copy . '/automation/adapters/actions/b.py');
check('the fingerprint depends on the files, not on where they are', (new ModuleRegistry($copy . '/automation/var/modules.json'))->currentFingerprint() === $registry->currentFingerprint());

function rrmdir(string $dir): void
{
    foreach (glob($dir . '/{,.}*', GLOB_BRACE) ?: [] as $entry) {
        if (in_array(basename($entry), ['.', '..'], true)) {
            continue;
        }
        is_dir($entry) ? rrmdir($entry) : unlink($entry);
    }
    @rmdir($dir);
}
rrmdir($root);
rrmdir($copy);
echo $failures === 0 ? "ALL PASSED\n" : "$failures FAILED\n";
exit($failures === 0 ? 0 : 1);
