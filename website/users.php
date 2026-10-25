<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\BasicAuthUsers;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\Layout;

// The users of the site's Basic Auth - for the admin only (the first user of the
// .htpasswd file): add, set a new password, delete. Nothing else.
$users = BasicAuthUsers::fromRepoRoot();
$current = BasicAuthUsers::currentUser();

if (!$users->isAdmin($current)) {
    http_response_code(403);
    Layout::start('Benutzer', 'Benutzer');
    echo '<p class="notice error">Die Benutzerverwaltung ist nur für den Admin da'
        . ($current === null ? ' - und nur, wenn die Website per HTTP-Basic-Auth geschützt ist (siehe README).' : '.') . '</p>';
    Layout::end();
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    Csrf::requireValidPost();
    $action = (string) ($_POST['action'] ?? '');
    $name = trim((string) ($_POST['name'] ?? ''));
    $password = (string) ($_POST['password'] ?? '');
    $error = match ($action) {
        'add' => $users->add($name, $password),
        'password' => $users->setPassword($name, $password),
        'delete' => $users->delete($name),
        default => 'Unbekannte Aktion.',
    };
    $done = ['add' => "Benutzer '$name' angelegt.", 'password' => "Neues Passwort für '$name' gesetzt.", 'delete' => "Benutzer '$name' gelöscht."];
    Layout::flash($error === null ? 'ok' : 'error', $error ?? $done[$action]);
    header('Location: users.php');
    exit;
}

Layout::start('Benutzer', 'Benutzer', 'users');
$names = array_keys($users->read());
if (!$users->isWritable()) {
    echo '<p class="notice error">Die Passwortdatei <code>' . h($users->path()) . '</code> ist nicht beschreibbar - hier kann nichts geändert werden.</p>';
}
?>
<p class="muted">Diese Benutzer können sich an der Website anmelden (HTTP-Basic-Auth). Der erste Benutzer ist der Admin
    und der Einzige, der diese Seite sieht; er kann nicht gelöscht werden. Ein neues Passwort gilt sofort.</p>

<table>
    <thead><tr><th>Benutzer</th><th>Neues Passwort setzen</th><th></th></tr></thead>
    <tbody>
    <?php foreach ($names as $i => $name): ?>
        <tr>
            <td><?= h($name) ?><?= $i === 0 ? ' <span class="muted">(Admin)</span>' : '' ?></td>
            <td>
                <form method="post" action="users.php" class="inline">
                    <?= Csrf::field() ?>
                    <input type="hidden" name="action" value="password">
                    <input type="hidden" name="name" value="<?= h($name) ?>">
                    <input type="password" name="password" minlength="<?= BasicAuthUsers::MIN_PASSWORD_LENGTH ?>" required
                           autocomplete="new-password" placeholder="mind. <?= BasicAuthUsers::MIN_PASSWORD_LENGTH ?> Zeichen" aria-label="Neues Passwort für <?= h($name) ?>">
                    <button type="submit">Setzen</button>
                </form>
            </td>
            <td class="actions">
                <?php if ($i > 0): ?>
                    <form method="post" action="users.php" class="inline" onsubmit="return confirm('Benutzer <?= h(addslashes($name)) ?> wirklich löschen?');">
                        <?= Csrf::field() ?>
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="name" value="<?= h($name) ?>">
                        <button type="submit" class="danger icon-btn" title="Löschen" aria-label="Benutzer <?= h($name) ?> löschen"><?= Layout::icon('trash') ?></button>
                    </form>
                <?php endif; ?>
            </td>
        </tr>
    <?php endforeach; ?>
    </tbody>
</table>

<h2>Benutzer anlegen</h2>
<form method="post" action="users.php" class="inline">
    <?= Csrf::field() ?>
    <input type="hidden" name="action" value="add">
    <input type="text" name="name" required maxlength="64" pattern="[A-Za-z0-9._@\-]+" placeholder="Benutzername" aria-label="Benutzername" autocomplete="off">
    <input type="password" name="password" minlength="<?= BasicAuthUsers::MIN_PASSWORD_LENGTH ?>" required autocomplete="new-password"
           placeholder="Passwort (mind. <?= BasicAuthUsers::MIN_PASSWORD_LENGTH ?> Zeichen)" aria-label="Passwort">
    <button type="submit" class="with-icon"><?= Layout::icon('plus') ?> Anlegen</button>
</form>
<?php Layout::end();
