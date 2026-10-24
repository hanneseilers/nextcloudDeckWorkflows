<?php
// Standalone check of website/src/LogReader.php (no PHPUnit in this project):
//   php tools/test_log_reader.php   - exits 1 if anything fails. Uses a temp directory.
require __DIR__ . '/../website/vendor/autoload.php';

use NextcloudDeckWorkflows\LogReader;

$dir = sys_get_temp_dir() . '/logreader_' . bin2hex(random_bytes(4));
mkdir($dir);
$fails = 0;
function ok(string $name, bool $cond, $detail = ''): void
{
    global $fails;
    echo ($cond ? 'PASS ' : 'FAIL ') . $name . ($cond ? '' : '  -> ' . json_encode($detail)) . "\n";
    $fails += $cond ? 0 : 1;
}

$r = new LogReader($dir);
ok('nothing exists yet', $r->available() === [] && $r->read('automation')['entries'] === []);
ok('unknown file key', $r->read('../../etc/passwd')['entries'] === []);

file_put_contents("$dir/automation.log", implode("\n", [
    '2026-10-24 10:00:00,100 INFO automation.main: Detected card_created on card 1',
    '2026-10-24 10:00:01,200 WARNING automation.main: Skipping board 7',
    '2026-10-24 10:00:02,300 ERROR automation.core.domain.engine: Action \'add_label\' failed for workflow \'wf1\'',
    'Traceback (most recent call last):',
    '  File "x.py", line 1, in <module>',
    'RuntimeError: boom <script>alert(1)</script>',
    '2026-10-24 10:00:03,400 INFO automation.main: Fixed point reached after 2 iteration(s)',
    '',
]));
file_put_contents("$dir/cron.log", "Traceback (most recent call last):\n  File \"/x/main.py\", line 3\nModuleNotFoundError: No module named 'yaml'\nStarte...\n");

$all = $r->read('automation');
ok('available lists both files', array_keys($r->available()) === ['automation', 'cron']);
ok('4 entries, newest first', count($all['entries']) === 4 && $all['entries'][0]['text'] === 'automation.main: Fixed point reached after 2 iteration(s)', array_column($all['entries'], 'level'));
$err = $all['entries'][1];
ok('a traceback belongs to its ERROR entry', $err['level'] === 'ERROR' && str_contains($err['text'], "Traceback") && str_contains($err['text'], 'RuntimeError: boom'), $err);
ok('time without millis', $all['entries'][3]['time'] === '2026-10-24 10:00:00');
ok('level filter WARNING+', array_column($r->read('automation', 300, 'WARNING')['entries'], 'level') === ['ERROR', 'WARNING']);
ok('level filter ERROR', count($r->read('automation', 300, 'ERROR')['entries']) === 1);
ok('unknown level = no filter', count($r->read('automation', 300, 'NOPE')['entries']) === 4);
ok('text search is case-insensitive and finds traceback text', count($r->read('automation', 300, null, 'RUNTIMEERROR')['entries']) === 1);
ok('search matches nothing', $r->read('automation', 300, null, 'zzz')['entries'] === []);
$limited = $r->read('automation', 2);
ok('limit keeps the newest and reports the total', count($limited['entries']) === 2 && $limited['total'] === 4 && $limited['truncated'] === true, $limited['total']);
$cron = $r->read('cron');
ok('plain console lines become entries, tracebacks flagged ERROR', count($cron['entries']) === 4 && $cron['entries'][1]['level'] === 'ERROR' && $cron['entries'][0]['level'] === 'INFO', array_column($cron['entries'], 'level'));
ok('error filter on cron.log keeps the crash lines', count($r->read('cron', 300, 'ERROR')['entries']) === 3);

// a big file: only the end is read, the partial first line is dropped
$line = fn (int $i) => sprintf("2026-10-24 10:%02d:%02d,000 INFO automation.main: filler line %07d %s", intdiv($i, 60) % 60, $i % 60, $i, str_repeat('x', 100));
$fh = fopen("$dir/automation.log", 'w');
for ($i = 0; $i < 30000; $i++) { fwrite($fh, $line($i) . "\n"); }
fclose($fh);
$start = microtime(true);
$big = $r->read('automation', 300);
ok('big file: newest entry is the last line', str_contains($big['entries'][0]['text'], '0029999'), $big['entries'][0]['text'] ?? '');
ok('big file: truncated flag, 300 entries, fast', $big['truncated'] === true && count($big['entries']) === 300 && microtime(true) - $start < 1.5, microtime(true) - $start);
ok('big file: every read entry is complete (no partial first line)', !array_filter($big['entries'], fn ($e) => !str_starts_with($e['text'], 'automation.main: filler line')));

// invalid UTF-8 must not break json/html output
file_put_contents("$dir/automation.log", "2026-10-24 10:00:00,000 INFO automation.main: bad \xFF\xFE bytes\n");
$bad = $r->read('automation')['entries'][0]['text'];
ok('invalid UTF-8 is repaired', mb_check_encoding($bad, 'UTF-8') && str_contains($bad, 'bad'), bin2hex($bad));

echo $fails === 0 ? "\nALL PASSED\n" : "\n$fails FAILED\n";
exec('rm -rf ' . escapeshellarg($dir));
exit($fails === 0 ? 0 : 1);
