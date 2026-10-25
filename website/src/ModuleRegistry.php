<?php

namespace NextcloudDeckWorkflows;

/**
 * Reads automation/var/modules.json, written by `python -m automation.main`
 * (any mode - see automation/main.py::_write_modules_snapshot). No shell_exec
 * of Python is needed from PHP, which is often disabled on shared webspace -
 * the snapshot file is refreshed on every automation run instead.
 *
 * After an update the file is still the old version's until the next run - with
 * a cron job every few hours the editor would offer the old fields (and refuse
 * a new module as "unknown") for hours. So the snapshot carries a fingerprint
 * of the modules' code (automation/adapters/actions/loader.py::code_fingerprint),
 * isFresh() compares it with the code that is there now, and refreshInBackground()
 * has the automation write a new one right away (best effort, see AutomationRunner).
 */
class ModuleRegistry
{
    /** @var array<int, array{name: string, requires: array<int, string>, input: array, output: array}>|null */
    private ?array $modules = null;

    public function __construct(private readonly string $snapshotPath)
    {
    }

    public static function fromRepoRoot(): self
    {
        return new self(dirname(__DIR__, 2) . '/automation/var/modules.json');
    }

    /** @return array<int, array{name: string, requires: array<int, string>, input: array, output: array}> */
    public function all(): array
    {
        // Lazy: a page that only needs isAvailable()/rawModulesJson() (both
        // read the snapshot file their own way) never triggers this
        // assoc-array decode at all - index.php and new.php are exactly
        // that case; only save.php's get() actually needs it.
        return $this->modules ??= $this->load();
    }

    public function get(string $name): ?array
    {
        foreach ($this->all() as $module) {
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

    /** Where the modules' code lives, relative to automation/ - the same list as FINGERPRINT_DIRS in loader.py. */
    private const FINGERPRINT_DIRS = ['actions_registry', 'adapters/actions'];

    /**
     * The fingerprint of the code that is installed now: sha1 over
     * "<path>\0<sha1 of the content>\n" for every *.py of the module folders,
     * sorted by path - computed exactly like code_fingerprint() in Python.
     */
    public function currentFingerprint(): string
    {
        $automation = dirname($this->snapshotPath, 2);
        $entries = [];
        foreach (self::FINGERPRINT_DIRS as $directory) {
            foreach (glob($automation . '/' . $directory . '/*.py') ?: [] as $file) {
                $entries[$directory . '/' . basename($file)] = sha1_file($file);
            }
        }
        ksort($entries, SORT_STRING);
        $digest = '';
        foreach ($entries as $relative => $contentHash) {
            $digest .= $relative . "\0" . $contentHash . "\n";
        }
        return sha1($digest);
    }

    /** The fingerprint the snapshot was written with, '' if it has none (written by an older version). */
    public function snapshotFingerprint(): string
    {
        if (!is_file($this->snapshotPath)) {
            return '';
        }
        $data = json_decode((string) file_get_contents($this->snapshotPath), true);
        return is_array($data) && is_string($data['fingerprint'] ?? null) ? $data['fingerprint'] : '';
    }

    /** True if the module list was written by the code that is installed now. */
    public function isFresh(): bool
    {
        return $this->isAvailable() && hash_equals($this->currentFingerprint(), $this->snapshotFingerprint());
    }

    /**
     * Asks for a new module list if the current one is missing or outdated - at
     * most once every 30 seconds however many pages are opened meanwhile. True
     * if the list is fresh already, false if a refresh was (or just had been)
     * started or couldn't be (then the next automation run writes it).
     */
    public function refreshIfStale(): bool
    {
        if ($this->isFresh()) {
            return true;
        }
        $marker = dirname($this->snapshotPath) . '/modules.refresh';
        if (!is_file($marker) || filemtime($marker) < time() - 30) {
            @touch($marker);
            AutomationRunner::refreshModules();
        }
        return false;
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
