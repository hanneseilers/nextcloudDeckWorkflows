<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\Csrf;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\TemplateStore;
use NextcloudDeckWorkflows\WorkflowRepository;

// Text templates: create, edit, rename and delete the files that "E-Mail senden",
// "Text zusammensetzen" and "Kommentar hinzufügen" can use.
$config = Config::fromRepoRoot();
$store = TemplateStore::fromRepoRoot();
$workflows = new WorkflowRepository($config->workflowsDir());

Csrf::token(); // starts the session (the draft of a failed save lives there)
$draft = $_SESSION['template_draft'] ?? null;
unset($_SESSION['template_draft']);

$store->migrateLegacy();
$names = $store->names();

$selectedName = trim((string) ($_GET['name'] ?? ''));
$isNew = isset($_GET['new']);
if ($selectedName !== '' && !$store->exists($selectedName)) {
    Layout::flash('error', "Die Vorlage '" . $selectedName . "' gibt es nicht.");
    $selectedName = '';
}
if ($selectedName !== '') {
    $isNew = false;
}

// What the editor shows: the file, or what was typed when saving failed.
$current = $selectedName !== '' ? $store->read($selectedName) : null;
$fields = ['name' => '', 'subject' => '', 'body' => '', 'version' => ''];
if ($current !== null) {
    $parts = TemplateStore::splitEmail($current['content']);
    $fields = ['name' => $current['name'], 'subject' => $parts['subject'], 'body' => $parts['body'], 'version' => $current['version']];
}
if (is_array($draft) && ($draft['new'] ? $isNew : (!$isNew && $draft['name'] === $selectedName))) {
    $fields['subject'] = (string) $draft['subject'];
    $fields['body'] = (string) $draft['body'];
    $fields['name'] = $draft['new'] ? (string) $draft['name'] : $fields['name'];
}
$editing = $current !== null || $isNew;

// Where each template is used (one pass over the workflows).
$usageMap = $store->usageMap($workflows);
$usage = [];
foreach ($names as $name) {
    $usage[$name] = $usageMap[$name] ?? [];
}
$usedHere = $current !== null ? $usage[$current['name']] : [];

Layout::start('Vorlagen', 'Vorlagen', 'templates');
?>
<details class="help-box" id="template-help" open>
    <summary>Hilfe: Wie funktionieren Vorlagen?</summary>
    <div class="help-body">
        <p>Eine <strong>Vorlage</strong> ist ein Text mit Platzhaltern, den du einmal schreibst und in mehreren Workflows
        verwendest. Es gibt nur eine Art von Vorlage - sie funktioniert überall gleich:</p>
        <ul>
            <li><strong>E-Mail senden:</strong> bei „Textvorlage“ auswählen - der Text wird zum Inhalt der Mail, die
                <em>Betreff</em>-Zeile zum Betreff.</li>
            <li><strong>Text zusammensetzen</strong> und <strong>Kommentar hinzufügen:</strong> bei „Textvorlage“
                auswählen - der Text ersetzt das Feld Vorlage bzw. Kommentar. Der Betreff wird dort nicht gebraucht.</li>
        </ul>
        <p><strong>Platzhalter</strong> schreibst du als <code>$name</code> oder <code>${name}</code>
        (Name aus Buchstaben, Ziffern und _; <code>${name}</code> hilft, wenn direkt danach ein Buchstabe folgt:
        <code>${nummer}x</code>). Beim Ausführen wird jeder Platzhalter durch einen Wert ersetzt:</p>
        <ul>
            <li>durch eine <em>Variable</em> mit diesem Namen (Schritt „Variable setzen“) - gilt überall;</li>
            <li>bei „E-Mail senden“ durch den Eintrag gleichen Namens unter „Werte für die Vorlage“,
                bei „Text zusammensetzen“ unter „Werte“ (der Eintrag hat Vorrang vor der Variablen).</li>
        </ul>
        <p>Gibt es zu einem Platzhalter keinen Wert, bleibt er <em>unverändert im Text stehen</em> - es gibt keinen Fehler.
        Ein echtes Dollarzeichen schreibst du als <code>$$</code>.</p>
        <p><strong>Betreff:</strong> Nur für E-Mails. Er wird als erste Zeile <code>Subject: …</code> gefolgt von einer
        Leerzeile in der Datei gespeichert - hier trägst du ihn einfach ins Feld „Betreff“ ein. Ein im Schritt
        eingetragener Betreff hat Vorrang. Auch der Betreff darf Platzhalter enthalten.</p>
        <p><strong>Beispiel:</strong> Text <code>Ticket $nummer: $titel</code>, dazu ein Schritt „Text zusammensetzen“ mit
        den Werten <code>{"nummer": {"$ref": "…"}, "titel": {"$ref": "card.title"}}</code> ergibt „Ticket 0273: Drucker defekt“.</p>
        <p><strong>Umbenennen und Löschen:</strong> Beim Umbenennen kannst du die Verweise in den Workflows gleich mit
        ändern lassen. Eine Vorlage, die noch in einem Workflow verwendet wird, lässt sich nicht löschen.
        Die Dateien liegen als <code>config/text_templates/&lt;Name&gt;.txt</code> auf dem Server.</p>
    </div>
</details>

<div class="toolbar">
    <a class="button with-icon" href="templates.php?new=1"><?= Layout::icon('plus') ?> Neue Vorlage</a>
</div>

<div class="template-layout">
    <nav class="template-list" aria-label="Vorlagen">
        <?php if ($names === []): ?>
            <p class="muted">Noch keine Vorlage. Mit „Neue Vorlage“ legst du die erste an.</p>
        <?php endif; ?>
        <ul>
        <?php foreach ($names as $name): ?>
            <li<?= $current !== null && $current['name'] === $name ? ' class="is-selected"' : '' ?>>
                <a href="templates.php?name=<?= h(rawurlencode($name)) ?>"><?= Layout::icon('file-text') ?> <?= h($name) ?></a>
                <span class="muted small"><?= count($usage[$name]) === 0 ? 'nicht verwendet' : 'in ' . count($usage[$name]) . ' Workflow' . (count($usage[$name]) === 1 ? '' : 's') ?></span>
            </li>
        <?php endforeach; ?>
        </ul>
    </nav>

    <section class="template-editor">
    <?php if (!$editing): ?>
        <p class="muted">Links eine Vorlage auswählen oder eine neue anlegen.</p>
    <?php else: ?>
        <form method="post" action="template_action.php" id="template-form" class="template-form">
            <?= Csrf::field() ?>
            <input type="hidden" name="action" value="<?= $isNew ? 'create' : 'save' ?>">
            <?php if ($isNew): ?>
                <h2>Neue Vorlage</h2>
                <label>Name
                    <input type="text" name="name" value="<?= h($fields['name']) ?>" required maxlength="60" autofocus
                        placeholder="z. B. Freigabe-Mail">
                </label>
                <p class="muted small">Buchstaben, Ziffern, Leerzeichen, _ und - (bis 60 Zeichen).</p>
            <?php else: ?>
                <h2><?= h($fields['name']) ?></h2>
                <input type="hidden" name="name" value="<?= h($fields['name']) ?>">
                <input type="hidden" name="version" value="<?= h($fields['version']) ?>">
                <p class="muted small">Zuletzt geändert <?= Layout::dateTime(gmdate('c', $current['modified'])) ?>, <?= h(number_format($current['size'] / 1024, 1, ',', '.')) ?> KB.</p>
            <?php endif; ?>

            <label>Betreff <span class="muted small">(nur für E-Mails, kann leer bleiben)</span>
                <input type="text" name="subject" id="template-subject" value="<?= h($fields['subject']) ?>" maxlength="200"
                    placeholder="z. B. Freigabe für $titel">
            </label>
            <label>Text
                <textarea name="body" id="template-body" rows="16" spellcheck="true"
                    placeholder="Hallo $name, ..."><?= h($fields['body']) ?></textarea>
            </label>
            <p class="small" id="template-placeholders" data-empty="Keine Platzhalter in dieser Vorlage."></p>
            <div class="toolbar">
                <button type="submit" class="button"><?= $isNew ? 'Vorlage anlegen' : 'Speichern' ?></button>
                <?php if ($isNew): ?><a href="templates.php">Abbrechen</a><?php endif; ?>
            </div>
        </form>

        <?php if (!$isNew && $current !== null): ?>
        <div class="template-more">
            <h3>Verwendet in</h3>
            <?php if ($usedHere === []): ?>
                <p class="muted">Diese Vorlage wird in keinem Workflow verwendet.</p>
            <?php else: ?>
                <ul>
                <?php foreach ($usedHere as $workflow): ?>
                    <li><a href="new.php?id=<?= h(rawurlencode($workflow['id'])) ?>"><?= h($workflow['name']) ?></a></li>
                <?php endforeach; ?>
                </ul>
            <?php endif; ?>

            <div class="toolbar">
                <details class="popover">
                    <summary class="button with-icon"><?= Layout::icon('edit') ?> Umbenennen</summary>
                    <form method="post" action="template_action.php">
                        <?= Csrf::field() ?>
                        <input type="hidden" name="action" value="rename">
                        <input type="hidden" name="name" value="<?= h($current['name']) ?>">
                        <label>Neuer Name <input type="text" name="new_name" value="<?= h($current['name']) ?>" required maxlength="60"></label>
                        <?php if ($usedHere !== []): ?>
                            <label class="checkbox"><input type="checkbox" name="update_references" value="1" checked>
                                Verweise in <?= count($usedHere) ?> Workflow<?= count($usedHere) === 1 ? '' : 's' ?> mitändern</label>
                        <?php endif; ?>
                        <button type="submit">Umbenennen</button>
                    </form>
                </details>

                <?php if ($usedHere === []): ?>
                <form method="post" action="template_action.php" class="inline" data-confirm="Die Vorlage '<?= h($current['name']) ?>' endgültig löschen?">
                    <?= Csrf::field() ?>
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="name" value="<?= h($current['name']) ?>">
                    <button type="submit" class="danger with-icon"><?= Layout::icon('trash') ?> Löschen</button>
                </form>
                <?php else: ?>
                    <span class="muted small">Löschen geht erst, wenn kein Workflow die Vorlage mehr verwendet.</span>
                <?php endif; ?>
            </div>
        </div>
        <?php endif; ?>
    <?php endif; ?>
    </section>
</div>

<script src="assets/templates.js"></script>

<?php Layout::end(); ?>
