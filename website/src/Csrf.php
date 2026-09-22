<?php

namespace NextcloudDeckWorkflows;

/**
 * Minimal session-based CSRF protection for the POST forms (toggle/delete/save).
 * This is not authentication - the site is expected to be protected externally
 * (e.g. .htaccess Basic Auth, see website/README.md) - it only stops a third
 * party page from silently triggering state-changing requests here.
 */
class Csrf
{
    public static function token(): string
    {
        if (session_status() !== PHP_SESSION_ACTIVE) {
            session_start();
        }
        if (empty($_SESSION['csrf_token'])) {
            $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
        }
        return $_SESSION['csrf_token'];
    }

    public static function field(): string
    {
        return '<input type="hidden" name="csrf_token" value="' . htmlspecialchars(self::token()) . '">';
    }

    public static function verify(?string $submitted): bool
    {
        if (session_status() !== PHP_SESSION_ACTIVE) {
            session_start();
        }
        $expected = $_SESSION['csrf_token'] ?? null;
        return is_string($submitted) && is_string($expected) && hash_equals($expected, $submitted);
    }
}
