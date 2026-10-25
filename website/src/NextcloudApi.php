<?php

namespace NextcloudDeckWorkflows;

/**
 * Read-only Nextcloud Deck API access for the website (board/stack pickers).
 * Mirrors automation/adapters/nextcloud/client.py + deck_gateway.py's list_*
 * methods - the website never needs the write endpoints, only Python executes
 * actions. Credentials are used here, server-side, and never sent to the browser.
 */
class NextcloudApi
{
    private const DECK_API = '/index.php/apps/deck/api/v1.1';
    // The "sharees" endpoint backs Nextcloud's own share-with-a-user
    // autocomplete, so - unlike the admin-only user-provisioning API - it
    // works for any authenticated user/app password, which is what we have.
    private const SHAREES_API = '/ocs/v2.php/apps/files_sharing/api/v1/sharees';
    // Same CalDAV calendar-home convention automation/adapters/nextcloud/
    // calendar_gateway.py uses - a calendar's "id" the calendar_lookup action
    // takes is its CalDAV href from here, unchanged.
    private const CALDAV_CALENDARS = '/remote.php/dav/calendars/';
    private const DAV_NS = 'DAV:';
    private const CALDAV_NS = 'urn:ietf:params:xml:ns:caldav';

    private string $baseUrl;
    private string $username;
    private string $appPassword;

    public function __construct(string $baseUrl, string $username, string $appPassword)
    {
        $this->baseUrl = rtrim($baseUrl, '/');
        $this->username = $username;
        $this->appPassword = $appPassword;
    }

    /** @return array<int, array{id: int, title: string, archived: bool}> */
    public function listBoards(): array
    {
        $boards = $this->get(self::DECK_API . '/boards') ?? [];
        return array_map(
            static fn (array $board) => [
                'id' => (int) $board['id'],
                'title' => (string) $board['title'],
                'archived' => !empty($board['archived']),
            ],
            $boards
        );
    }

    /** @return array<int, array{id: int, title: string, card_count: int}> */
    public function listStacks(int $boardId): array
    {
        $stacks = $this->get(self::DECK_API . '/boards/' . $boardId . '/stacks') ?? [];
        return array_map(
            static fn (array $stack) => [
                'id' => (int) $stack['id'],
                'title' => (string) $stack['title'],
                // The stacks endpoint embeds the (non-archived) cards.
                'card_count' => count($stack['cards'] ?? []),
            ],
            $stacks
        );
    }

    /**
     * The labels defined on a board, for the add_label label picker and
     * boards.php. Deck's single-board endpoint embeds them as `labels`
     * (documented; not verified against a live instance) - a missing/odd
     * `labels` key just yields an
     * empty picker (the field still accepts a typed label id).
     *
     * @return array<int, array{id: int, title: string, color: string}>
     */
    public function listLabels(int $boardId): array
    {
        $board = $this->get(self::DECK_API . '/boards/' . $boardId) ?? [];
        $labels = [];
        foreach ($board['labels'] ?? [] as $label) {
            $labels[] = [
                'id' => (int) $label['id'],
                'title' => (string) $label['title'],
                'color' => (string) ($label['color'] ?? ''), // hex without '#', e.g. "31CC7C"
            ];
        }
        return $labels;
    }

    /**
     * Every card across every stack of a board, for the "Testlauf" card
     * picker - the stacks endpoint already embeds each stack's cards (same
     * response DeckGatewayPort.list_cards() filters by stack on the Python
     * side), just not kept by listStacks() above.
     *
     * @return array<int, array{id: int, title: string}>
     */
    public function listCards(int $boardId): array
    {
        $stacks = $this->get(self::DECK_API . '/boards/' . $boardId . '/stacks') ?? [];
        $cards = [];
        foreach ($stacks as $stack) {
            foreach ($stack['cards'] ?? [] as $card) {
                $cards[] = ['id' => (int) $card['id'], 'title' => (string) $card['title']];
            }
        }
        return $cards;
    }

    /**
     * Searches Nextcloud users AND groups by (partial) name, for the assign_user/
     * unassign_user picker. A user is returned with the plain user id, a group
     * as `group:<group id>` (the token the automation reads, see
     * automation/adapters/actions/user_ids.py) with "Gruppe: <name>" as label.
     * At most one entry per id, exact matches first, users before groups.
     *
     * Which groups show up is Nextcloud's decision (sharing with groups can be
     * switched off, or limited to the searcher's own groups).
     *
     * @return array<int, array{id: string, label: string}>
     */
    public function searchUsers(string $query): array
    {
        $response = $this->request(self::SHAREES_API, [
            'format' => 'json',
            'search' => $query,
            'itemType' => 'file',
            'shareType' => [0, 1], // users and groups (not teams/emails/remote)
        ]);
        return self::mapShareesResponse(is_array($response) ? $response : []);
    }

    /**
     * Pulled out as a pure function (no network, no $this) so it can be unit
     * tested directly against a sample OCS response.
     *
     * @return array<int, array{id: string, label: string}>
     */
    private static function mapShareesResponse(array $response): array
    {
        $data = $response['ocs']['data'] ?? [];

        $found = [];
        // users first (exact matches before the rest), then the groups the same way
        foreach (['users' => '', 'groups' => 'group:'] as $key => $prefix) {
            foreach ([$data['exact'][$key] ?? [], $data[$key] ?? []] as $entries) {
                foreach ($entries as $entry) {
                    $id = (string) ($entry['value']['shareWith'] ?? '');
                    if ($id === '' || isset($found[$prefix . $id])) {
                        continue;
                    }
                    $label = (string) ($entry['label'] ?? $id);
                    $found[$prefix . $id] = [
                        'id' => $prefix . $id,
                        'label' => $prefix === '' ? $label : 'Gruppe: ' . $label,
                    ];
                }
            }
        }
        return array_values($found);
    }

    /**
     * Lists the calendars in the signed-in user's CalDAV calendar-home, for
     * the calendar_lookup action's calendar_id picker. "id" is the raw
     * CalDAV href - calendar_lookup (automation side) takes the exact same
     * string, so no translation happens in either direction.
     *
     * @return array<int, array{id: string, title: string}>
     */
    public function listCalendars(): array
    {
        $basePath = self::CALDAV_CALENDARS . rawurlencode($this->username) . '/';
        $body = '<?xml version="1.0" encoding="utf-8"?>'
            . '<d:propfind xmlns:d="DAV:">'
            . '<d:prop><d:displayname/><d:resourcetype/></d:prop>'
            . '</d:propfind>';
        $xml = $this->requestXml('PROPFIND', $basePath, $body, 1);
        return self::mapPropfindCalendars($xml, $basePath, (string) parse_url($this->baseUrl, PHP_URL_PATH));
    }

    /**
     * Pulled out as a pure function (no network, no $this) so it can be unit
     * tested directly against a sample PROPFIND response, same as
     * mapShareesResponse() above.
     *
     * @return array<int, array{id: string, title: string}>
     */
    private static function mapPropfindCalendars(string $xml, string $basePath, string $urlPrefix = ''): array
    {
        // A real CalDAV answer has no DOCTYPE; refusing one rules out entity tricks
        // (and LIBXML_NONET forbids network access while parsing).
        if (stripos(substr($xml, 0, 4096), '<!DOCTYPE') !== false || stripos(substr($xml, 0, 4096), '<!ENTITY') !== false) {
            return [];
        }
        $doc = new \DOMDocument();
        if (!@$doc->loadXML($xml, LIBXML_NONET)) {
            return []; // malformed response must not break the picker - just show no calendars
        }
        $xpath = new \DOMXPath($doc);
        $xpath->registerNamespace('d', self::DAV_NS);
        $xpath->registerNamespace('c', self::CALDAV_NS);

        $calendars = [];
        $responses = $xpath->query('//d:response');
        if ($responses === false) {
            return [];
        }
        foreach ($responses as $response) {
            $href = self::relativeHref((string) $xpath->evaluate('string(d:href)', $response), $urlPrefix);
            if (rawurldecode(rtrim($href, '/')) === rawurldecode(rtrim($basePath, '/'))) {
                continue; // the calendar-home collection itself, not a calendar in it
            }
            $isCalendar = $xpath->query('.//d:propstat/d:prop/d:resourcetype/c:calendar', $response);
            if ($isCalendar === false || $isCalendar->length === 0) {
                continue;
            }
            $displayname = trim((string) $xpath->evaluate('string(.//d:propstat/d:prop/d:displayname)', $response));
            $title = $displayname !== '' ? $displayname : basename(rtrim($href, '/'));
            $calendars[] = ['id' => $href, 'title' => $title];
        }
        return $calendars;
    }

    /**
     * A Nextcloud in a subdirectory (https://host/nextcloud) answers with
     * hrefs including that prefix, but requests go to baseUrl + path - so the
     * calendar id is stored relative to the base URL. Mirrors
     * NextcloudCalendarGateway._relative() on the Python side, which also
     * accepts ids that still carry the prefix.
     */
    private static function relativeHref(string $href, string $urlPrefix): string
    {
        $path = str_contains($href, '://') ? (string) parse_url($href, PHP_URL_PATH) : $href;
        $prefix = rtrim($urlPrefix, '/');
        if ($prefix !== '' && str_starts_with($path, $prefix . '/')) {
            $path = substr($path, strlen($prefix));
        }
        return $path;
    }

    private function get(string $path): ?array
    {
        $data = $this->request($path);
        return is_array($data) ? $data : null;
    }

    private function request(string $path, array $query = []): mixed
    {
        $url = $this->baseUrl . $path;
        if ($query !== []) {
            $url .= '?' . http_build_query($query);
        }

        $body = $this->curlRequest($url, [
            CURLOPT_HTTPHEADER => ['OCS-APIRequest: true', 'Accept: application/json'],
        ], "Nextcloud request to $path");

        $data = json_decode($body, true);
        if (!is_array($data)) {
            throw new \RuntimeException("Nextcloud request to $path returned an unexpected response");
        }
        return $data;
    }

    private function requestXml(string $method, string $path, string $body, int $depth): string
    {
        return $this->curlRequest($this->baseUrl . $path, [
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_HTTPHEADER => ['Content-Type: application/xml; charset=utf-8', 'Depth: ' . $depth],
            CURLOPT_POSTFIELDS => $body,
        ], "Nextcloud CalDAV request to $path");
    }

    /**
     * Shared curl lifecycle for request()/requestXml() - init, auth/timeout,
     * exec, status check, close. `$options` are the caller's own curl_setopt
     * entries (method/headers/body); `$errorContext` is prepended to both
     * failure messages so request() and requestXml() keep their own distinct
     * wording ("Nextcloud request" vs "Nextcloud CalDAV request").
     */
    private function curlRequest(string $url, array $options, string $errorContext): string
    {
        $handle = curl_init($url);
        curl_setopt_array($handle, $options + [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_USERPWD => $this->username . ':' . $this->appPassword,
            CURLOPT_TIMEOUT => 15,
            CURLOPT_CONNECTTIMEOUT => 5, // an unreachable host must not hold a PHP worker for the whole timeout
            CURLOPT_FOLLOWLOCATION => false, // never send the app password to wherever a redirect points
        ]);
        $body = curl_exec($handle);
        $error = curl_error($handle);
        $status = curl_getinfo($handle, CURLINFO_RESPONSE_CODE);

        if ($body === false) {
            throw new \RuntimeException("$errorContext failed: $error");
        }
        if ($status < 200 || $status >= 300) {
            throw new \RuntimeException("$errorContext failed: HTTP $status");
        }
        return $body;
    }
}
