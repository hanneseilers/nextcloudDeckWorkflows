<?php

namespace NextcloudDeckWorkflows;

use Symfony\Component\Yaml\Yaml;

/**
 * Reads/writes workflow YAML files in the same directory and exact schema the
 * Python side expects
 * (automation/adapters/persistence/yaml_workflow_repository.py::_parse/_to_dict):
 *
 *   id, name, enabled, nextcloud_instance, board_id,
 *   trigger: {event, stack_id?},
 *   actions: [{id?, module, params}]
 *
 * A param value of {"$ref": "<step_id>.<field>"} (see
 * automation/core/domain/engine.py::_resolve_params) maps another step's
 * output into this one - the website just passes that shape through as-is.
 *
 * Workflows may live in subfolders of the workflows directory (real
 * directories, nested up to MAX_DEPTH levels) - folders only organize the
 * files: the id stays unique across all of them, the file is always
 * <id>.yaml, and the Python side reads the whole tree. A folder is
 * addressed by its relative path ("" = top level, "support/tickets").
 *
 * Workflows are plain associative arrays here, not objects - the website only
 * lists/creates/toggles/deletes them; the actual domain logic (matching
 * events, running action chains) lives entirely in Python.
 */
class WorkflowRepository
{
    public const MAX_DEPTH = 6;

    /** @var array<string, string>|null id => absolute path, built lazily, dropped on every write */
    private ?array $index = null;

    public function __construct(private readonly string $directory)
    {
        if (!is_dir($this->directory)) {
            mkdir($this->directory, 0775, true);
        }
    }

    // -- workflows ---------------------------------------------------------

    /** @return array<int, array<string, mixed>> every workflow in every folder, sorted by id */
    public function listAll(): array
    {
        $workflows = [];
        foreach ($this->locations() as $path) {
            $data = $this->read($path);
            if ($data !== null) {
                $workflows[] = $data;
            }
        }
        usort($workflows, static fn ($a, $b) => strcmp($a['id'] ?? '', $b['id'] ?? ''));
        return $workflows;
    }

    public function exists(string $id): bool
    {
        return $this->locate($id) !== null;
    }

    public function get(string $id): ?array
    {
        $path = $this->locate($id);
        return $path === null ? null : $this->read($path);
    }

    /** The folder a workflow lives in ("" = top level), or null if there is no such workflow. */
    public function folderOf(string $id): ?string
    {
        $path = $this->locate($id);
        return $path === null ? null : $this->relativeFolder(dirname($path));
    }

    /**
     * Writes the workflow. A workflow that exists is rewritten where it
     * lives; `$folder` (when given) puts it there - for a new workflow the
     * folder to create it in, for an existing one a move.
     *
     * @param array<string, mixed> $workflow
     */
    public function save(array $workflow, ?string $folder = null): void
    {
        $existing = $this->locate($workflow['id']);
        $targetFolder = $folder !== null
            ? self::normalizeFolder($folder)
            : ($existing !== null ? $this->relativeFolder(dirname($existing)) : '');
        $this->requireFolder($targetFolder);

        $target = $this->dirFor($targetFolder) . '/' . $workflow['id'] . '.yaml';
        file_put_contents($target, Yaml::dump($workflow, 10, 2));
        if ($existing !== null && $existing !== $target) {
            unlink($existing);
        }
        $this->index = null;
    }

    public function delete(string $id): void
    {
        $path = $this->locate($id);
        if ($path !== null) {
            unlink($path);
        }
        $this->index = null;
    }

    public function moveWorkflow(string $id, string $folder): void
    {
        $workflow = $this->get($id);
        if ($workflow === null) {
            throw new \RuntimeException("Workflow '$id' nicht gefunden.");
        }
        $this->save($workflow, $folder);
    }

    public function setEnabled(string $id, bool $enabled): bool
    {
        $workflow = $this->get($id);
        if ($workflow === null) {
            return false;
        }
        $workflow['enabled'] = $enabled;
        $this->save($workflow);
        return true;
    }

    // -- folders -----------------------------------------------------------

    /**
     * Validates a folder path ("a/b") and returns it normalized ("" for the
     * top level). Every segment must be a plain name - letters (incl.
     * umlauts), digits, spaces, "-" and "_", starting with a letter or digit
     * - so no "..", no hidden folders, no separators other than "/", which
     * is what makes the path safe to join onto the workflows directory.
     */
    public static function normalizeFolder(string $path): string
    {
        $path = trim(str_replace('\\', '/', $path), '/ ');
        if ($path === '') {
            return '';
        }
        $segments = explode('/', $path);
        if (count($segments) > self::MAX_DEPTH) {
            throw new \InvalidArgumentException('Ordner sind höchstens ' . self::MAX_DEPTH . ' Ebenen tief.');
        }
        foreach ($segments as $segment) {
            self::assertFolderName($segment);
        }
        return implode('/', $segments);
    }

    public static function assertFolderName(string $name): void
    {
        if (!preg_match('/^[\p{L}\p{N}][\p{L}\p{N} _\-]{0,59}$/u', $name) || $name !== trim($name)) {
            throw new \InvalidArgumentException(
                "Ungültiger Ordnername '$name' - erlaubt sind Buchstaben, Ziffern, Leerzeichen, - und _ (höchstens 60 Zeichen, "
                . 'nicht mit Leerzeichen, - oder _ beginnend).'
            );
        }
    }

    public function folderExists(string $folder): bool
    {
        $folder = self::normalizeFolder($folder);
        $dir = $this->dirFor($folder);
        return is_dir($dir) && !is_link($dir);
    }

    /** @return array<int, string> every folder path in the tree, sorted ("a", "a/b", "c") */
    public function listFolders(): array
    {
        $folders = [];
        $walk = function (string $folder) use (&$walk, &$folders): void {
            foreach ($this->childFolders($folder) as $name) {
                $path = $folder === '' ? $name : $folder . '/' . $name;
                $folders[] = $path;
                $walk($path);
            }
        };
        $walk('');
        return $folders;
    }

    /**
     * One level of the tree: its subfolders (with how many folders/workflows
     * are inside, recursively) and the workflows directly in it.
     *
     * @return array{folders: array<int, array{name: string, path: string, workflows: int, folders: int}>, workflows: array<int, array<string, mixed>>}
     */
    public function listFolder(string $folder): array
    {
        $folder = self::normalizeFolder($folder);
        $this->requireFolder($folder);

        $folders = [];
        foreach ($this->childFolders($folder) as $name) {
            $path = $folder === '' ? $name : $folder . '/' . $name;
            $folders[] = [
                'name' => $name,
                'path' => $path,
                'workflows' => $this->countWorkflows($path),
                'folders' => count($this->descendantFolders($path)),
            ];
        }

        $workflows = [];
        foreach (glob($this->dirFor($folder) . '/*.yaml') ?: [] as $file) {
            $data = $this->read($file);
            if ($data !== null) {
                $workflows[] = $data;
            }
        }
        usort($workflows, static fn ($a, $b) => strcasecmp((string) ($a['name'] ?? $a['id']), (string) ($b['name'] ?? $b['id'])));
        return ['folders' => $folders, 'workflows' => $workflows];
    }

    /** @return string the new folder's path */
    public function createFolder(string $parent, string $name): string
    {
        $parent = self::normalizeFolder($parent);
        $name = trim($name);
        self::assertFolderName($name);
        $this->requireFolder($parent);
        $path = $parent === '' ? $name : $parent . '/' . $name;
        self::normalizeFolder($path); // depth limit
        if (file_exists($this->dirFor($path))) {
            throw new \RuntimeException("Den Ordner '$name' gibt es hier schon.");
        }
        mkdir($this->dirFor($path), 0775);
        $this->index = null;
        return $path;
    }

    /** @return string the folder's new path */
    public function renameFolder(string $path, string $newName): string
    {
        $path = self::normalizeFolder($path);
        if ($path === '') {
            throw new \InvalidArgumentException('Der oberste Ordner lässt sich nicht umbenennen.');
        }
        $newName = trim($newName);
        self::assertFolderName($newName);
        $parent = str_contains($path, '/') ? dirname($path) : '';
        return $this->relocate($path, $parent, $newName);
    }

    /** @return string the folder's new path */
    public function moveFolder(string $path, string $newParent): string
    {
        $path = self::normalizeFolder($path);
        $newParent = self::normalizeFolder($newParent);
        if ($path === '') {
            throw new \InvalidArgumentException('Der oberste Ordner lässt sich nicht verschieben.');
        }
        if ($newParent === $path || str_starts_with($newParent, $path . '/')) {
            throw new \RuntimeException('Ein Ordner lässt sich nicht in sich selbst verschieben.');
        }
        return $this->relocate($path, $newParent, basename($path));
    }

    /** Only an empty folder can be deleted - nothing is ever removed with it. */
    public function deleteFolder(string $path): void
    {
        $path = self::normalizeFolder($path);
        if ($path === '') {
            throw new \InvalidArgumentException('Der oberste Ordner lässt sich nicht löschen.');
        }
        $this->requireFolder($path);
        $entries = array_diff(scandir($this->dirFor($path)) ?: [], ['.', '..']);
        if ($entries !== []) {
            throw new \RuntimeException(
                "Der Ordner '" . basename($path) . "' ist nicht leer - verschiebe oder lösche zuerst die Workflows und Unterordner darin."
            );
        }
        rmdir($this->dirFor($path));
        $this->index = null;
    }

    // -- internals ---------------------------------------------------------

    private function relocate(string $path, string $newParent, string $newName): string
    {
        $this->requireFolder($path);
        $this->requireFolder($newParent);
        $newPath = $newParent === '' ? $newName : $newParent . '/' . $newName;
        // Moving a subtree down can exceed the depth limit: check the deepest descendant.
        $deepest = $newPath;
        foreach ($this->descendantFolders($path) as $descendant) {
            $candidate = $newPath . substr($descendant, strlen($path));
            if (substr_count($candidate, '/') > substr_count($deepest, '/')) {
                $deepest = $candidate;
            }
        }
        self::normalizeFolder($deepest);
        if ($newPath === $path) {
            return $path;
        }
        if (file_exists($this->dirFor($newPath))) {
            throw new \RuntimeException("Im Zielordner gibt es schon einen Ordner '$newName'.");
        }
        rename($this->dirFor($path), $this->dirFor($newPath));
        $this->index = null;
        return $newPath;
    }

    private function requireFolder(string $folder): void
    {
        if (!$this->folderExists($folder)) {
            throw new \RuntimeException("Der Ordner '$folder' existiert nicht.");
        }
    }

    /** Absolute path of an already normalized folder path. */
    private function dirFor(string $folder): string
    {
        return $folder === '' ? $this->directory : $this->directory . '/' . $folder;
    }

    private function relativeFolder(string $absoluteDir): string
    {
        $relative = substr($absoluteDir, strlen($this->directory));
        return trim($relative, '/');
    }

    /** @return array<int, string> names of the real, non-hidden subfolders of a folder */
    private function childFolders(string $folder): array
    {
        $names = [];
        foreach (scandir($this->dirFor($folder)) ?: [] as $entry) {
            if ($entry === '.' || $entry === '..' || $entry[0] === '.') {
                continue;
            }
            $full = $this->dirFor($folder) . '/' . $entry;
            if (is_dir($full) && !is_link($full) && preg_match('/^[\p{L}\p{N}][\p{L}\p{N} _\-]{0,59}$/u', $entry)) {
                $names[] = $entry;
            }
        }
        natcasesort($names);
        return array_values($names);
    }

    /** @return array<int, string> */
    private function descendantFolders(string $folder): array
    {
        $result = [];
        foreach ($this->childFolders($folder) as $name) {
            $path = $folder === '' ? $name : $folder . '/' . $name;
            $result[] = $path;
            array_push($result, ...$this->descendantFolders($path));
        }
        return $result;
    }

    private function countWorkflows(string $folder): int
    {
        $count = count(glob($this->dirFor($folder) . '/*.yaml') ?: []);
        foreach ($this->childFolders($folder) as $name) {
            $count += $this->countWorkflows($folder === '' ? $name : $folder . '/' . $name);
        }
        return $count;
    }

    /** @return array<string, string> id => absolute file path (first one wins on a duplicate id) */
    private function locations(): array
    {
        if ($this->index === null) {
            $this->index = [];
            foreach (array_merge([''], $this->listFolders()) as $folder) {
                foreach (glob($this->dirFor($folder) . '/*.yaml') ?: [] as $file) {
                    $id = basename($file, '.yaml');
                    if (preg_match('/^[a-z0-9\-]+$/', $id) && !isset($this->index[$id])) {
                        $this->index[$id] = $file;
                    }
                }
            }
        }
        return $this->index;
    }

    private function locate(string $id): ?string
    {
        // Every caller (save.php, delete.php, toggle.php, duplicate.php,
        // new.php, test_run.php, start_test_run.php, the folder pages)
        // reaches a filesystem path through here or normalizeFolder() -
        // validating once, centrally, means a future entry point can't forget
        // the sanitization and closes off path traversal (e.g.
        // id=../../config/nextcloud) that would otherwise let a POST
        // delete/overwrite/read an arbitrary .yaml file.
        if (!preg_match('/^[a-z0-9\-]+$/', $id)) {
            throw new \InvalidArgumentException("Invalid workflow id '$id'");
        }
        return $this->locations()[$id] ?? null;
    }

    /** @return array<string, mixed>|null */
    private function read(string $path): ?array
    {
        try {
            $data = Yaml::parseFile($path);
        } catch (\Throwable $e) {
            // A malformed file must not break a listing or page - same
            // resilience as the Python side's YamlWorkflowRepository.
            return null;
        }
        // Without a valid id the overview can't link to it (and every page
        // would emit "undefined array key" notices) - skip it like a
        // malformed file, same as the Python side does.
        if (!is_array($data) || !is_string($data['id'] ?? null) || !preg_match('/^[a-z0-9\-]+$/', $data['id'])) {
            return null;
        }
        return $data;
    }
}
