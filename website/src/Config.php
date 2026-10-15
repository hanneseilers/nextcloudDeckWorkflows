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

        if (!empty($settings['webhooks'])) {
            $this->webhooks = [
                'enabled' => (bool) ($settings['webhooks']['enabled'] ?? true),
                'secret' => (string) $settings['webhooks']['secret'],
                'fallback_poll_minutes' => (float) ($settings['webhooks']['fallback_poll_minutes'] ?? 15.0),
            ];
        }
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

    /** @return array{enabled: bool, secret: string, fallback_poll_minutes: float}|null */
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
