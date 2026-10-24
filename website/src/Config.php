<?php

namespace NextcloudDeckWorkflows;

use Symfony\Component\Yaml\Yaml;

/**
 * Loads the same config/nextcloud.yaml and config/settings.yaml the Python
 * automation reads (see automation/config/settings.py) - one shared source of
 * truth for Nextcloud instances and general settings.
 */
class Config
{
    /** @var array<string, array{name: string, url: string, username: string, app_password: string}> */
    private array $instances = [];
    private string $workflowsDir;
    private string $stateDbPath;
    /** @var array{enabled: bool, secret: string, fallback_poll_minutes: float}|null */
    private ?array $webhooks = null;
    private float $healthStaleMinutes = 15.0;

    public function __construct(string $configDir)
    {
        $nextcloud = $this->readYaml($configDir . '/nextcloud.yaml');
        foreach ($nextcloud['instances'] ?? [] as $instance) {
            if (isset($instance['encrypted_app_password']) && !isset($instance['app_password'])) {
                $instance['app_password'] = $this->decryptAppPassword($instance['encrypted_app_password'], $configDir);
            }
            $this->instances[$instance['name']] = $instance;
        }

        $settings = $this->readYaml($configDir . '/settings.yaml');
        $workflowsDir = $settings['workflows_dir'] ?? 'workflows';
        $this->workflowsDir = str_starts_with($workflowsDir, '/')
            ? $workflowsDir
            : dirname($configDir) . '/' . $workflowsDir;

        $stateDbPath = $settings['state_db_path'] ?? 'automation/var/state.sqlite3';
        $this->stateDbPath = str_starts_with($stateDbPath, '/')
            ? $stateDbPath
            : dirname($configDir) . '/' . $stateDbPath;

        // Display only (every stored timestamp is UTC and compared as such):
        // the timezone the pages show times in.
        $timezone = (string) ($settings['timezone'] ?? 'Europe/Berlin');
        if (in_array($timezone, \DateTimeZone::listIdentifiers(), true)) {
            date_default_timezone_set($timezone);
        }

        if (isset($settings['health_stale_minutes']) && (float) $settings['health_stale_minutes'] > 0) {
            $this->healthStaleMinutes = (float) $settings['health_stale_minutes'];
        }

        if (!empty($settings['webhooks'])) {
            $rawSecret = $settings['webhooks']['secret'] ?? '';
            $this->webhooks = [
                'enabled' => (bool) ($settings['webhooks']['enabled'] ?? true),
                'secret' => is_string($rawSecret) ? $rawSecret : '',
                // Why webhook.php must not accept this secret (null = fine).
                'secret_problem' => self::webhookSecretProblem($rawSecret),
                'require_https' => (bool) ($settings['webhooks']['require_https'] ?? true),
                'fallback_poll_minutes' => (float) ($settings['webhooks']['fallback_poll_minutes'] ?? 15.0),
            ];
        }
    }

    /** A webhook secret shorter than this is refused (webhook.php answers as if webhooks were off). */
    public const MIN_WEBHOOK_SECRET_LENGTH = 24;

    /** @return string|null German reason the secret can't be used, null if it's fine */
    public static function webhookSecretProblem(mixed $secret): ?string
    {
        if (!is_string($secret)) {
            // YAML turns an unquoted 123456... into a number, losing digits.
            return $secret === null || $secret === ''
                ? 'Kein Secret gesetzt.'
                : 'Das Secret muss ein Text sein - in settings.yaml in Anführungszeichen setzen.';
        }
        if ($secret === '') {
            return 'Kein Secret gesetzt.';
        }
        if (stripos($secret, 'CHANGE_ME') === 0) {
            return 'Das Secret ist noch der Platzhalter aus der Vorlage.';
        }
        if (strlen($secret) < self::MIN_WEBHOOK_SECRET_LENGTH) {
            return 'Das Secret ist zu kurz (mindestens ' . self::MIN_WEBHOOK_SECRET_LENGTH . ' Zeichen).';
        }
        return null;
    }

    public static function fromRepoRoot(): self
    {
        return new self(dirname(__DIR__, 2) . '/config');
    }

    /** @return array<string, array{name: string, url: string, username: string, app_password: string}> */
    public function instances(): array
    {
        return $this->instances;
    }

    public function instance(string $name): ?array
    {
        return $this->instances[$name] ?? null;
    }

    public function workflowsDir(): string
    {
        return $this->workflowsDir;
    }

    public function stateDbPath(): string
    {
        return $this->stateDbPath;
    }

    public function healthStaleMinutes(): float
    {
        return $this->healthStaleMinutes;
    }

    /** @return array{enabled: bool, secret: string, secret_problem: ?string, require_https: bool, fallback_poll_minutes: float}|null */
    public function webhooks(): ?array
    {
        return $this->webhooks;
    }

    private function readYaml(string $path): array
    {
        if (!is_file($path)) {
            return [];
        }
        return Yaml::parseFile($path) ?? [];
    }

    /**
     * See automation/config/secrets.py - an instance can have
     * `encrypted_app_password` instead of a plaintext `app_password`,
     * decrypted the same way (Fernet) using the same config/secret.key.
     */
    private function decryptAppPassword(string $encrypted, string $configDir): string
    {
        $keyPath = $configDir . '/secret.key';
        if (!is_file($keyPath)) {
            throw new \RuntimeException(
                "Missing $keyPath - needed to decrypt an encrypted_app_password entry in nextcloud.yaml "
                . "(generate it with: python -m automation.config.secrets generate-key)"
            );
        }
        return Fernet::decrypt($encrypted, trim(file_get_contents($keyPath)));
    }
}
