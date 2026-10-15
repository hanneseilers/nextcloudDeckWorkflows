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

    /**
     * Enforces the "must be POST with a valid CSRF token, or 400" guard that
     * every state-changing endpoint needs - one place for it instead of each
     * entry point (delete.php, toggle.php, duplicate.php, start_test_run.php, ...)
     * repeating the same few lines, which is how the id-validation gap this
     * review found slipped into three of them without the fourth (save.php,
     * which validates its own id) ever being affected. Exits itself on
     * failure, same as the inline checks it replaces; save.php keeps its own
     * check since it renders a full HTML error page instead of a plain one.
     */
    public static function requireValidPost(string $invalidMessage = 'Invalid request.'): void
    {
        if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !self::verify($_POST['csrf_token'] ?? null)) {
            http_response_code(400);
            echo $invalidMessage;
            exit;
        }
    }
}
