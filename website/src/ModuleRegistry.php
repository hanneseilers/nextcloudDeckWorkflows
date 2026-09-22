<?php

namespace NextcloudDeckWorkflows;

/**
 * Reads automation/var/modules.json, written by `python -m automation.main`
 * (any mode - see automation/main.py::_write_modules_snapshot). No shell_exec
 * of Python is needed from PHP, which is often disabled on shared webspace -
 * the snapshot file is refreshed on every automation run instead.
 */
class ModuleRegistry
{
    /** @var array<int, array{name: string, requires: array<int, string>, input: array, output: array}> */
    private array $modules;

    public function __construct(private readonly string $snapshotPath)
    {
        $this->modules = $this->load();
    }

    public static function fromRepoRoot(): self
    {
        return new self(dirname(__DIR__, 2) . '/automation/var/modules.json');
    }

    /** @return array<int, array{name: string, requires: array<int, string>, input: array, output: array}> */
    public function all(): array
    {
        return $this->modules;
    }

    public function get(string $name): ?array
    {
        foreach ($this->modules as $module) {
            if ($module['name'] === $name) {
                return $module;
            }
        }
        return null;
    }

    public function isAvailable(): bool
    {
        return is_file($this->snapshotPath);
    }

    /**
     * The snapshot file's raw JSON text (the `modules` array), for embedding
     * directly into a page. Deliberately not re-encoded through PHP's
     * json_decode($x, true)/json_encode() round-trip: PHP arrays can't
     * distinguish an empty JSON object {} (e.g. an action with no declared
     * output) from an empty JSON array [], so a round-trip would silently
     * turn every {} from Python into [] in the browser.
     */
    public function rawModulesJson(): string
    {
        if (!is_file($this->snapshotPath)) {
            return '[]';
        }
        // Decoded WITHOUT assoc=true, so JSON objects become stdClass and JSON
        // arrays stay PHP arrays - re-encoding then preserves {} vs [] exactly
        // as Python wrote it (see the doc comment above).
        $decoded = json_decode(file_get_contents($this->snapshotPath));
        $modules = is_object($decoded) && isset($decoded->modules) ? $decoded->modules : [];
        return json_encode($modules, JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_HEX_AMP);
    }

    private function load(): array
    {
        if (!is_file($this->snapshotPath)) {
            return [];
        }
        $data = json_decode(file_get_contents($this->snapshotPath), true);
        return is_array($data['modules'] ?? null) ? $data['modules'] : [];
    }
}
