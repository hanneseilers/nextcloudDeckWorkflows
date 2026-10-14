<?php

namespace NextcloudDeckWorkflows;

/**
 * Decrypts (only - this project never needs to encrypt from PHP) a Fernet
 * token (https://github.com/fernet/spec), matching Python's `cryptography`
 * library (Fernet) used by automation/config/secrets.py to encrypt an
 * `encrypted_app_password` in config/nextcloud.yaml. Implemented directly
 * via openssl/hash_hmac (both near-universal PHP extensions) instead of a
 * dependency, since this is read-only and the format is small and stable.
 *
 * Token layout (after base64url-decoding): 1 byte version (0x80) + 8 bytes
 * big-endian timestamp (ignored here - no TTL check) + 16 bytes IV + N
 * bytes AES-128-CBC ciphertext (PKCS7-padded) + 32 bytes HMAC-SHA256 over
 * everything before it. The Fernet key, once base64url-decoded, is the
 * signing key (first 16 bytes, for the HMAC) followed by the encryption
 * key (last 16 bytes, for AES).
 */
class Fernet
{
    public static function decrypt(string $token, string $base64Key): string
    {
        $key = self::base64UrlDecode($base64Key);
        if (strlen($key) !== 32) {
            throw new \RuntimeException('Fernet key must decode to exactly 32 bytes');
        }
        $signingKey = substr($key, 0, 16);
        $encryptionKey = substr($key, 16, 16);

        $data = self::base64UrlDecode($token);
        if (strlen($data) < 1 + 8 + 16 + 32) {
            throw new \RuntimeException('Fernet token too short');
        }
        if ($data[0] !== "\x80") {
            throw new \RuntimeException('Unsupported Fernet token version');
        }

        $hmacGiven = substr($data, -32);
        $payload = substr($data, 0, -32);
        $hmacExpected = hash_hmac('sha256', $payload, $signingKey, true);
        if (!hash_equals($hmacExpected, $hmacGiven)) {
            throw new \RuntimeException('Fernet token signature mismatch - wrong key or corrupted data');
        }

        $iv = substr($payload, 9, 16);
        $ciphertext = substr($payload, 25);

        $plaintext = openssl_decrypt($ciphertext, 'aes-128-cbc', $encryptionKey, OPENSSL_RAW_DATA, $iv);
        if ($plaintext === false) {
            throw new \RuntimeException('Fernet decryption failed');
        }
        return $plaintext;
    }

    private static function base64UrlDecode(string $value): string
    {
        $padded = $value . str_repeat('=', (4 - strlen($value) % 4) % 4);
        $decoded = base64_decode(strtr($padded, '-_', '+/'), true);
        if ($decoded === false) {
            throw new \RuntimeException('Invalid base64url-encoded Fernet data');
        }
        return $decoded;
    }
}
