<?php
// Standalone check for NextcloudApi's pure response mappers (no PHPUnit in
// this project, see AGENTS.md): php tools/test_nextcloud_api.php
declare(strict_types=1);

require __DIR__ . '/../website/vendor/autoload.php';

use NextcloudDeckWorkflows\NextcloudApi;

$failures = 0;
function check(string $name, bool $ok): void
{
    global $failures;
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . "\n";
    if (!$ok) {
        $failures++;
    }
}

$map = new ReflectionMethod(NextcloudApi::class, 'mapPropfindCalendars');

function propfind(string $home, array $calendars): string
{
    $xml = '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        . "<d:response><d:href>$home</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>";
    foreach ($calendars as $href => $name) {
        $xml .= "<d:response><d:href>$href</d:href><d:propstat><d:prop><d:displayname>$name</d:displayname>"
            . '<d:resourcetype><d:collection/><c:calendar/></d:resourcetype></d:prop></d:propstat></d:response>';
    }
    return $xml . '</d:multistatus>';
}

$home = '/remote.php/dav/calendars/alice/';
check('root install: ids are the hrefs, home collection skipped',
    $map->invoke(null, propfind($home, [$home . 'personal/' => 'Privat']), $home, '')
        === [['id' => $home . 'personal/', 'title' => 'Privat']]);

$served = '/nextcloud/remote.php/dav/calendars/alice/';
check('subdirectory install: prefix stripped from the id, home collection still skipped',
    $map->invoke(null, propfind($served, [$served . 'work/' => 'Arbeit']), $home, '/nextcloud')
        === [['id' => $home . 'work/', 'title' => 'Arbeit']]);

check('absolute URL hrefs are reduced to the relative path',
    $map->invoke(null, propfind('https://h.example' . $served, ['https://h.example' . $served . 'x/' => 'X']), $home, '/nextcloud/')
        === [['id' => $home . 'x/', 'title' => 'X']]);

$encodedHome = '/remote.php/dav/calendars/anna%40example.org/';
check('encoded user name: home collection recognised either way',
    $map->invoke(null, propfind('/remote.php/dav/calendars/anna@example.org/', []), $encodedHome, '') === []);

check('a DOCTYPE/entity answer is refused (empty list)', $map->invoke(null, '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]>' . propfind($home, [$home . 'p/' => '&a;']), $home, '') === []);
check('malformed XML gives an empty list', $map->invoke(null, 'not xml', $home, '') === []);

echo $failures === 0 ? "ALL PASSED\n" : "$failures FAILED\n";
exit($failures === 0 ? 0 : 1);
