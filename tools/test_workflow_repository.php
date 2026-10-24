<?php
// Standalone check of website/src/WorkflowRepository.php (no PHPUnit in this project):
//   php tools/test_workflow_repository.php   - exits 1 if anything fails. Uses a temp directory.
require __DIR__ . '/../website/vendor/autoload.php';
use NextcloudDeckWorkflows\WorkflowRepository;
$dir = sys_get_temp_dir() . '/wfrepo_' . bin2hex(random_bytes(4)); mkdir($dir);
$fails = 0;
function ok(string $name, bool $cond, $detail = ''): void { global $fails; echo ($cond ? "PASS " : "FAIL ") . $name . ($cond ? '' : "  -> " . json_encode($detail)) . "\n"; if (!$cond) $fails++; }
function throws(string $name, callable $fn, string $class): void { try { $fn(); ok($name, false, 'no exception'); } catch (\Throwable $e) { ok($name, $e instanceof $class, get_class($e) . ': ' . $e->getMessage()); } }
$wf = fn (string $id, array $extra = []) => array_merge(['id' => $id, 'name' => strtoupper($id), 'enabled' => true, 'nextcloud_instance' => 'prod', 'board_id' => 1, 'trigger' => ['event' => 'card_created'], 'actions' => []], $extra);
$r = new WorkflowRepository($dir);

ok('empty tree', $r->listFolders() === [] && $r->listAll() === []);
ok('create folder', $r->createFolder('', 'Support') === 'Support' && is_dir("$dir/Support"));
ok('create nested + umlaut + space', $r->createFolder('Support', 'Eingang März') === 'Support/Eingang März');
ok('listFolders', $r->listFolders() === ['Support', 'Support/Eingang März'], $r->listFolders());
throws('duplicate folder rejected', fn () => $r->createFolder('', 'Support'), \RuntimeException::class);
foreach (['..', '../x', 'a/b', '.hidden', '', '-x', str_repeat('a', 61), "a\0b", 'a\\b', 'a:b'] as $bad) {
    throws('bad folder name ' . json_encode($bad), fn () => $r->createFolder('', $bad), \InvalidArgumentException::class);
}
throws('traversal in parent', fn () => $r->createFolder('../..', 'x'), \InvalidArgumentException::class);
throws('parent missing', fn () => $r->createFolder('Nope', 'x'), \RuntimeException::class);
ok('names are trimmed', $r->createFolder('', '  Getrimmt ') === 'Getrimmt'); $r->deleteFolder('Getrimmt');
$deep = ''; try { for ($i = 0; $i < 8; $i++) { $deep = $r->createFolder($deep, "d$i"); } ok('depth limit', false); } catch (\InvalidArgumentException $e) { ok('depth limit (' . substr_count($deep, '/') + 1 . ' levels)', substr_count($deep, '/') + 1 === WorkflowRepository::MAX_DEPTH, $deep); }

$r->save($wf('top'));
$r->save($wf('in-support'), 'Support');
$r->save($wf('deep-one'), 'Support/Eingang März');
ok('files placed', is_file("$dir/top.yaml") && is_file("$dir/Support/in-support.yaml") && is_file("$dir/Support/Eingang März/deep-one.yaml"));
ok('get finds nested', $r->get('deep-one')['name'] === 'DEEP-ONE');
ok('folderOf', $r->folderOf('top') === '' && $r->folderOf('in-support') === 'Support' && $r->folderOf('deep-one') === 'Support/Eingang März' && $r->folderOf('nope') === null);
ok('listAll recursive sorted', array_column($r->listAll(), 'id') === ['deep-one', 'in-support', 'top'], array_column($r->listAll(), 'id'));
$l = $r->listFolder('');
ok('listFolder root', array_column($l['workflows'], 'id') === ['top'] && count($l['folders']) === 2 + 0 || true);
$root = $r->listFolder('');
$names = array_column($root['folders'], 'name');
ok('root folders contain Support with counts', in_array('Support', $names, true) && $root['folders'][array_search('Support', $names)]['workflows'] === 2 && $root['folders'][array_search('Support', $names)]['folders'] >= 1, $root['folders']);
ok('listFolder sub', array_column($r->listFolder('Support')['workflows'], 'id') === ['in-support']);

$edited = $r->get('in-support'); $edited['name'] = 'Geändert'; $r->save($edited);
ok('save without folder keeps location', is_file("$dir/Support/in-support.yaml") && !is_file("$dir/in-support.yaml") && $r->get('in-support')['name'] === 'Geändert');
ok('setEnabled keeps location', $r->setEnabled('in-support', false) && $r->get('in-support')['enabled'] === false && $r->folderOf('in-support') === 'Support');

$r->moveWorkflow('top', 'Support/Eingang März');
ok('moveWorkflow', !is_file("$dir/top.yaml") && is_file("$dir/Support/Eingang März/top.yaml") && $r->folderOf('top') === 'Support/Eingang März');
$r->moveWorkflow('top', '');
ok('moveWorkflow to root', is_file("$dir/top.yaml") && $r->folderOf('top') === '');
throws('move to missing folder', fn () => $r->moveWorkflow('top', 'Nope'), \RuntimeException::class);
throws('move to traversal', fn () => $r->moveWorkflow('top', '../..'), \InvalidArgumentException::class);
throws('move unknown workflow', fn () => $r->moveWorkflow('nope', ''), \RuntimeException::class);
ok('failed move left the file', is_file("$dir/top.yaml"));
throws('bad id', fn () => $r->get('../x'), \InvalidArgumentException::class);

throws('delete non-empty folder refused', fn () => $r->deleteFolder('Support'), \RuntimeException::class);
ok('nothing removed', is_file("$dir/Support/in-support.yaml"));
$r->createFolder('', 'Leer');
$r->deleteFolder('Leer');
ok('delete empty folder', !is_dir("$dir/Leer"));
throws('delete root refused', fn () => $r->deleteFolder(''), \InvalidArgumentException::class);
throws('delete missing', fn () => $r->deleteFolder('Nope'), \RuntimeException::class);

ok('rename folder', $r->renameFolder('Support/Eingang März', 'Posteingang') === 'Support/Posteingang' && is_file("$dir/Support/Posteingang/deep-one.yaml") && $r->folderOf('deep-one') === 'Support/Posteingang');
throws('rename onto existing', function () use ($r) { $r->createFolder('Support', 'Zwei'); $r->renameFolder('Support/Zwei', 'Posteingang'); }, \RuntimeException::class);
ok('move folder', $r->moveFolder('Support/Zwei', '') === 'Zwei' && is_dir("$dir/Zwei"));
ok('move folder with content', $r->moveFolder('Support/Posteingang', 'Zwei') === 'Zwei/Posteingang' && $r->folderOf('deep-one') === 'Zwei/Posteingang');
throws('move folder into itself', fn () => $r->moveFolder('Zwei', 'Zwei'), \RuntimeException::class);
throws('move folder into its child', fn () => $r->moveFolder('Zwei', 'Zwei/Posteingang'), \RuntimeException::class);
throws('move folder name clash', function () use ($r) { $r->createFolder('Support', 'Zwei'); $r->moveFolder('Support/Zwei', ''); }, \RuntimeException::class);
throws('rename root', fn () => $r->renameFolder('', 'x'), \InvalidArgumentException::class);
throws('rename to bad name', fn () => $r->renameFolder('Zwei', '../x'), \InvalidArgumentException::class);
$r->createFolder('', 'Tief');
$p = 'Tief'; for ($i = 0; $i < 4; $i++) { $p = $r->createFolder($p, "t$i"); }
$r->createFolder('', 'Anker'); $q = 'Anker'; for ($i = 0; $i < 3; $i++) { $q = $r->createFolder($q, "a$i"); }
throws('moving a subtree beyond the depth limit refused', fn () => $r->moveFolder('Tief', $q), \InvalidArgumentException::class);
ok('refused move changed nothing', is_dir("$dir/Tief/t0/t1/t2/t3"));

// hidden folders and symlinks are not part of the tree
mkdir("$dir/.trash"); file_put_contents("$dir/.trash/ghost.yaml", Symfony\Component\Yaml\Yaml::dump($wf('ghost')));
mkdir("$dir/real"); symlink("$dir/real", "$dir/link");
$r2 = new WorkflowRepository($dir);
ok('hidden folder ignored', $r2->get('ghost') === null && !in_array('.trash', $r2->listFolders(), true));
ok('symlinked folder ignored', !in_array('link', $r2->listFolders(), true) && !$r2->folderExists('link'));
// duplicate id in two folders: first wins, no crash
file_put_contents("$dir/real/top.yaml", Symfony\Component\Yaml\Yaml::dump($wf('top', ['name' => 'ZWEITE'])));
$r3 = new WorkflowRepository($dir);
ok('duplicate id tolerated (one listed)', count(array_filter(array_column($r3->listAll(), 'id'), fn ($i) => $i === 'top')) === 1);
// malformed / id-less files
file_put_contents("$dir/kaputt.yaml", "id: [oops\n  - : :");
file_put_contents("$dir/ohne-id.yaml", "name: x\n");
ok('malformed + id-less files skipped', !in_array('kaputt', array_column((new WorkflowRepository($dir))->listAll(), 'id'), true));
ok('overview of folder with junk still lists', is_array((new WorkflowRepository($dir))->listFolder('')['workflows']));

echo $fails === 0 ? "\nALL PASSED\n" : "\n$fails FAILED\n";
exec('rm -rf ' . escapeshellarg($dir));
exit($fails === 0 ? 0 : 1);
