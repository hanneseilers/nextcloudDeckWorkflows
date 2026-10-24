# Tutorial: Workflows erstellen und verwenden

Dieses Tutorial führt Schritt für Schritt durch die Bedienung des Tools -
von den Grundbegriffen über einen einfachen ersten Workflow bis zu
komplexeren Automatisierungen. Ein durchgehendes Beispiel (ein
"Support"-Board) wird dabei von Schritt zu Schritt weiterentwickelt, statt
bei jedem Schritt ein neues Beispiel zu beginnen.

Für die technischen Hintergründe (Architektur, alle verfügbaren Module,
Fehlerverhalten) siehe [automation/README.md](automation/README.md). Für
eigene neue Module siehe [MODULE_GUIDE.md](MODULE_GUIDE.md).

## Grundlagen

Ein **Workflow** besteht aus drei Teilen:

1. **Wo?** - eine Nextcloud-Instanz, ein Board (Deck) und optional eine
   bestimmte Spalte. Lässt man die Spalte leer ("Alle Spalten"), reagiert
   der Workflow auf jeder Spalte des Boards.
2. **Wann?** - ein Event, auf das reagiert wird: `Karte erstellt`,
   `Karte verschoben`, `Neue Person zugewiesen`, `Fälligkeitsdatum geändert`,
   `Beschreibung geändert`, `Karte geändert (beliebiges Feld)` oder
   `Karte gelöscht`.
3. **Was passiert?** - eine Kette von **Modulen** (Schritten), die beim
   Eintreten des Events in der angegebenen Reihenfolge ausgeführt werden,
   z. B. einen Kommentar hinterlassen, ein Fälligkeitsdatum setzen, eine
   E-Mail schicken.

Workflows werden über die Website angelegt (`new.php`, erreichbar über
"+ Neuer Workflow" auf der Übersichtsseite `index.php`) und als YAML-Datei
unter `workflows/<Id>.yaml` gespeichert. Ein separat laufendes Python-Skript
(`automation/main.py`, typischerweise per Cron alle paar Minuten) prüft
regelmäßig, ob sich auf den konfigurierten Boards etwas geändert hat, und
führt die passenden Workflows aus.

**Voraussetzung für alles Folgende:** mindestens eine Nextcloud-Instanz ist
in `config/nextcloud.yaml` eingetragen (das erledigt `./configure.sh`, siehe README)
und das Automatisierungs-Skript wurde schon mindestens einmal ausgeführt
(`python -m automation.main --list-modules` reicht aus), damit die Website
die verfügbaren Module kennt.

**Zum lokalen Ausprobieren ohne auf ein echtes Event zu warten**: nach dem
Speichern eines Workflows einmal `python -m automation.main` manuell
ausführen - das prüft sofort auf Änderungen, statt auf den nächsten
Cron-Lauf zu warten. Was tatsächlich passiert ist, sieht man an der Karte
selbst in Nextcloud (neuer Kommentar, geändertes Fälligkeitsdatum, ...) und
im Log der Ausführung (stdout/`automation/var/cron.log`, je nach
Cron-Einrichtung) - es gibt (noch) keine Ausführungs-Historie in der
Website selbst.

---

## Schritt 1: Der einfachste Workflow

**Ausgangsszenario:** Ein Board "Support". Wenn eine neue Karte (= ein
neues Ticket) erstellt wird, soll automatisch ein Kommentar auf der Karte
hinterlassen werden, der bestätigt, dass das Ticket erfasst wurde.

### In der Website

1. Übersicht (`index.php`) → **+ Neuer Workflow**.
2. Unter **2. Wo?**: Nextcloud-Instanz wählen, dann das Board "Support" (Name
   eintippen, aus der Liste auswählen). Spalte leer lassen - das Ticket
   kann in jeder Spalte landen.
3. Unter **3. Wann?**: Event = `Karte erstellt`.
4. Unter **Workflow**: Name = "Ticket-Eingangsbestätigung", Id wird daraus
   automatisch vorgeschlagen (z. B. `ticket-eingangsbestaetigung`).
5. Unter **4. Was passiert?**: **+ Schritt**, als Modul
   `add_comment` wählen, Feld `message` = `Ticket wurde erfasst.`
6. **Workflow speichern**.

### Was dabei gespeichert wird

```yaml
id: ticket-eingangsbestaetigung
name: Ticket-Eingangsbestätigung
enabled: true
nextcloud_instance: prod
board_id: 42
trigger:
  event: card_created
actions:
  - module: add_comment
    params:
      message: "Ticket wurde erfasst."
```

Das ist bereits ein vollständiger, funktionierender Workflow.

---

## Schritt 2: Daten der Karte verwenden

**Erweiterung:** Der Kommentar soll den Titel des Tickets nennen, nicht nur
einen generischen Text.

Jede Karte, die einen Workflow auslöst, ist automatisch unter der
reservierten Quelle „Karte“ verfügbar (`card.title`, `card.description`,
`card.duedate`, ...) - dafür ist kein zusätzlicher Schritt nötig. Um einen
Kartenwert in einem **Freitext** wie `add_comment`s `message` zu verwenden,
geht man über eine **globale Variable**: `set_variable` liest den Wert
strukturiert per Referenz, danach kann er im Text als `$name` eingesetzt
werden.

### In der Website

Im Workflow aus Schritt 1, unter **4. Was passiert?**:

1. **+ Schritt** (vor dem bestehenden `add_comment`-Schritt per
   ↑ nach oben verschieben), Modul „Variable setzen“ (`set_variable`):
   - die Schritt-Id vergibt der Editor selbst aus Modul und Nummer: `set_variable_1`
     (erstes „Variable setzen“ im Workflow; steht in der Info-Box „i“ des Schritts)
   - Feld „Name“ (`name`): `titel`
   - Feld „Wert“ (`value`): auf **Wert übernehmen** umschalten, Quelle „Karte“,
     Ausgabefeld `title`
2. Im bestehenden `add_comment`-Schritt, Feld `message` ändern zu:
   `Ticket zu '$titel' wurde erfasst.`
3. **Workflow speichern**.

### YAML

```yaml
actions:
  - id: set_variable_1
    module: set_variable
    params:
      name: "titel"
      value: {$ref: card.title}
  - module: add_comment
    params:
      message: "Ticket zu '$titel' wurde erfasst."
```

Bei einer Karte mit Titel "Server antwortet nicht mehr" entsteht daraus der
Kommentar: `Ticket zu 'Server antwortet nicht mehr' wurde erfasst.`

---

## Schritt 3: Nur eine bestimmte Spalte, und ein Fälligkeitsdatum setzen

**Erweiterung:** Neue Tickets landen zunächst in der Spalte "Neu". Nur dort
soll der Workflow reagieren (nicht z. B. wenn später eine Karte aus einer
anderen Spalte hierher verschoben wird) - und zusätzlich soll automatisch
eine Fälligkeit von 3 Tagen gesetzt werden.

### In der Website

1. Unter **2. Wo?**: Spalte jetzt auf "Neu" setzen (statt "Alle Spalten").
2. Unter **4. Was passiert?**, zwei neue Schritte am Ende hinzufügen:
   - Modul „Datum verschieben“ (`date_offset`) - Id `date_offset_1` -, Feld „Tage“ (`days`) = `3` (Feld „Ausgangsdatum“ (`base`)
     leer lassen - dann wird ab heute gerechnet)
   - Modul „Fälligkeitsdatum setzen“ (`set_due_date`), Feld „Fälligkeitsdatum“ (`due_date`) auf **Wert übernehmen** umschalten,
     Quelle „Schritt …: Datum verschieben“ (`date_offset_1`), Ausgabefeld `date`
3. **Workflow speichern**.

### YAML

```yaml
trigger:
  event: card_created
  stack_id: 10   # die Id der Spalte "Neu"
actions:
  - id: set_variable_1
    module: set_variable
    params:
      name: "titel"
      value: {$ref: card.title}
  - module: add_comment
    params:
      message: "Ticket zu '$titel' wurde erfasst."
  - id: date_offset_1
    module: date_offset
    params:
      days: 3
  - module: set_due_date
    params:
      due_date: {$ref: date_offset_1.date}
```

`date_offset` ohne `base` rechnet ab dem aktuellen Zeitpunkt; sein Ergebnis
(`date_offset_1.date`) wird direkt in `set_due_date` weitergereicht - zwei
Module, die zusammenarbeiten, ohne dass eine eigene Code-Zeile dafür nötig
war.

---

## Schritt 4: Verzweigung (Wenn/Sonst)

**Erweiterung:** Enthält der Titel das Wort "dringend", soll das Ticket
mit einem Prioritäts-Label versehen und einem erfahrenen Mitarbeiter
zugewiesen werden - sonst dem normalen Erstsupport.

### In der Website

Unter **4. Was passiert?**, am Ende **+ Wenn/Sonst** hinzufügen:

1. Bedingung: linke Seite auf **Wert übernehmen** umschalten, Quelle „Karte“,
   Ausgabefeld `title`; Operator `enthält`; rechte Seite (Fester Wert)
   `dringend`.
2. Im **Dann:**-Zweig, zwei Schritte: `add_label` (Feld „Label“ (`label_id`): die Id
   des Prioritäts-Labels, z. B. `99`) und `assign_user` (Feld „Benutzer“ (`user_id`):
   Name eintippen und auswählen - z. B. eine zweite Support-Ebene).
3. Im **Sonst:**-Zweig: `assign_user` mit dem Erstsupport-Benutzer.
4. **Workflow speichern**.

### YAML

```yaml
actions:
  # ... (set_variable_1, add_comment, date_offset_1, set_due_date wie in Schritt 3) ...
  - type: if
    condition:
      left: {$ref: card.title}
      op: contains
      right: "dringend"
    then:
      - module: add_label
        params:
          label_id: 99
      - module: assign_user
        params:
          user_id: "zweite-ebene"
    else:
      - module: assign_user
        params:
          user_id: "erste-ebene"
```

Verfügbare Operatoren (in der Website als Dropdown): `=`, `≠`, `<`, `>`,
`enthält`, `beginnt mit`, `endet mit`.

---

## Schritt 5: Eine eindeutige Ticketnummer vergeben

**Erweiterung:** Jedes Ticket soll eine eindeutige, nie doppelt vergebene
Nummer bekommen - z. B. um sie auf einem Lieferschein oder in einer
E-Mail an den Kunden referenzieren zu können.

`generate_random_number` erzeugt genau das: eine Zufallszahl mit
führenden Nullen, die noch nicht vergeben wurde (gegen eine dauerhaft
gespeicherte Liste geprüft, siehe automation/README.md).

### In der Website

Am Ende der Schrittliste:

1. Modul „Zufallszahl erzeugen“ (`generate_random_number`) - Id `generate_random_number_1`. Felder: `list_name` =
   `tickets`, `min_digits` = `4` (also mind. 4-stellig, z. B. "0273"),
   `save` = aktiviert (Standard - die Nummer wird als "vergeben"
   gespeichert).
2. Modul „Variable setzen“ (`set_variable`) - Id `set_variable_2`, das zweite „Variable setzen“: `name` = `ticket_nr`, `value`
   per Referenz von `generate_random_number_1`, Feld „Zahl“ (`number`).
3. Modul „Beschreibung setzen“ (`set_description`), Feld `description` per Referenz von `generate_random_number_1`,
   Feld „Zahl“ (`number`) - die Nummer wird so direkt auf der Karte gespeichert,
   nicht nur in diesem einen Workflow-Lauf.
4. Im bestehenden `add_comment`-Schritt die Nachricht erweitern, z. B.
   `Ticket-Nr: $ticket_nr. Ticket zu '$titel' wurde erfasst.`
5. **Workflow speichern**.

### YAML

```yaml
actions:
  # ... (set_variable_1, date_offset_1, set_due_date, if/else wie zuvor) ...
  - id: generate_random_number_1
    module: generate_random_number
    params:
      list_name: "tickets"
      min_digits: 4
  - id: set_variable_2
    module: set_variable
    params:
      name: "ticket_nr"
      value: {$ref: generate_random_number_1.number}
  - module: set_description
    params:
      description: {$ref: generate_random_number_1.number}
  - module: add_comment
    params:
      message: "Ticket-Nr: $ticket_nr. Ticket zu '$titel' wurde erfasst."
```

Zwei verschiedene Mechanismen kommen hier absichtlich nebeneinander vor:
`set_description`s Feld ist eine reine Referenz (die Karten-Beschreibung
wird exakt die Nummer, z. B. "0273"), während `add_comment`s Text die
Nummer über die globale Variable `$ticket_nr` in einen vollständigen Satz
einbaut. `set_description`/`set_title`/`set_due_date` usw. ersetzen keine
`$platzhalter` in ihrem Text - nur `add_comment` und `send_email` tun das.

---

## Schritt 6: Die Nummer wieder freigeben

**Erweiterung:** Wird ein Ticket abgeschlossen (die Karte in die Spalte
"Erledigt" verschoben), soll die Ticketnummer wieder freigegeben werden,
damit sie künftig erneut vergeben werden kann.

Dafür ist ein **zweiter, eigenständiger Workflow** nötig - er reagiert auf
ein anderes Event (Verschieben statt Erstellen) und braucht keinen eigenen
Auslöser-Kontext vom ersten Workflow.

### In der Website

**+ Neuer Workflow** (ein zweiter, unabhängig vom bisherigen):

1. **Wo?**: dieselbe Instanz/Board, Spalte jetzt "Erledigt".
2. **Wann?**: Event = `Karte verschoben`.
3. **Was passiert?**: Modul „Zufallszahl entfernen“ (`forget_random_number`), Felder: `list_name` =
   `tickets`, `number` per Referenz von `card`, Feld `description` (dort
   hatte Schritt 5 die Nummer gespeichert).
4. **Workflow speichern**.

### YAML

```yaml
id: ticket-nummer-freigeben
name: Ticket-Nummer freigeben
enabled: true
nextcloud_instance: prod
board_id: 42
trigger:
  event: card_moved
  stack_id: 30   # die Id der Spalte "Erledigt"
actions:
  - module: forget_random_number
    params:
      list_name: "tickets"
      number: {$ref: card.description}
```

**Hinweis:** `{$ref: card.*}` funktioniert bei jedem Event außer
`Karte gelöscht` - eine gelöschte Karte existiert nicht mehr, daher trägt
dieses eine Event keine Kartenfelder. Deshalb liest dieser Workflow
bewusst beim *Verschieben* nach "Erledigt", nicht beim Löschen.

---

## Der Workflow jetzt im Überblick

Nach allen sechs Schritten besteht die Automatisierung aus zwei Workflows:

- **Bei Ticket-Erstellung** (in Spalte "Neu"): Titel in einer Variable
  merken → Eingangs-Kommentar → Fälligkeit in 3 Tagen → je nach Dringlichkeit
  Label + Zuweisung → eindeutige Ticketnummer erzeugen, auf der Karte
  speichern und im Kommentar nennen.
- **Beim Verschieben nach "Erledigt"**: die Ticketnummer wieder freigeben.

Jeder einzelne Schritt für sich war einfach; die Kette ergibt sich daraus,
dass ein Modul das Ergebnis eines anderen per `$ref` oder einer globalen
Variable weiterverwenden kann. Von hier aus lässt sich mit den übrigen
Modulen (`send_email`, `calendar_lookup`, `slice_text`, `extract_field`, ...)
und eigenen Modulen (siehe [MODULE_GUIDE.md](MODULE_GUIDE.md)) beliebig
weitermachen - siehe die vollständige Modul- und Funktionsübersicht in
[automation/README.md](automation/README.md).
