<?php

namespace NextcloudDeckWorkflows;

/**
 * The text templates the "Vorlagen" page edits: config/text_templates/<name>.txt.
 * One kind of template for everything - send_email (`template`), format_text
 * and add_comment (`text_template`) pick from the same list; an optional first
 * paragraph `Subject: ...` is the subject when the template is sent as an
 * e-mail. The automation reads the same files - see
 * automation/adapters/text_templates.py. Templates from before this folder
 * existed (config/email_templates/) are moved over by migrateLegacy() and are
 * found there until then.
 *
 * A name never becomes a path unless it matches NAME_PATTERN (no slash, no dot),
 * writes are atomic (temp file + rename), and content is stored with "\n" line
 * endings and as valid UTF-8.
 */
class TemplateStore
{
    /** Same rule as NAME_PATTERN in automation/adapters/text_templates.py. */
    public const NAME_PATTERN = '/^[\p{L}\p{N}_][\p{L}\p{N}_\- ]{0,59}$/u';

    public const MAX_BYTES = 102400;

    private const DIR = 'text_templates';
    private const LEGACY_DIR = 'email_templates';

    /** Which workflow step parameters name a template: [module, parameter]. */
    public const USED_BY = [['send_email', 'template'], ['format_text', 'text_template'], ['add_comment', 'text_template']];

    public function __construct(private readonly string $configDir)
    {
    }

    public static function fromRepoRoot(): self
    {
        return new self(dirname(__DIR__, 2) . '/config');
    }

    public static function validName(string $name): bool
    {
        return $name === trim($name) && preg_match(self::NAME_PATTERN, $name) === 1;
    }

    /**
     * Moves the templates of the old config/email_templates/ folder over to
     * config/text_templates/ (a name that exists in both is left where it is -
     * the new one wins). Cheap, so every page that lists templates calls it.
     * Returns how many were moved; failing to (no write permission) is not an
     * error: the old files are still found where they are.
     */
    public function migrateLegacy(): int
    {
        $legacy = $this->configDir . '/' . self::LEGACY_DIR;
        if (!is_dir($legacy)) {
            return 0;
        }
        $moved = 0;
        foreach ($this->listFiles($legacy) as $name) {
            $target = $this->dir() . '/' . $name . '.txt';
            if (is_file($target)) {
                continue;
            }
            if (!is_dir($this->dir()) && !@mkdir($this->dir(), 0775, true) && !is_dir($this->dir())) {
                return $moved;
            }
            if (@rename($legacy . '/' . $name . '.txt', $target)) {
                $moved++;
            }
        }
        @rmdir($legacy); // only succeeds when empty
        return $moved;
    }

    /** @return array<int, string> the names of the usable templates, sorted */
    public function names(): array
    {
        $names = array_unique(array_merge(
            $this->listFiles($this->dir()),
            $this->listFiles($this->configDir . '/' . self::LEGACY_DIR)
        ));
        sort($names, SORT_NATURAL | SORT_FLAG_CASE);
        return array_values($names);
    }

    public function exists(string $name): bool
    {
        return $this->locate($name) !== null;
    }

    /** @return array{name: string, content: string, modified: int, size: int, version: string}|null */
    public function read(string $name): ?array
    {
        $path = self::validName($name) ? $this->locate($name) : null;
        if ($path === null) {
            return null;
        }
        $content = file_get_contents($path);
        if ($content === false) {
            return null;
        }
        return [
            'name' => $name,
            'content' => str_replace(["\r\n", "\r"], "\n", $content),
            'modified' => (int) filemtime($path),
            'size' => strlen($content),
            // Identifies this exact text: a form that was loaded earlier can tell it is outdated
            // (a time stamp can't - two saves within a second look the same).
            'version' => sha1($content),
        ];
    }

    /** Creates a new template; fails if the name is taken. */
    public function create(string $name, string $content): void
    {
        $this->assertName($name);
        if ($this->exists($name)) {
            throw new \RuntimeException("Es gibt schon eine Vorlage '$name'.");
        }
        $this->write($name, $content);
    }

    /** Overwrites an existing template. */
    public function save(string $name, string $content): void
    {
        $this->assertName($name);
        if (!$this->exists($name)) {
            throw new \RuntimeException("Die Vorlage '$name' gibt es nicht (mehr).");
        }
        $this->write($name, $content);
    }

    public function rename(string $old, string $new): void
    {
        $this->assertName($new);
        if (!$this->exists($old)) {
            throw new \RuntimeException("Die Vorlage '$old' gibt es nicht (mehr).");
        }
        if ($old === $new) {
            return;
        }
        // A different spelling of the same file (case-insensitive file systems) is allowed.
        if ($this->exists($new) && strcasecmp($old, $new) !== 0) {
            throw new \RuntimeException("Es gibt schon eine Vorlage '$new'.");
        }
        $this->migrateLegacy();
        $from = $this->locate($old);
        if ($from === null || !@rename($from, $this->path($new))) {
            throw new \RuntimeException("Die Vorlage konnte nicht umbenannt werden (Schreibrechte für config/?).");
        }
    }

    public function delete(string $name): void
    {
        if (!$this->exists($name)) {
            throw new \RuntimeException("Die Vorlage '$name' gibt es nicht (mehr).");
        }
        // Both folders: an old copy of the same name must not "come back" after the delete.
        foreach ([$this->path($name), $this->configDir . '/' . self::LEGACY_DIR . '/' . $name . '.txt'] as $file) {
            if (is_file($file) && !@unlink($file)) {
                throw new \RuntimeException("Die Vorlage konnte nicht gelöscht werden (Schreibrechte für config/?).");
            }
        }
    }

    // -- e-mail templates: optional "Subject:" line ---------------------------------

    /**
     * The first line `Subject: ...` followed by a blank line is the subject,
     * everything after it the body (same rule as the automation's).
     *
     * @return array{subject: string, body: string}
     */
    public static function splitEmail(string $content): array
    {
        $parts = explode("\n\n", $content, 2);
        if (count($parts) === 2 && str_starts_with($parts[0], 'Subject:')) {
            return ['subject' => trim(substr($parts[0], strlen('Subject:'))), 'body' => $parts[1]];
        }
        return ['subject' => '', 'body' => $content];
    }

    public static function joinEmail(string $subject, string $body): string
    {
        $subject = trim(preg_replace('/\s+/', ' ', $subject) ?? '');
        if ($subject !== '') {
            return 'Subject: ' . $subject . "\n\n" . $body;
        }
        // No subject, but a body that starts like a subject line: a leading blank
        // line keeps it from being read as one.
        return str_starts_with($body, 'Subject:') ? "\n" . $body : $body;
    }

    // -- placeholders ------------------------------------------------------------------

    /**
     * The $name / ${name} placeholders of a text, in order of appearance ($$ is a
     * literal dollar sign and no placeholder) - what string.Template substitutes.
     *
     * @return array<int, string>
     */
    public static function placeholders(string $text): array
    {
        preg_match_all('/\$(?:\$|([_a-zA-Z][_a-zA-Z0-9]*)|\{([_a-zA-Z][_a-zA-Z0-9]*)\})/', $text, $matches, PREG_SET_ORDER);
        $names = [];
        foreach ($matches as $match) {
            $name = ($match[2] ?? '') !== '' ? $match[2] : ($match[1] ?? '');
            if ($name !== '' && !in_array($name, $names, true)) {
                $names[] = $name;
            }
        }
        return $names;
    }

    // -- where templates are used -------------------------------------------------------

    /**
     * The workflows whose steps name this template.
     *
     * @return array<int, array{id: string, name: string}>
     */
    public function usages(WorkflowRepository $workflows, string $name): array
    {
        $found = [];
        foreach ($workflows->listAll() as $workflow) {
            $count = 0;
            $actions = $workflow['actions'] ?? [];
            self::walkSteps($actions, $name, null, $count);
            if ($count > 0) {
                $found[] = ['id' => (string) $workflow['id'], 'name' => (string) ($workflow['name'] ?? $workflow['id'])];
            }
        }
        return $found;
    }

    /**
     * Points every step that names `$old` at `$new` - after a rename, so no
     * workflow is left with a template that doesn't exist. Returns the number
     * of workflows changed.
     */
    public function renameReferences(WorkflowRepository $workflows, string $old, string $new): int
    {
        $changed = 0;
        foreach ($workflows->listAll() as $workflow) {
            $count = 0;
            $actions = $workflow['actions'] ?? [];
            self::walkSteps($actions, $old, $new, $count);
            if ($count > 0) {
                $workflow['actions'] = $actions;
                $workflows->save($workflow);
                $changed++;
            }
        }
        return $changed;
    }

    /**
     * Counts the steps naming `$name` (literal string values only - a reference
     * to another step's output can't be followed) and, with `$replacement`,
     * rewrites them.
     *
     * @param array<int, mixed> $steps
     */
    private static function walkSteps(array &$steps, string $name, ?string $replacement, int &$count): void
    {
        foreach ($steps as &$step) {
            if (!is_array($step)) {
                continue;
            }
            if (($step['type'] ?? null) === 'if') {
                foreach (['then', 'else'] as $branch) {
                    if (isset($step[$branch]) && is_array($step[$branch])) {
                        self::walkSteps($step[$branch], $name, $replacement, $count);
                    }
                }
                continue;
            }
            foreach (self::USED_BY as [$module, $param]) {
                if (($step['module'] ?? null) === $module && ($step['params'][$param] ?? null) === $name) {
                    $count++;
                    if ($replacement !== null) {
                        $step['params'][$param] = $replacement;
                    }
                }
            }
        }
        unset($step);
    }

    // -- internals -----------------------------------------------------------------------

    private function dir(): string
    {
        return $this->configDir . '/' . self::DIR;
    }

    private function path(string $name): string
    {
        $this->assertName($name);
        return $this->dir() . '/' . $name . '.txt';
    }

    /** The file of a template: the new folder first, then the old one. */
    private function locate(string $name): ?string
    {
        if (!self::validName($name)) {
            return null;
        }
        foreach ([$this->dir(), $this->configDir . '/' . self::LEGACY_DIR] as $dir) {
            $file = $dir . '/' . $name . '.txt';
            if (is_file($file) && !is_link($file)) {
                return $file;
            }
        }
        return null;
    }

    /** @return array<int, string> the names of the usable .txt files of a folder */
    private function listFiles(string $dir): array
    {
        $names = [];
        foreach (is_dir($dir) ? (scandir($dir) ?: []) : [] as $file) {
            if (!str_ends_with($file, '.txt')) {
                continue;
            }
            $name = substr($file, 0, -4);
            if (self::validName($name) && is_file($dir . '/' . $file) && !is_link($dir . '/' . $file)) {
                $names[] = $name;
            }
        }
        return $names;
    }

    private function assertName(string $name): void
    {
        if (!self::validName($name)) {
            throw new \InvalidArgumentException(
                "Ungültiger Name '$name': erlaubt sind Buchstaben, Ziffern, Leerzeichen, _ und - (höchstens 60 Zeichen, nicht mit Leerzeichen oder - beginnend)."
            );
        }
    }

    private function write(string $name, string $content): void
    {
        $content = str_replace(["\r\n", "\r"], "\n", $content);
        if (!mb_check_encoding($content, 'UTF-8')) {
            throw new \InvalidArgumentException('Der Text ist nicht gültiges UTF-8.');
        }
        if (strlen($content) > self::MAX_BYTES) {
            throw new \InvalidArgumentException('Die Vorlage ist zu groß (höchstens ' . (self::MAX_BYTES / 1024) . ' KB).');
        }
        if (str_contains($content, "\0")) {
            throw new \InvalidArgumentException('Der Text enthält ein ungültiges Zeichen.');
        }
        $this->migrateLegacy();
        $dir = $this->dir();
        if (!is_dir($dir) && !@mkdir($dir, 0775, true) && !is_dir($dir)) {
            throw new \RuntimeException('Der Ordner config/' . self::DIR . '/ konnte nicht angelegt werden (Schreibrechte?).');
        }
        $target = $this->path($name);
        $temp = $dir . '/.' . bin2hex(random_bytes(6)) . '.tmp';
        if (@file_put_contents($temp, $content) === false) {
            throw new \RuntimeException('Die Vorlage konnte nicht gespeichert werden (Schreibrechte für config/' . self::DIR . '/?).');
        }
        if (is_file($target)) {
            @chmod($temp, fileperms($target) & 0777);
        }
        if (!@rename($temp, $target)) {
            @unlink($temp);
            throw new \RuntimeException('Die Vorlage konnte nicht gespeichert werden.');
        }
    }
}
