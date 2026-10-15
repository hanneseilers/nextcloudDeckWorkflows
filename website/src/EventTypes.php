<?php

namespace NextcloudDeckWorkflows;

/**
 * The same EventType values automation/core/domain/models.py defines, with
 * their German display labels - shared between new.php (event picker) and
 * history.php (showing which event a logged run reacted to).
 */
class EventTypes
{
    /**
     * card_assigned/card_due_date_changed/card_description_changed fire *in
     * addition to* card_updated when that specific field changed -
     * card_updated itself still fires on any change.
     *
     * @return array<string, string>
     */
    public static function labels(): array
    {
        return [
            'card_created' => 'Karte erstellt',
            'card_moved' => 'Karte verschoben',
            'card_assigned' => 'Neue Person zugewiesen',
            'card_due_date_changed' => 'Fälligkeitsdatum geändert',
            'card_description_changed' => 'Beschreibung geändert',
            'card_label_changed' => 'Label geändert',
            'card_updated' => 'Karte geändert (beliebiges Feld)',
            'card_deleted' => 'Karte gelöscht',
        ];
    }

    public static function label(string $eventType): string
    {
        return self::labels()[$eventType] ?? $eventType;
    }
}
