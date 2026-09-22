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

    private function get(string $path): ?array
    {
        $handle = curl_init($this->baseUrl . $path);
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
}
