from automation.adapters.nextcloud.deck_gateway import DECK_API, NextcloudDeckGateway


class RecordingClient:
    def __init__(self, card=None):
        self.calls = []
        self._card = card or {}

    def get(self, path, params=None):
        self.calls.append(("GET", path, None))
        return self._card

    def put(self, path, json=None):
        self.calls.append(("PUT", path, json))

    def post(self, path, json=None):
        self.calls.append(("POST", path, json))


def test_add_label_uses_assign_label_endpoint_with_body():
    client = RecordingClient()
    NextcloudDeckGateway(client).add_label(12, 46, 93, 50)
    assert client.calls == [
        ("PUT", f"{DECK_API}/boards/12/stacks/46/cards/93/assignLabel", {"labelId": 50})
    ]


def test_update_keeps_type_owner_and_order():
    card = {"title": "T", "type": "plain", "owner": {"uid": "anna"}, "order": 3,
            "description": "D", "duedate": None}
    client = RecordingClient(card)
    NextcloudDeckGateway(client).set_title(1, 2, 3, "Neu")
    _, path, payload = client.calls[-1]
    assert path == f"{DECK_API}/boards/1/stacks/2/cards/3"
    assert payload == {"title": "Neu", "type": "plain", "owner": "anna", "order": 3,
                       "description": "D", "duedate": None}


def test_add_comment_uses_decks_ocs_comments_endpoint():
    client = RecordingClient()
    NextcloudDeckGateway(client).add_comment(93, "Hallo")
    assert client.calls == [
        ("POST", "/ocs/v2.php/apps/deck/api/v1.0/cards/93/comments", {"message": "Hallo"})
    ]


def test_overlong_comment_is_shortened_to_decks_limit():
    client = RecordingClient()
    NextcloudDeckGateway(client).add_comment(1, "x" * 1500)
    message = client.calls[0][2]["message"]
    assert len(message) == 1000 and message.endswith("…")


def test_overlong_title_is_shortened_instead_of_failing_with_400():
    client = RecordingClient({"title": "alt"})
    NextcloudDeckGateway(client).set_title(1, 2, 3, "t" * 300)
    assert len(client.calls[-1][2]["title"]) == 255
