from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext

DEFAULT_SUCCESS_MESSAGE = "Die Aktion wurde erfolgreich ausgeführt."


class CreateActionLinkAction(WorkflowAction):
    """Creates a one-time link that, when opened in a browser, runs any other
    action - with the current card, in the context of the workflow the link
    was created in.

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
    capture the values at that moment; the link's action then runs against
    the same card (and global variables) as of creation. Use it with
    set_variable + add_comment/send_email to hand the link to someone.
    Needs `public_url` in config/settings.yaml (where the website lives).

    params:
      action: str - name of the action module to run (not create_action_link)
      action_params: dict - that action's params, e.g. {"message": "Erledigt"}
      success_message: str - text shown on success (empty = default text)
      require_confirmation: bool - show a "Jetzt ausführen" button first
        instead of running on the first GET (protects the link from being
        used up by link-preview/virus-scanner bots; default false)

    output:
      url: str - the one-time link
    """

    ACTION_NAME: ClassVar[str] = "create_action_link"
    LABEL: ClassVar[str] = "Einmal-Link erstellen"
    DESCRIPTION: ClassVar[str] = "Erstellt einen Link, der beim ersten Aufruf eine Action für diese Karte ausführt."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"action": "Auszuführende Action", "action_params": "Felder der Action", "success_message": "Text bei Erfolg", "require_confirmation": "Erst bestätigen lassen"}
    PARAM_HELP: ClassVar[dict[str, str]] = {"action_params": "Beispiel für \"Kommentar hinzufügen\": {\"message\": \"Per Link erledigt\"} - Referenzen werden beim Erstellen des Links aufgelöst.", "success_message": "Wird nach erfolgreicher Ausführung angezeigt - leer = Standardtext.", "require_confirmation": "An = die Seite zeigt zuerst einen Button \"Jetzt ausführen\" (schützt den Link vor Link-Vorschau-Bots)."}
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"url": "Link"}

    def default_input(self) -> dict[str, Any]:
        return {"action": "", "action_params": {}, "success_message": "", "require_confirmation": False}

    def default_output(self) -> dict[str, Any]:
        return {"url": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        if context.link_store is None:
            raise RuntimeError("create_action_link: no link store available for this run")
        if not context.public_url:
            raise ValueError("create_action_link: set `public_url` in config/settings.yaml (where the website lives)")

        module = (params.get("action") or "").strip()
        if not module:
            raise ValueError("create_action_link: `action` is required")
        if module == self.ACTION_NAME:
            raise ValueError("create_action_link: a link cannot run create_action_link itself")
        context.modules.get(module)  # raises UnknownActionError for an unknown action - fail at creation, not on click

        action_params = params.get("action_params") or {}
        if not isinstance(action_params, dict):
            raise ValueError("create_action_link: `action_params` must be an object")

        token = context.link_store.create_link(
            workflow_id=context.workflow_id,
            event=context.event,
            current_stack_id=context.current_stack_id,
            module=module,
            params=action_params,
            variables=dict(context.variables),
            success_message=(params.get("success_message") or "").strip() or DEFAULT_SUCCESS_MESSAGE,
            require_confirmation=bool(params.get("require_confirmation")),
        )
        return {"url": f"{context.public_url.rstrip('/')}/link.php?h={token}"}
