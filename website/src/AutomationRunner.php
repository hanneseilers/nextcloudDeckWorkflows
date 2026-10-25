<?php

namespace NextcloudDeckWorkflows;

/**
 * Best-effort "run `python -m automation.main` now" for the pages that want
 * a result sooner than the next cron tick (webhook.php, link.php). The
 * website never waits for or depends on it: proc_open/exec are commonly
 * disabled on shared hosting, and if this silently does nothing the work it
 * was meant to speed up is still picked up by the next regular cron run.
 */
class AutomationRunner
{
    public static function triggerNow(): void
    {
        self::start('--wait-lock 120 --triggered');
    }

    /**
     * Has the automation write a new module list (`--list-modules`) - after an
     * update, so the editor shows the new fields without waiting for the next cron
     * run. Takes about a second and needs no Nextcloud, config or lock.
     */
    public static function refreshModules(): void
    {
        self::start('--list-modules');
    }

    /**
     * Starts just this one queued test run (`--test-run <id>`): no board
     * polling, so the answer is there in seconds. The id comes from
     * TestRunStore (hex only) and is validated again before it reaches a shell.
     */
    public static function triggerTestRun(string $testRunId): void
    {
        if (preg_match('/^[0-9a-f]{32}$/', $testRunId) === 1) {
            self::start('--test-run ' . $testRunId);
        }
    }

    /** @param string $arguments fixed, validated arguments for `python -m automation.main` */
    private static function start(string $arguments): void
    {
        try {
            if (!function_exists('proc_open')) {
                return;
            }
            $repoRoot = dirname(__DIR__, 2);
            // The same interpreter the cron job uses: install.sh creates
            // automation/.venv; a development checkout has .venv in the root.
            $python = 'python3';
            foreach (["$repoRoot/automation/.venv/bin/python", "$repoRoot/.venv/bin/python"] as $candidate) {
                if (is_file($candidate)) {
                    $python = $candidate;
                    break;
                }
            }
            // The trailing `&` backgrounds the real work at the shell level,
            // detached from this PHP process, so `sh -c` itself returns
            // almost immediately regardless of how long the automation run
            // takes - this call must not make the caller's response slow.
            // --wait-lock: if a run (e.g. cron) is already in progress, wait
            // up to 120 s for it to finish instead of giving up (only one
            // such waiter is kept - see automation/main.py). A longer run
            // picks up claimed links itself between its polling passes.
            $shellCommand = 'cd ' . escapeshellarg($repoRoot) . ' && '
                . escapeshellarg($python) . ' -m automation.main ' . $arguments . ' > /dev/null 2>&1 &';
            $process = @proc_open(
                ['/bin/sh', '-c', $shellCommand],
                [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']],
                $pipes
            );
            if (is_resource($process)) {
                foreach ($pipes as $pipe) {
                    fclose($pipe);
                }
                proc_close($process);
            }
        } catch (\Throwable $e) {
            // Never let this optional accelerator affect the response.
        }
    }
}
