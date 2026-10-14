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

    /** @return array<int, array{id: int, title: string}> */
    public function listBoards(): array
    {
        $boards = $this->get(self::DECK_API . '/boards') ?? [];
        return array_map(
            static fn (array $board) => ['id' => (int) $board['id'], 'title' => (string) $board['title']],
            $boards
        );
    }

    /** @return array<int, array{id: int, title: string}> */
    public function listStacks(int $boardId): array
    {
        $stacks = $this->get(self::DECK_API . '/boards/' . $boardId . '/stacks') ?? [];
        return array_map(
            static fn (array $stack) => ['id' => (int) $stack['id'], 'title' => (string) $stack['title']],
            $stacks
        );
    }

    /**
     * Searches Nextcloud users by (partial) name, for the assign_user/
     * unassign_user user-id picker. Returns at most one entry per user id,
     * exact matches first.
     *
     * @return array<int, array{id: string, label: string}>
     */
    public function searchUsers(string $query): array
    {
        $response = $this->request(self::SHAREES_API, [
            'format' => 'json',
            'search' => $query,
            'itemType' => 'file',
            'shareType' => 0, // users only, not groups/circles/etc.
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

        $users = [];
        foreach ([$data['exact']['users'] ?? [], $data['users'] ?? []] as $group) {
            foreach ($group as $entry) {
                $id = (string) ($entry['value']['shareWith'] ?? '');
                if ($id !== '' && !isset($users[$id])) {
                    $users[$id] = ['id' => $id, 'label' => (string) ($entry['label'] ?? $id)];
                }
            }
        }
        return array_values($users);
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
        return self::mapPropfindCalendars($xml, $basePath);
    }

    /**
     * Pulled out as a pure function (no network, no $this) so it can be unit
     * tested directly against a sample PROPFIND response, same as
     * mapShareesResponse() above.
     *
     * @return array<int, array{id: string, title: string}>
     */
    private static function mapPropfindCalendars(string $xml, string $basePath): array
    {
        $doc = new \DOMDocument();
        if (!@$doc->loadXML($xml)) {
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
            $href = (string) $xpath->evaluate('string(d:href)', $response);
            if (rtrim($href, '/') === rtrim($basePath, '/')) {
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

        $handle = curl_init($url);
        curl_setopt_array($handle, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => ['OCS-APIRequest: true', 'Accept: application/json'],
            CURLOPT_USERPWD => $this->username . ':' . $this->appPassword,
            CURLOPT_TIMEOUT => 15,
        ]);
        $body = curl_exec($handle);
        $error = curl_error($handle);
        $status = curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
        curl_close($handle);

        if ($body === false) {
            throw new \RuntimeException("Nextcloud request to $path failed: $error");
        }
        if ($status < 200 || $status >= 300) {
            throw new \RuntimeException("Nextcloud request to $path failed: HTTP $status");
        }

        $data = json_decode($body, true);
        if (!is_array($data)) {
            throw new \RuntimeException("Nextcloud request to $path returned an unexpected response");
        }
        return $data;
    }

    private function requestXml(string $method, string $path, string $body, int $depth): string
    {
        $handle = curl_init($this->baseUrl . $path);
        curl_setopt_array($handle, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CUSTOMREQUEST => $method,
            CURLOPT_HTTPHEADER => ['Content-Type: application/xml; charset=utf-8', 'Depth: ' . $depth],
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_USERPWD => $this->username . ':' . $this->appPassword,
            CURLOPT_TIMEOUT => 15,
        ]);
        $responseBody = curl_exec($handle);
        $error = curl_error($handle);
        $status = curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
        curl_close($handle);

        if ($responseBody === false) {
            throw new \RuntimeException("Nextcloud CalDAV request to $path failed: $error");
        }
        if ($status < 200 || $status >= 300) {
            throw new \RuntimeException("Nextcloud CalDAV request to $path failed: HTTP $status");
        }
        return $responseBody;
    }
}
