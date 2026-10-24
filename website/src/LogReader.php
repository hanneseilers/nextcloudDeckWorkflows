<?php

namespace NextcloudDeckWorkflows;

/**
 * Reads the automation's log files for the website's log page: automation.log
 * (written by main.py itself, rotating) and cron.log (whatever the cron job's
 * redirect collected - including errors that happen before logging starts,
 * e.g. a missing Python package). Only the end of a file is read, so a large
 * file costs the same as a small one.
 */
class LogReader
{
    public const FILES = [
        'automation' => ['automation.log', 'Automation-Log'],
        'cron' => ['cron.log', 'Cron-Ausgabe (Konsole)'],
    ];

    /** Level => rank, for "this level and above". */
    public const LEVELS = ['DEBUG' => 0, 'INFO' => 1, 'WARNING' => 2, 'ERROR' => 3, 'CRITICAL' => 4];

    private const MAX_READ_BYTES = 2_000_000;
    private const ENTRY_START = '/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,.]\d+ (DEBUG|INFO|WARNING|ERROR|CRITICAL) (.*)$/';

    public function __construct(private readonly string $directory)
    {
    }

    /** @return array<string, array{label: string, size: int, modified: int}> the log files that exist */
    public function available(): array
    {
        $result = [];
        foreach (self::FILES as $key => [$name, $label]) {
            $path = $this->directory . '/' . $name;
            if (is_file($path)) {
                $result[$key] = ['label' => $label, 'size' => (int) filesize($path), 'modified' => (int) filemtime($path)];
            }
        }
        return $result;
    }

    /**
     * The newest entries, newest first. An entry is one log record with its
     * continuation lines (a traceback belongs to the ERROR line above it).
     *
     * @param string|null $minLevel show this level and above (null = all)
     * @param string $query case-insensitive text the entry must contain ('' = any)
     * @return array{entries: array<int, array{time: string, level: string, text: string}>, truncated: bool, total: int}
     */
    public function read(string $key, int $maxEntries = 300, ?string $minLevel = null, string $query = ''): array
    {
        $empty = ['entries' => [], 'truncated' => false, 'total' => 0];
        if (!isset(self::FILES[$key])) {
            return $empty;
        }
        $path = $this->directory . '/' . self::FILES[$key][0];
        if (!is_file($path) || ($handle = @fopen($path, 'rb')) === false) {
            return $empty;
        }

        $size = (int) filesize($path);
        $cut = $size > self::MAX_READ_BYTES;
        if ($cut) {
            fseek($handle, $size - self::MAX_READ_BYTES);
        }
        $text = (string) stream_get_contents($handle);
        fclose($handle);
        if ($cut) {
            // We started somewhere inside a line - drop that partial first line.
            $newline = strpos($text, "\n");
            $text = $newline === false ? '' : substr($text, $newline + 1);
        }
        $text = mb_convert_encoding($text, 'UTF-8', 'UTF-8'); // never emit invalid UTF-8

        $minRank = $minLevel !== null && isset(self::LEVELS[$minLevel]) ? self::LEVELS[$minLevel] : null;
        $needle = mb_strtolower($query);
        $entries = [];
        $current = null;
        $accept = function (array $entry) use ($minRank, $needle): bool {
            return ($minRank === null || self::LEVELS[$entry['level']] >= $minRank)
                && ($needle === '' || str_contains(mb_strtolower($entry['time'] . ' ' . $entry['text']), $needle));
        };
        $flush = function () use (&$current, &$entries, $accept): void {
            if ($current !== null) {
                $current['text'] = rtrim($current['text']);
                if ($accept($current)) {
                    $entries[] = $current;
                }
                $current = null;
            }
        };

        foreach (preg_split('/\r?\n/', $text) ?: [] as $line) {
            if (preg_match(self::ENTRY_START, $line, $m) === 1) {
                $flush();
                $current = ['time' => $m[1], 'level' => $m[2], 'text' => $m[3]];
            } elseif ($current !== null) {
                $current['text'] .= "\n" . $line;
            } elseif (trim($line) !== '') {
                // Plain console output (cron.log can hold lines without the log
                // format, e.g. a crash before logging started): one entry per line.
                $plain = [
                    'time' => '',
                    'level' => preg_match('/Traceback|Error|Exception|^\s+File "/', $line) === 1 ? 'ERROR' : 'INFO',
                    'text' => $line,
                ];
                if ($accept($plain)) {
                    $entries[] = $plain;
                }
            }
        }
        $flush();

        $entries = array_reverse($entries);
        $total = count($entries);
        return ['entries' => array_slice($entries, 0, $maxEntries), 'truncated' => $total > $maxEntries || $cut, 'total' => $total];
    }
}
