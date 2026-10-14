<?php

namespace NextcloudDeckWorkflows;

/**
 * Shared boilerplate for every api_*.php JSON endpoint: JSON content type,
 * loads Config, looks up the "instance" query param (400 if unknown), builds
 * a NextcloudApi for it, and turns any failure into a JSON {"error": ...}
 * response instead of a PHP error page - 400 for a bad request (the
 * callback throws ApiBadRequestException), 502 for anything else (an
 * unreachable/misbehaving Nextcloud instance), matching the Python side's
 * "log and skip, never crash" approach to the same problem.
 */
class ApiEndpoint
{
    /** @param callable(NextcloudApi): array $callback Returns the JSON response body's data. */
    public static function run(callable $callback): void
    {
        header('Content-Type: application/json');

        $config = Config::fromRepoRoot();
        $instanceName = (string) ($_GET['instance'] ?? '');
        $instance = $config->instance($instanceName);

        if ($instance === null) {
            self::fail(400, "Unknown Nextcloud instance '$instanceName'");
            return;
        }

        try {
            $api = new NextcloudApi($instance['url'], $instance['username'], $instance['app_password']);
            echo json_encode($callback($api));
        } catch (ApiBadRequestException $e) {
            self::fail(400, $e->getMessage());
        } catch (\Throwable $e) {
            self::fail(502, 'Could not reach Nextcloud: ' . $e->getMessage());
        }
    }

    private static function fail(int $status, string $message): void
    {
        http_response_code($status);
        echo json_encode(['error' => $message]);
    }
}
