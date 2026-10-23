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
    ];

    /** @param string $active one of the NAV keys ('' = none highlighted) */
    public static function start(string $title, string $heading, string $active = ''): void
    {
        // Pages print CSRF fields further down; the session (cookie header)
        // has to be started before the first byte of output.
        Csrf::token();
        echo '<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8">'
            . '<meta name="viewport" content="width=device-width, initial-scale=1">'
            . '<title>' . h($title) . ' — Nextcloud Deck Workflows</title>'
            . '<link rel="stylesheet" href="assets/style.css"></head><body>'
            . '<nav class="topnav"><a class="brand" href="index.php">Deck Workflows</a><span class="nav-links">';
        foreach (self::NAV as $key => [$href, $label, $icon]) {
            echo '<a href="' . $href . '"' . ($key === $active ? ' class="active" aria-current="page"' : '') . '>'
                . self::icon($icon) . ' ' . h($label) . '</a>';
        }
        echo '</span><a class="button with-icon" href="new.php">' . self::icon('plus') . ' Neuer Workflow</a></nav>'
            . '<header><h1>' . h($heading) . '</h1></header>';
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
            'list' => '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
            'trash' => '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
        ];
        return '<svg class="icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
            . 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' . $paths[$name] . '</svg>';
    }
}
