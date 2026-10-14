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

    public function __construct(string $configDir)
    {
        $nextcloud = $this->readYaml($configDir . '/nextcloud.yaml');
        foreach ($nextcloud['instances'] ?? [] as $instance) {
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

    private function readYaml(string $path): array
    {
        if (!is_file($path)) {
            return [];
        }
        return Yaml::parseFile($path) ?? [];
    }
}
