<?php

namespace NextcloudDeckWorkflows;

/**
 * The frame every page of the management UI shares: <head>, the navigation
 * bar and the page heading - one place instead of a copy per page.
 */
final class Layout
{
    private const NAV = [
        'index' => ['index.php', 'Übersicht', 'list'],
        'history' => ['history.php', 'Historie', 'clock'],
        'health' => ['health.php', 'Status', 'activity'],
        'log' => ['log.php', 'Log', 'file-text'],
        'boards' => ['boards.php', 'Boards', 'grid'],
        'docs' => ['docs.php', 'Doku', 'book'],
    ];

    /** Reference pages - opened in a new tab, so the editor stays open. */
    private const NEW_TAB = ['boards', 'docs'];

    /** @param string $active one of the NAV keys ('' = none highlighted) */
    public static function start(string $title, string $heading, string $active = ''): void
    {
        // Pages print CSRF fields further down; the session (cookie header)
        // has to be started before the first byte of output.
        Csrf::token();
        $flash = $_SESSION['flash'] ?? null;
        unset($_SESSION['flash']);
        echo '<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">'
            . '<meta name="viewport" content="width=device-width, initial-scale=1">'
            . '<title>' . h($title) . ' — Nextcloud Deck Workflows</title>'
            . '<link rel="stylesheet" href="assets/style.css"></head><body>'
            . '<nav class="topnav"><a class="brand" href="index.php">Deck Workflows</a><span class="nav-links">';
        foreach (self::NAV as $key => [$href, $label, $icon]) {
            $newTab = in_array($key, self::NEW_TAB, true);
            echo '<a href="' . $href . '"' . ($key === $active ? ' class="active" aria-current="page"' : '')
                . ($newTab ? ' target="_blank" rel="noopener" title="Öffnet in einem neuen Tab"' : '') . '>'
                . self::icon($icon) . ' ' . h($label) . '</a>';
        }
        $version = self::version();
        echo '</span><a class="button with-icon" href="new.php">' . self::icon('plus') . ' Neuer Workflow</a>'
            . ($version !== '' ? '<span class="app-version" title="Version von Nextcloud Deck Workflows">v' . h($version) . '</span>' : '')
            . '</nav>'
            . '<header><h1>' . h($heading) . '</h1></header>';
        if (is_array($flash)) {
            echo '<p class="notice' . ($flash['kind'] === 'error' ? ' error' : '') . '" role="status">' . h((string) $flash['message']) . '</p>';
        }
    }

    /** A one-time message shown at the top of the next page ($kind: 'ok' or 'error'). */
    public static function flash(string $kind, string $message): void
    {
        Csrf::token(); // makes sure the session is started
        $_SESSION['flash'] = ['kind' => $kind, 'message' => $message];
    }

    /** Overview URL for a folder path ("" = top level). */
    public static function folderUrl(string $folder = ''): string
    {
        return 'index.php' . ($folder === '' ? '' : '?folder=' . rawurlencode($folder));
    }

    /**
     * <option>s for a folder dropdown: the top level plus every folder,
     * indented by depth.
     *
     * @param array<int, string> $folders all folder paths (WorkflowRepository::listFolders)
     * @param array<int, string> $exclude folders (with everything below) to leave out
     */
    public static function folderOptions(array $folders, string $selected = '', array $exclude = []): string
    {
        $html = '<option value=""' . ($selected === '' ? ' selected' : '') . '>Hauptordner</option>';
        foreach ($folders as $path) {
            foreach ($exclude as $skip) {
                if ($path === $skip || str_starts_with($path, $skip . '/')) {
                    continue 2;
                }
            }
            $depth = substr_count($path, '/');
            $html .= '<option value="' . h($path) . '"' . ($path === $selected ? ' selected' : '') . '>'
                . str_repeat('— ', $depth) . h(basename($path)) . '</option>';
        }
        return $html;
    }

    /** The tool's version from the VERSION file in the project root ('' if missing). */
    public static function version(): string
    {
        $file = dirname(__DIR__, 2) . '/VERSION';
        return is_file($file) ? trim((string) file_get_contents($file)) : '';
    }

    public static function end(): void
    {
        echo '</body></html>';
    }

    /**
     * A stored UTC ISO timestamp as "24.10.2026 14:05" in the server's
     * timezone (PHP's date.timezone), wrapped in <time> with the exact value
     * as tooltip. Anything unparsable is shown as it is.
     */
    public static function dateTime(?string $iso): string
    {
        if ($iso === null || $iso === '') {
            return '–';
        }
        try {
            $moment = new \DateTimeImmutable($iso);
        } catch (\Exception $e) {
            return h($iso);
        }
        $local = $moment->setTimezone(new \DateTimeZone(date_default_timezone_get()));
        return '<time datetime="' . h($iso) . '" title="' . h($iso) . '">' . h($local->format('d.m.Y H:i')) . '</time>';
    }

    /** Feather-style line icon; any text belongs in the element's title/aria-label. */
    public static function icon(string $name): string
    {
        $paths = [
            'edit' => '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
            'play' => '<polygon points="5 3 19 12 5 21 5 3"/>',
            'copy' => '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
            'power' => '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>',
            'activity' => '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
            'clock' => '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
            'plus' => '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
            'folder' => '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
            'folder-plus' => '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/>',
            'move' => '<polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/>',
            'file-text' => '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
            'list' => '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
            'grid' => '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
            'book' => '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
            'trash' => '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
        ];
        return '<svg class="icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
            . 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' . $paths[$name] . '</svg>';
    }
}
