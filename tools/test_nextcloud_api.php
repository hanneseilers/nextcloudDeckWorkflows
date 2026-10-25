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

$sharees = new ReflectionMethod(NextcloudApi::class, 'mapShareesResponse');
$entry = fn (string $label, string $with, int $type) => ['label' => $label, 'value' => ['shareType' => $type, 'shareWith' => $with]];
$response = ['ocs' => ['data' => [
    'exact' => ['users' => [$entry('Anna Schmidt', 'anna', 0)], 'groups' => [$entry('Förderkreis', 'foerderkreis', 1)]],
    'users' => [$entry('Anna Schmidt', 'anna', 0), $entry('Annabelle', 'annabelle', 0)],
    'groups' => [$entry('Förderkreis', 'foerderkreis', 1), $entry('Anna-Team', 'anna-team', 1)],
]]];
$found = $sharees->invoke(null, $response);
check('sharees: users first with the plain id, then groups as group:<id> labelled "Gruppe: ..."', $found === [
    ['id' => 'anna', 'label' => 'Anna Schmidt'],
    ['id' => 'annabelle', 'label' => 'Annabelle'],
    ['id' => 'group:foerderkreis', 'label' => 'Gruppe: Förderkreis'],
    ['id' => 'group:anna-team', 'label' => 'Gruppe: Anna-Team'],
]);
check('sharees: a group named like a user is a separate entry', count($sharees->invoke(null, ['ocs' => ['data' => [
    'users' => [$entry('Staff', 'staff', 0)], 'groups' => [$entry('Staff', 'staff', 1)]]]])) === 2);
check('sharees: only users (no groups key) still works, and so does an empty answer',
    $sharees->invoke(null, ['ocs' => ['data' => ['users' => [$entry('A', 'a', 0)]]]]) === [['id' => 'a', 'label' => 'A']]
    && $sharees->invoke(null, []) === []);

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
