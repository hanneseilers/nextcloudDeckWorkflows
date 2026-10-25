<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\Config;
use NextcloudDeckWorkflows\EventTypes;
use NextcloudDeckWorkflows\Layout;
use NextcloudDeckWorkflows\ModuleRegistry;

// Reference of every step type: what it does, its input fields (real names,
// as in the YAML and in "Felder der Action") and the values it hands on -
// the same texts as a step's "i" box in the editor, all on one page.
Config::fromRepoRoot(); // sets the configured timezone for the example values below
$registry = ModuleRegistry::fromRepoRoot();
$modulesStale = !$registry->refreshIfStale(); // an outdated list is renewed in the background
$modules = $registry->all();
usort($modules, static fn (array $a, array $b) => strcoll(mb_strtolower($a['label'] ?? $a['name']), mb_strtolower($b['label'] ?? $b['name'])));

// Same list as CARD_FIELDS in assets/builder.js (the "Karte" source of the
// value picker) - any other field the Deck API returns works as well.
$cardFields = [
    'title' => 'Titel',
    'description' => 'Beschreibung',
    'duedate' => 'Fälligkeitsdatum',
    'labels' => 'Labels',
    'assignedUsers' => 'Zugewiesene Benutzer',
    'owner' => 'Ersteller',
    'done' => 'Erledigt (Datum)',
    'archived' => 'Archiviert',
    'id' => 'Karten-Id',
    'stackId' => 'Spalten-Id',
    'createdAt' => 'Erstellt am (Zeitstempel)',
    'lastModified' => 'Zuletzt geändert (Zeitstempel)',
    'lastEditor' => 'Zuletzt bearbeitet von',
    'order' => 'Position in der Spalte',
    'overdue' => 'Überfällig-Status',
    'commentsCount' => 'Anzahl Kommentare',
    'attachmentCount' => 'Anzahl Anhänge',
];

/** A default value as it would be written in the YAML / "Felder der Action". */
function defaultValue(mixed $value): string
{
    if ($value === null || $value === '' || $value === []) {
        return '';
    }
    return json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}
?>
<?php Layout::start('Doku', 'Dokumentation', 'docs'); ?>

<?php if ($modulesStale && $registry->isAvailable()): ?>
    <?= Layout::staleModulesNotice() ?>
<?php endif; ?>

<?php if (!$registry->isAvailable()): ?>
    <p class="notice">Noch keine <code>automation/var/modules.json</code> - sie entsteht beim ersten Lauf von
    <code>python -m automation.main</code> (oder mit <code>python -m automation.main --list-modules</code>).</p>
<?php else: ?>

<p class="muted">Alle Schritte mit ihren Eingabefeldern und den Werten, die sie an spätere Schritte weitergeben.
Die Feldnamen in <code>code</code> sind die echten Namen - so stehen sie in der YAML-Datei und so trägt man sie z. B. bei
„Einmal-Link erstellen" unter „Felder der Action" ein.</p>

<div class="filters">
    <label>Suche <input type="search" id="docs-filter" placeholder="Schritt oder Feldname …" autocomplete="off"></label>
</div>

<nav class="docs-toc" aria-label="Schritte">
    <?php foreach ($modules as $module): ?>
    <a href="#<?= h($module['name']) ?>"><?= h($module['label'] ?? $module['name']) ?></a>
    <?php endforeach; ?>
    <a href="#card-fields">Kartenfelder</a>
    <a href="#date-values">Datum und Uhrzeit</a>
    <a href="#events">Auslöser</a>
</nav>

<?php foreach ($modules as $module): ?>
<?php
    $inputs = is_array($module['input'] ?? null) ? $module['input'] : [];
    $outputs = is_array($module['output'] ?? null) ? $module['output'] : [];
    $paramLabels = $module['param_labels'] ?? [];
    $paramHelp = $module['param_help'] ?? [];
    $outputLabels = $module['output_labels'] ?? [];
?>
<section class="doc-module" id="<?= h($module['name']) ?>">
    <h2><?= h($module['label'] ?? $module['name']) ?> <code class="small"><?= h($module['name']) ?></code></h2>
    <?php if (!empty($module['description'])): ?><p><?= h($module['description']) ?></p><?php endif; ?>
    <?php if (!empty($module['requires'])): ?>
        <p class="muted small">Benötigt: <?= h(implode(', ', $module['requires'])) ?></p>
    <?php endif; ?>

    <h3>Eingabefelder</h3>
    <?php if ($inputs === []): ?>
        <p class="muted">Keine.</p>
    <?php else: ?>
    <table class="doc-table">
        <thead><tr><th>Feld</th><th>Bedeutung</th><th>Standardwert</th></tr></thead>
        <tbody>
        <?php foreach ($inputs as $name => $default): ?>
            <tr>
                <td><code><?= h((string) $name) ?></code></td>
                <td><?= h((string) ($paramLabels[$name] ?? '')) ?>
                    <?php if (!empty($paramHelp[$name])): ?><div class="muted small"><?= h((string) $paramHelp[$name]) ?></div><?php endif; ?></td>
                <td><?= defaultValue($default) === '' ? '<span class="muted">–</span>' : '<code>' . h(defaultValue($default)) . '</code>' ?></td>
            </tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <?php endif; ?>

    <h3>Liefert für spätere Schritte</h3>
    <?php if ($outputs === []): ?>
        <p class="muted">Nichts.</p>
    <?php else: ?>
    <table class="doc-table">
        <thead><tr><th>Feld</th><th>Bedeutung</th></tr></thead>
        <tbody>
        <?php foreach (array_keys($outputs) as $name): ?>
            <tr><td><code><?= h((string) $name) ?></code></td><td><?= h((string) ($outputLabels[$name] ?? '')) ?></td></tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <?php endif; ?>
</section>
<?php endforeach; ?>

<section class="doc-module" id="card-fields">
    <h2>Kartenfelder <span class="muted small">Quelle „Karte"</span></h2>
    <p>Ohne eigenen Schritt verfügbar: die Felder der Karte, die den Workflow ausgelöst hat (bei „Wert übernehmen" die
    Quelle „Karte"). Die Werte kommen direkt aus der Deck-API - weitere Felder gehen über „Anderes Feld …".</p>
    <table class="doc-table">
        <thead><tr><th>Feld</th><th>Bedeutung</th></tr></thead>
        <tbody>
        <?php foreach ($cardFields as $name => $label): ?>
            <tr><td><code><?= h($name) ?></code></td><td><?= h($label) ?></td></tr>
        <?php endforeach; ?>
        </tbody>
    </table>
</section>

<section class="doc-module" id="date-values">
    <h2>Datum und Uhrzeit <span class="muted small">Quelle „Datum und Uhrzeit (jetzt)“ und Platzhalter</span></h2>
    <p>Immer verfügbar, ohne eigenen Schritt: in <strong>Texten</strong> (Kommentar, E-Mail, „Text zusammensetzen“ und
    allen Vorlagen) als <code>$date</code>, <code>$day</code>, <code>$weekday</code>, und bei „Wert übernehmen“ als Quelle
    „Datum und Uhrzeit (jetzt)“ (in der YAML <code>{$ref: now.day}</code>). Der Wert gilt zum Zeitpunkt der Ausführung
    (ein Kommentar „Erledigt am $day“ in einem Einmal-Link zeigt den Tag des Klicks) und richtet sich nach der
    eingestellten Zeitzone (<code>timezone</code>). Eine Variable oder ein Eintrag unter „Werte“ mit demselben Namen hat Vorrang.</p>
    <table class="doc-table">
        <thead><tr><th>Feld</th><th>Bedeutung</th><th>Beispiel</th></tr></thead>
        <tbody>
        <tr><td><code>date</code></td><td>Datum und Uhrzeit (TT.MM.JJJJ hh:mm)</td><td><?= h(date('d.m.Y H:i')) ?></td></tr>
        <tr><td><code>day</code></td><td>Datum (TT.MM.JJJJ)</td><td><?= h(date('d.m.Y')) ?></td></tr>
        <tr><td><code>weekday</code></td><td>Wochentag</td><td><?= h(['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'][(int) date('w')]) ?></td></tr>
        </tbody>
    </table>
</section>

<section class="doc-module" id="events">
    <h2>Auslöser</h2>
    <p>Wann ein Workflow startet (Feld <code>trigger.event</code>). Neben Karten-Ereignissen gibt es den Zeitplan-Auslöser.</p>
    <table class="doc-table">
        <thead><tr><th>Wert</th><th>Bedeutung</th></tr></thead>
        <tbody>
        <?php foreach (EventTypes::labels() as $value => $label): ?>
            <tr><td><code><?= h($value) ?></code></td><td><?= h($label) ?></td></tr>
        <?php endforeach; ?>
        </tbody>
    </table>
    <p class="muted small">„Neue Person zugewiesen", „Fälligkeitsdatum geändert", „Beschreibung geändert" und „Label geändert"
    kommen zusätzlich zu „Karte geändert", das bei jeder Änderung auslöst.</p>
</section>

<script>
(function () {
  var input = document.getElementById('docs-filter');
  var sections = document.querySelectorAll('.doc-module');
  var links = document.querySelectorAll('.docs-toc a');
  input.addEventListener('input', function () {
    var query = input.value.trim().toLowerCase();
    sections.forEach(function (section, index) {
      var visible = query === '' || section.textContent.toLowerCase().indexOf(query) !== -1;
      section.hidden = !visible;
      if (links[index]) {
        links[index].hidden = !visible;
      }
    });
  });
})();
</script>
<?php endif; ?>

<?php Layout::end(); ?>
