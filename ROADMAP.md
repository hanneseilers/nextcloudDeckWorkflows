# Mögliche Features (Ideensammlung)

Eine Übersicht sinnvoller Erweiterungen, die über den aktuellen Stand
hinausgehen - keine Zusagen, sondern Kandidaten zur Priorisierung. Jeder
Punkt nennt kurz die Begründung und eine grobe Aufwandseinschätzung
(**klein** = ein bis zwei Dateien, **mittel** = mehrere Dateien/eine neue
Ports-Schnittstelle, **groß** = neues Architektur-Element).

## Bereits umgesetzt

Diese Liste war die Grundlage für ein größeres Umsetzungs-Paket - Details
jeweils im `automation/README.md`:

- Workflow bearbeiten & duplizieren (`new.php?id=...`, "Duplizieren"-Button)
- Ausführungs-Historie in der Website (`history.php`)
- Workflow testweise auslösen (`test_run.php`, "Testlauf"-Button)
- Zeitbasierte Trigger (`Trigger.schedule`, siehe "Time-based (schedule)
  triggers" im README)
- Spezifisches "Label geändert"-Event (`card_label_changed`)
- Text zusammensetzen (`format_text`-Modul)
- Checklisten-Punkt hinzufügen (`add_checklist_item`-Modul)
- Einfache Berechnungen (`calculate`-Modul)
- Fehler-Benachrichtigung bei wiederholt fehlschlagenden Workflows
  (`error_notifications` in `settings.yaml`)
- Health-Check & Statistiken (`health.php`, inkl. `?format=json`)
- Verschlüsselte App-Passwörter (`encrypted_app_password`,
  `automation/config/secrets.py`)
- Webhooks statt/zusätzlich zu Polling (`website/webhook.php`,
  `core/domain/webhook_gate.py`) - mit der expliziten Einschränkung, dass
  Polling als Fallback bestehen bleibt (siehe README, "Webhooks" - Nextclouds
  tatsächliches Webhook-Verhalten konnte hier nicht an einer echten Instanz
  verifiziert werden)

## Noch offen

- **Generischer HTTP-Aufruf** (mittel) - ein Modul, das eine beliebige URL
  aufruft (z. B. Slack/Teams/Discord-Webhook, oder ein eigener Dienst).
  Würde die Automatisierung für alles öffnen, was eine HTTP-API hat, ohne
  dass jedes Zielsystem ein eigenes Modul bräuchte.
- **RDATE/RECURRENCE-ID in `calendar_lookup`** (mittel) - bereits als
  bekannte Lücke im Code dokumentiert (`calendar_gateway.py`): einzelne
  verschobene/zusätzliche Termine einer Serie werden aktuell nicht
  erkannt, nur die reine `RRULE`+`EXDATE`-Wiederholung.
- **Mehrbenutzer-Berechtigungen** (groß) - aktuell ist der Zugriffsschutz
  für `website/` alles-oder-nichts (eine gemeinsame HTTP-Basic-Auth für
  alle). Getrennte Logins mit z. B. "nur eigene Workflows sehen" wären ein
  echter Mehrbenutzer-Umbau, kein kleiner Zusatz.
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

Diese Liste ist absichtlich nicht vollständig. Bei Interesse an einem der
offenen Punkte: einfach benennen, dann wird daraus ein konkreter Plan.
