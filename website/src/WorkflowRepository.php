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
 * Workflows are plain associative arrays here, not objects - the website only
 * lists/creates/toggles/deletes them; the actual domain logic (matching
 * events, running action chains) lives entirely in Python.
 */
class WorkflowRepository
{
    public function __construct(private readonly string $directory)
    {
        if (!is_dir($this->directory)) {
            mkdir($this->directory, 0775, true);
        }
    }

    /** @return array<int, array<string, mixed>> */
    public function listAll(): array
    {
        $workflows = [];
        foreach (glob($this->directory . '/*.yaml') ?: [] as $path) {
            try {
                $data = Yaml::parseFile($path);
            } catch (\Throwable $e) {
                // A malformed file must not break the whole listing - same
                // resilience as the Python side's YamlWorkflowRepository.
                continue;
            }
            // Without a valid id the overview can't link to it (and every
            // page would emit "undefined array key" notices) - skip it like a
            // malformed file, same as the Python side does.
            if (is_array($data) && is_string($data['id'] ?? null) && preg_match('/^[a-z0-9\-]+$/', $data['id'])) {
                $workflows[] = $data;
            }
        }
        usort($workflows, static fn ($a, $b) => strcmp($a['id'] ?? '', $b['id'] ?? ''));
        return $workflows;
    }

    public function exists(string $id): bool
    {
        return is_file($this->pathFor($id));
    }

    public function get(string $id): ?array
    {
        $path = $this->pathFor($id);
        if (!is_file($path)) {
            return null;
        }
        try {
            $data = Yaml::parseFile($path);
        } catch (\Throwable $e) {
            return null; // malformed file: treat as "not found" instead of a 500 page
        }
        return is_array($data) ? $data : null;
    }

    /** @param array<string, mixed> $workflow */
    public function save(array $workflow): void
    {
        file_put_contents($this->pathFor($workflow['id']), Yaml::dump($workflow, 10, 2));
    }

    public function delete(string $id): void
    {
        $path = $this->pathFor($id);
        if (is_file($path)) {
            unlink($path);
        }
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

    private function pathFor(string $id): string
    {
        // Every caller (save.php, delete.php, toggle.php, duplicate.php,
        // new.php, test_run.php, start_test_run.php) ultimately reaches a
        // filesystem path through here - validating once, centrally, means
        // a future entry point can't forget the id-sanitization check
        // save.php otherwise did on its own (and delete/toggle/duplicate did
        // not), and closes off path traversal (e.g. id=../../config/nextcloud)
        // that would otherwise let a POST delete/overwrite/read an arbitrary
        // .yaml file outside the workflows directory.
        if (!preg_match('/^[a-z0-9\-]+$/', $id)) {
            throw new \InvalidArgumentException("Invalid workflow id '$id'");
        }
        return $this->directory . '/' . $id . '.yaml';
    }
}
