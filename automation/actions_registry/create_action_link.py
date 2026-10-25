from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext

DEFAULT_SUCCESS_MESSAGE = "Die Aktion wurde erfolgreich ausgeführt."

# A link runs one to three actions, in this order. The first pair keeps the names
# links always had, so workflows saved before stay valid.
ACTION_SLOTS = (("action", "action_params"), ("action_2", "action_params_2"), ("action_3", "action_params_3"))


class CreateActionLinkAction(WorkflowAction):
    """Creates a one-time link that, when opened in a browser, runs one to three
    other actions - with the current card, in the context of the workflow the
    link was created in.

    The link points at website/link.php and carries a long random token
    (only its hash is stored). The first visit uses the link up for good:
    opened again - or after it ran - it is invalid. The page shows
    `success_message` if the action worked and a generic error text if it
    failed (details stay in the history). Visiting the link only queues the
    action; it runs on the next `python -m automation.main` invocation,
    which the website tries to start immediately (best effort, see
    website/link.php) - without that, the page says the action was accepted
    and will run with the next cron run.

    `action_params` are resolved ($ref) when the link is *created*, so they
    capture the values at that moment; the link's actions then run against
    the same card (and global variables) as of creation. With up to three
    actions they run in order, one after the other, in one run: a failing one
    doesn't stop the next (the page then shows the error text), the card's
    column carries on from action to action (a move_card first makes the later
    ones act on the new column), and one action cannot use another's output -
    all values are fixed when the link is created. Use it with
    set_variable + add_comment/send_email to hand the link to someone.
    Needs `public_url` in config/settings.yaml (where the website lives).

    params:
      action: str - name of the action module to run (not create_action_link)
      action_params: dict - that action's params, e.g. {"message": "Erledigt"}
      action_2, action_params_2, action_3, action_params_3: optional second and
        third action, the same way (empty action = none)
      success_message: str - text shown on success (empty = default text)
      valid_days: number - how many days from now the link can be used; 0 or
        empty = no expiry. An expired link shows "abgelaufen" and is deleted.
      require_confirmation: bool - show a "Jetzt ausführen" button first
        instead of running on the first GET (protects the link from being
        used up by link-preview/virus-scanner bots; default false)

    output:
      url: str - the one-time link
      expires_at: str | None - expiry as ISO 8601 (UTC), None without expiry
      expires_text: str - expiry for texts, e.g. "31.10.2026 14:05" in the
        configured timezone (settings `timezone`), "unbegrenzt" without
    """

    ACTION_NAME: ClassVar[str] = "create_action_link"
    LABEL: ClassVar[str] = "Einmal-Link erstellen"
    DESCRIPTION: ClassVar[str] = "Erstellt einen Link, der beim ersten Aufruf eine Action für diese Karte ausführt."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"action": "Erste Aktion", "action_params": "Felder der ersten Aktion", "action_2": "Zweite Aktion (optional)", "action_params_2": "Felder der zweiten Aktion", "action_3": "Dritte Aktion (optional)", "action_params_3": "Felder der dritten Aktion", "success_message": "Text bei Erfolg", "valid_days": "Gültig (Tage)", "require_confirmation": "Erst bestätigen lassen"}
    PARAM_HELP: ClassVar[dict[str, str]] = {"action_2": "Bis zu drei Aktionen pro Link. Sie laufen nacheinander; scheitert eine, laufen die anderen trotzdem. Alle Werte stehen beim Erstellen des Links fest - eine Aktion kann nicht das Ergebnis einer anderen nutzen.", "action_params": "Im Editor erscheinen die Felder der gewählten Action direkt im Schritt. In der YAML ein Objekt, z. B. {\"message\": \"Per Link erledigt\"} für „Kommentar hinzufügen“ - Verweise werden beim Erstellen des Links aufgelöst.", "success_message": "Wird nach erfolgreicher Ausführung angezeigt - leer = Standardtext.", "valid_days": "So viele Tage ab Erstellung ist der Link gültig - 0 = unbegrenzt. Das Ablaufdatum gibt der Schritt als „Gültig bis\u201c aus, z. B. für die Mail mit dem Link.", "require_confirmation": "An = die Seite zeigt zuerst einen Button \"Jetzt ausführen\" (schützt den Link vor Link-Vorschau-Bots)."}
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"url": "Link", "expires_text": "Gültig bis", "expires_at": "Gültig bis (ISO-Zeitpunkt)"}

    def default_input(self) -> dict[str, Any]:
        return {
            "action": "", "action_params": {},
            "action_2": "", "action_params_2": {}, "action_3": "", "action_params_3": {},
            "success_message": "", "valid_days": 7,
            "require_confirmation": False,
        }

    def default_output(self) -> dict[str, Any]:
        return {"url": "", "expires_at": None, "expires_text": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        if context.link_store is None:
            raise RuntimeError("create_action_link: no link store available for this run")
        if not context.public_url:
            raise ValueError("create_action_link: set `public_url` in config/settings.yaml (where the website lives)")

        steps = []
        for number, (action_key, params_key) in enumerate(ACTION_SLOTS, start=1):
            module = str(params.get(action_key) or "").strip()
            if not module:
                if number == 1:
                    raise ValueError("create_action_link: `action` is required")
                continue  # an unused second/third action
            if module == self.ACTION_NAME:
                raise ValueError("create_action_link: a link cannot run create_action_link itself")
            context.modules.get(module)  # raises UnknownActionError for an unknown action - fail at creation, not on click
            action_params = params.get(params_key) or {}
            if not isinstance(action_params, dict):
                raise ValueError(f"create_action_link: `{params_key}` must be an object")
            steps.append({"module": module, "params": action_params})

        expires_at = None
        expires_text = "unbegrenzt"
        raw_days = params.get("valid_days")
        days = float(raw_days) if raw_days not in (None, "") else 0.0
        if days < 0:
            raise ValueError("create_action_link: `valid_days` must not be negative")
        if days > 0:
            moment = (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0)
            expires_at = moment.isoformat()
            expires_text = _format_local(moment, context.display_timezone)

        token = context.link_store.create_link(
            workflow_id=context.workflow_id,
            event=context.event,
            current_stack_id=context.current_stack_id,
            module=steps[0]["module"],
            params=steps[0]["params"],
            extra_steps=steps[1:],
            variables=dict(context.variables),
            success_message=(params.get("success_message") or "").strip() or DEFAULT_SUCCESS_MESSAGE,
            require_confirmation=bool(params.get("require_confirmation")),
            expires_at=expires_at,
        )
        return {
            "url": f"{context.public_url.rstrip('/')}/link.php?h={token}",
            "expires_at": expires_at,
            "expires_text": expires_text,
        }


def _format_local(moment: datetime, timezone_name: str) -> str:
    """"31.10.2026 14:05" in the configured timezone - UTC if that timezone
    isn't known on this system (no tz database)."""

    try:
        from zoneinfo import ZoneInfo

        moment = moment.astimezone(ZoneInfo(timezone_name))
    except Exception:
        return moment.strftime("%d.%m.%Y %H:%M") + " UTC"
    return moment.strftime("%d.%m.%Y %H:%M")
