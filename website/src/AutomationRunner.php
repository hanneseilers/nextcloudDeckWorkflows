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
        try {
            if (!function_exists('proc_open')) {
                return;
            }
            $repoRoot = dirname(__DIR__, 2);
            $python = is_file("$repoRoot/.venv/bin/python") ? "$repoRoot/.venv/bin/python" : 'python3';
            // The trailing `&` backgrounds the real work at the shell level,
            // detached from this PHP process, so `sh -c` itself returns
            // almost immediately regardless of how long the automation run
            // takes - this call must not make the caller's response slow.
            $shellCommand = 'cd ' . escapeshellarg($repoRoot) . ' && '
                . escapeshellarg($python) . ' -m automation.main > /dev/null 2>&1 &';
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
