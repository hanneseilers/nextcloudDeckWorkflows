from automation import actions_registry
from automation.adapters.actions.loader import ModuleLoader
from automation.main import _modules_snapshot


def test_every_registered_action_has_a_german_label():
    loader = ModuleLoader(actions_registry)
    for name in loader.list_names():
        label = getattr(loader.get(name), "LABEL", "")
        assert label and label != name, f"{name} has no German LABEL"


def test_modules_snapshot_exposes_the_label():
    modules = {m["name"]: m for m in _modules_snapshot()["modules"]}
    assert modules["add_comment"]["label"] == "Kommentar hinzufügen"


def test_every_action_describes_itself_and_names_all_its_fields_in_german():
    loader = ModuleLoader(actions_registry)
    for name in loader.list_names():
        action = loader.get(name)
        assert action.DESCRIPTION, f"{name} has no DESCRIPTION"
        missing = set(action.default_input()) - set(action.PARAM_LABELS)
        assert not missing, f"{name}: no German label for {missing}"
        assert set(action.PARAM_HELP) <= set(action.default_input()), f"{name}: help for unknown fields"
        assert set(action.OUTPUT_LABELS) <= set(action.default_output()), f"{name}: labels for unknown outputs"


def test_snapshot_carries_the_ui_metadata():
    modules = {m["name"]: m for m in _modules_snapshot()["modules"]}
    assert modules["add_comment"]["param_labels"] == {"message": "Kommentar", "text_template": "Textvorlage (optional)"}
    assert modules["move_card"]["param_help"]["order"].startswith("Position")
    assert modules["calculate"]["output_labels"] == {"result": "Ergebnis"}
    assert modules["set_title"]["description"]
