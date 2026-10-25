<?php

namespace NextcloudDeckWorkflows;

/**
 * The users of the site's HTTP Basic Auth: reads and edits the .htpasswd file
 * website/.htaccess points to (AuthUserFile; website/.htpasswd if there is none).
 * The first user in that file is the admin - the one tools/install.sh created -
 * and the only one who sees users.php. Passwords are stored as Apache's
 * "$apr1$" MD5 hashes, exactly what `openssl passwd -apr1` writes.
 *
 * The web server does the authentication; this class only trusts the user name
 * it reports (REMOTE_USER / PHP_AUTH_USER). Without Basic Auth there is no
 * current user and nothing here is available.
 */
final class BasicAuthUsers
{
    public const MIN_PASSWORD_LENGTH = 8;

    public function __construct(private readonly string $websiteDir)
    {
    }

    public static function fromRepoRoot(): self
    {
        return new self(dirname(__DIR__));
    }

    /** The user the web server authenticated, or null (no Basic Auth in front of this page). */
    public static function currentUser(): ?string
    {
        foreach (['REMOTE_USER', 'REDIRECT_REMOTE_USER', 'PHP_AUTH_USER'] as $key) {
            if (!empty($_SERVER[$key]) && is_string($_SERVER[$key])) {
                return $_SERVER[$key];
            }
        }
        // PHP behind CGI/FastCGI: only the raw header arrives (see the RewriteRule in .htaccess)
        $header = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
        if (is_string($header) && stripos($header, 'basic ') === 0) {
            $decoded = base64_decode(substr($header, 6), true);
            if ($decoded !== false && str_contains($decoded, ':')) {
                return explode(':', $decoded, 2)[0];
            }
        }
        return null;
    }

    public function isAdmin(?string $user): bool
    {
        if ($user === null) {
            return false;
        }
        $names = array_keys($this->read());
        return $names !== [] && $names[0] === $user;
    }

    public function path(): string
    {
        $htaccess = $this->websiteDir . '/.htaccess';
        if (is_file($htaccess) && preg_match('/^\s*AuthUserFile\s+"?([^"\r\n]+?)"?\s*$/mi', (string) file_get_contents($htaccess), $m)) {
            return $m[1];
        }
        return $this->websiteDir . '/.htpasswd';
    }

    /** @return array<string, string> user name => hash, in file order */
    public function read(): array
    {
        $path = $this->path();
        $users = [];
        if (!is_file($path)) {
            return $users;
        }
        foreach (preg_split('/\r?\n/', (string) file_get_contents($path)) as $line) {
            if ($line === '' || $line[0] === '#' || !str_contains($line, ':')) {
                continue;
            }
            [$name, $hash] = explode(':', $line, 2);
            $users[$name] = $hash;
        }
        return $users;
    }

    public function isWritable(): bool
    {
        $path = $this->path();
        return is_file($path) && is_writable($path);
    }

    /** @return string|null an error message, null on success */
    public function add(string $name, string $password): ?string
    {
        if (($error = $this->checkName($name) ?? $this->checkPassword($password)) !== null) {
            return $error;
        }
        return $this->change(function (array $users) use ($name, $password) {
            if (isset($users[$name])) {
                return "Den Benutzer '$name' gibt es schon.";
            }
            $users[$name] = self::hash($password);
            return $users;
        });
    }

    /** @return string|null an error message, null on success */
    public function setPassword(string $name, string $password): ?string
    {
        if (($error = $this->checkPassword($password)) !== null) {
            return $error;
        }
        return $this->change(function (array $users) use ($name, $password) {
            if (!isset($users[$name])) {
                return "Den Benutzer '$name' gibt es nicht.";
            }
            $users[$name] = self::hash($password);
            return $users;
        });
    }

    /** @return string|null an error message, null on success */
    public function delete(string $name): ?string
    {
        return $this->change(function (array $users) use ($name) {
            if (!isset($users[$name])) {
                return "Den Benutzer '$name' gibt es nicht.";
            }
            if (array_key_first($users) === $name) {
                return 'Der Admin kann nicht gelöscht werden.';
            }
            unset($users[$name]);
            return $users;
        });
    }

    /** Apache's "$apr1$" MD5 crypt - the same as `openssl passwd -apr1 -salt <salt> <password>`. */
    public static function hash(string $password, ?string $salt = null): string
    {
        $alphabet = './0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
        if ($salt === null) {
            $salt = '';
            for ($i = 0; $i < 8; $i++) {
                $salt .= $alphabet[random_int(0, 63)];
            }
        }
        $len = strlen($password);
        $final = md5($password . $salt . $password, true);
        $text = $password . '$apr1$' . $salt . substr(str_repeat($final, intdiv($len, 16) + 1), 0, $len);
        for ($i = $len; $i > 0; $i >>= 1) {
            $text .= ($i & 1) ? "\0" : $password[0];
        }
        $final = md5($text, true);
        for ($i = 0; $i < 1000; $i++) {
            $round = ($i & 1) ? $password : $final;
            if ($i % 3) {
                $round .= $salt;
            }
            if ($i % 7) {
                $round .= $password;
            }
            $round .= ($i & 1) ? $final : $password;
            $final = md5($round, true);
        }
        $encode = static function (int $a, int $b, int $c, int $count) use ($final, $alphabet): string {
            $value = (($a >= 0 ? ord($final[$a]) : 0) << 16) | (($b >= 0 ? ord($final[$b]) : 0) << 8) | ord($final[$c]);
            $out = '';
            while ($count-- > 0) {
                $out .= $alphabet[$value & 0x3f];
                $value >>= 6;
            }
            return $out;
        };
        return '$apr1$' . $salt . '$' . $encode(0, 6, 12, 4) . $encode(1, 7, 13, 4) . $encode(2, 8, 14, 4)
            . $encode(3, 9, 15, 4) . $encode(4, 10, 5, 4) . $encode(-1, -1, 11, 2);
    }

    private function checkName(string $name): ?string
    {
        return preg_match('/^[A-Za-z0-9._@-]{1,64}$/', $name) === 1
            ? null
            : 'Der Benutzername darf nur Buchstaben, Ziffern und . _ @ - enthalten (höchstens 64 Zeichen).';
    }

    private function checkPassword(string $password): ?string
    {
        if (strlen($password) < self::MIN_PASSWORD_LENGTH) {
            return 'Das Passwort braucht mindestens ' . self::MIN_PASSWORD_LENGTH . ' Zeichen.';
        }
        return strlen($password) > 200 ? 'Das Passwort ist zu lang (höchstens 200 Zeichen).' : null;
    }

    /**
     * Reads the file under a lock, lets $edit change the user list (it returns the new list, or an
     * error message), and writes it back - two admins saving at once can't lose each other's change.
     *
     * @param callable(array<string, string>): (array<string, string>|string) $edit
     */
    private function change(callable $edit): ?string
    {
        $path = $this->path();
        if (!is_file($path) || !is_writable($path)) {
            return "Die Passwortdatei '$path' fehlt oder ist nicht beschreibbar.";
        }
        $handle = fopen($path, 'c+');
        if ($handle === false || !flock($handle, LOCK_EX)) {
            return "Die Passwortdatei '$path' konnte nicht gesperrt werden.";
        }
        try {
            rewind($handle);
            $users = [];
            foreach (preg_split('/\r?\n/', (string) stream_get_contents($handle)) as $line) {
                if ($line !== '' && $line[0] !== '#' && str_contains($line, ':')) {
                    [$name, $hash] = explode(':', $line, 2);
                    $users[$name] = $hash;
                }
            }
            $result = $edit($users);
            if (is_string($result)) {
                return $result;
            }
            $text = '';
            foreach ($result as $name => $hash) {
                $text .= $name . ':' . $hash . "\n";
            }
            ftruncate($handle, 0);
            rewind($handle);
            fwrite($handle, $text);
            fflush($handle);
            return null;
        } finally {
            flock($handle, LOCK_UN);
            fclose($handle);
        }
    }
}
