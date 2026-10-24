<?php

/** HTML-escapes a value for output in a page. */
function h(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}

// Loaded automatically with vendor/autoload.php (composer.json "files"), so
// every page gets these before any output.

if (PHP_SAPI !== 'cli') {
    if (!headers_sent()) {
        // The pages carry delete/disable buttons - never render them inside
        // a foreign frame (clickjacking).
        header('X-Frame-Options: DENY');
        header("Content-Security-Policy: frame-ancestors 'none'");
        header('X-Content-Type-Options: nosniff');
        // link.php URLs carry their one-time token - don't leak any URL.
        header('Referrer-Policy: no-referrer');
    }
    if (session_status() === PHP_SESSION_NONE) {
        // Own cookie name, scoped to this site's folder: the project may live
        // in a subdirectory next to other PHP apps on the same domain, whose
        // PHPSESSID would otherwise be shared (and could reset our CSRF token).
        session_name('ncdw_session');
        $path = rtrim(str_replace('\\', '/', dirname($_SERVER['SCRIPT_NAME'] ?? '/')), '/') . '/';
        ini_set('session.cookie_path', $path);
        ini_set('session.use_strict_mode', '1');
        ini_set('session.cookie_httponly', '1');
        ini_set('session.cookie_samesite', 'Lax');
        if (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') {
            ini_set('session.cookie_secure', '1');
        }
    }
}
