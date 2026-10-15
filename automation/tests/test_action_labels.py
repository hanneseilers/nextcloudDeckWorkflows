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
