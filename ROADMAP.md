# Mögliche Features (Ideensammlung)

Eine Übersicht sinnvoller Erweiterungen, die über den aktuellen Stand
hinausgehen - keine Zusagen, sondern Kandidaten zur Priorisierung. Jeder
Punkt nennt kurz die Begründung und eine grobe Aufwandseinschätzung
(**klein** = ein bis zwei Dateien, **mittel** = mehrere Dateien/eine neue
Ports-Schnittstelle, **groß** = neues Architektur-Element).

## Workflow-Verwaltung (Website)

- **Workflow bearbeiten, statt nur löschen + neu anlegen** (mittel) -
  aktuell explizit nicht unterstützt (siehe website/README.md, "Scope of
  this iteration"). Der Baum-Editor aus `new.php`/`builder.js` existiert
  schon; er müsste nur mit den Daten eines bestehenden Workflows
  vorbefüllt und `save.php` um einen Update-statt-nur-Anlegen-Pfad
  ergänzt werden - die größere Arbeit ist eher an Sorgfalt (Id darf sich
  beim Bearbeiten nicht ändern, Validierung) als an neuer Architektur.
- **Workflow duplizieren** (klein) - eine Kopie mit neuer Id als
  Startpunkt für einen ähnlichen Workflow (z. B. "gleicher Ablauf, anderes
  Board"). Baut auf "Bearbeiten" auf oder geht unabhängig davon.
- **Ausführungs-Historie in der Website sichtbar machen** (mittel) - wird
  bereits lückenlos in `execution_log` (SQLite) mitgeschrieben, aber
  nirgends angezeigt; aktuell nur per Cron-Log oder `sqlite3`-Abfrage
  einsehbar. Eine einfache Liste ("Workflow X, Event Y, Erfolg/Fehler,
  Zeitpunkt") auf der Übersichtsseite wäre ein kleiner PHP-Lesezugriff auf
  eine bereits vorhandene Tabelle.
- **Workflow testweise auslösen, ohne auf ein echtes Event zu warten**
  (mittel) - z. B. ein Button "Mit Beispielwerten testen", der den
  Workflow einmal gegen eine konkrete, vom Nutzer gewählte Karte laufen
  lässt. Erleichtert das Einrichten komplexer Ketten erheblich (aktuell:
  Karte im echten Nextcloud ändern und abwarten/`automation/main.py`
  manuell starten).
- **Mehrbenutzer-Berechtigungen** (groß) - aktuell ist der Zugriffsschutz
  für `website/` alles-oder-nichts (eine gemeinsame HTTP-Basic-Auth für
  alle). Getrennte Logins mit z. B. "nur eigene Workflows sehen" wären ein
  echter Mehrbenutzer-Umbau, kein kleiner Zusatz.

## Trigger / Events

- **Zeitbasierte Trigger** (mittel) - "jeden Montag 9 Uhr" statt nur
  "wenn sich eine Karte ändert". Würde eine zweite Art von `Trigger`
  (neben `event_type`) sowie eine eigene Prüfung in `main.py` brauchen
  (ähnlich einem Cron-Ausdruck), unabhängig vom Polling-Mechanismus für
  Deck-Events. Sinnvoll für wiederkehrende Erinnerungen, die nicht an
  eine konkrete Karten-Änderung hängen.
- **Spezifisches "Label geändert"-Event** (klein) - es gibt bereits
  `card_assigned`/`card_due_date_changed`/`card_description_changed` als
  gezielte Ausschnitte von `card_updated`; ein Label-Äquivalent fehlt
  noch, ließe sich nach demselben Muster in `PollingEventSource._diff`
  ergänzen.
- **Checklisten-Events** (mittel) - Deck unterstützt Checklisten auf
  Karten; "Checklisten-Punkt erledigt" ist aktuell nicht abgebildet, weder
  im Snapshot noch als Event.
- **Webhooks statt/zusätzlich zu Polling** (groß) - würde Reaktionszeit
  und Nextcloud-API-Last reduzieren, bräuchte aber einen öffentlich
  erreichbaren Endpunkt auf der Website-Seite und eine Umstellung der
  Event-Erkennung - ein größerer architektonischer Schritt, kein
  Erweiterungsmodul.

## Neue Action-Module

- **Text zusammensetzen/interpolieren** (klein) - aktuell unterstützen nur
  `add_comment`/`send_email` `$platzhalter`-Ersetzung in Freitext; ein
  generisches Modul (`format_text` o. ä., mehrere `$ref`/Literale zu einem
  String kombinieren) würde das auch für `set_description`, `set_title`
  & Co. ermöglichen, ohne jedes dieser Module einzeln umzubauen.
- **Generischer HTTP-Aufruf** (mittel) - ein Modul, das eine beliebige URL
  aufruft (z. B. Slack/Teams/Discord-Webhook, oder ein eigener Dienst).
  Würde die Automatisierung für alles öffnen, was eine HTTP-API hat, ohne
  dass jedes Zielsystem ein eigenes Modul bräuchte.
- **Checklisten-Punkt hinzufügen/abhaken** (klein, sobald die Deck-API
  dafür im `DeckGatewayPort` ergänzt ist) - passt ins bestehende Muster
  der Karten-Aktionen (`set_title`/`add_label`/...).
- **RDATE/RECURRENCE-ID in `calendar_lookup`** (mittel) - bereits als
  bekannte Lücke im Code dokumentiert (`calendar_gateway.py`): einzelne
  verschobene/zusätzliche Termine einer Serie werden aktuell nicht
  erkannt, nur die reine `RRULE`+`EXDATE`-Wiederholung.
- **Einfache Zahlen-/Text-Vergleiche/Berechnungen als Modul** (klein) -
  etwa eine Summe/Differenz aus zwei `$ref`-Werten, ergänzend zu den
  bestehenden `if`/`else`-Vergleichsoperatoren.

## Zuverlässigkeit / Betrieb

- **Fehler-Benachrichtigung bei wiederholt fehlschlagenden Workflows**
  (mittel) - aktuell wird ein Fehler nur geloggt
  (`execution_log`/stderr); eine E-Mail an eine Admin-Adresse, wenn
  derselbe Workflow mehrfach hintereinander fehlschlägt, wäre mit
  `send_email` und einer Auswertung von `execution_log` umsetzbar.
- **Health-Check für Monitoring** (klein) - ein einfacher Endpunkt/Flag,
  der prüft "lief der letzte Cron-Lauf kürzlich erfolgreich", nutzbar für
  externe Uptime-Überwachung.
- **Verschlüsselte Ablage der App-Passwörter** (mittel) - `config/nextcloud.yaml`
  liegt aktuell im Klartext (abgesichert nur durch Dateisystem-Rechte);
  eine optionale Verschlüsselung (z. B. mit einem lokal gehaltenen
  Schlüssel) wäre ein Härtungsschritt für Shared-Hosting-Umgebungen mit
  mehreren Nutzern auf demselben Server.

## Entwicklung / Qualität

- **CI-Pipeline** (klein) - automatisches Ausführen von `pytest` + `php -l`
  bei jedem Push (z. B. GitHub Actions), statt wie aktuell nur manuell vor
  jedem Commit.
- **PHPUnit statt Ad-hoc-Skripten für PHP** (mittel) - die PHP-seitigen
  reinen Funktionen (`NextcloudApi::mapShareesResponse`,
  `mapPropfindCalendars`, ...) werden aktuell über eigene
  Reflection-Skripte verifiziert, weil kein Test-Runner eingerichtet ist;
  ein echtes PHPUnit-Setup würde das in die normale Entwickler-Routine
  (`composer test` o. ä.) integrieren.

---

Diese Liste ist absichtlich nicht vollständig - sie sammelt die Ideen, die
beim Arbeiten an diesem Projekt sichtbar wurden (ausdrücklich offene
Punkte wie "Bearbeiten nicht möglich" oder "RDATE nicht unterstützt" sind
bereits im Code/den READMEs vermerkt). Bei Interesse an einem der Punkte:
einfach benennen, dann wird daraus ein konkreter Plan.
