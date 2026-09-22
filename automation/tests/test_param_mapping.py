from __future__ import annotations

from automation.core.domain.engine import _resolve_params, _resolve_ref


def test_literal_values_pass_through_unchanged():
    params = {"a": 1, "b": "text", "c": None, "d": True, "e": [1, "x", {"f": 2}]}

    assert _resolve_params(params, {}) == params


def test_ref_is_resolved_from_a_prior_steps_output():
    outputs = {"step1": {"value": 42}}

    assert _resolve_params({"x": {"$ref": "step1.value"}}, outputs) == {"x": 42}


def test_nested_ref_path_is_resolved():
    outputs = {"step1": {"nested": {"deep": "found"}}}

    assert _resolve_ref("step1.nested.deep", outputs) == "found"


def test_ref_to_a_missing_step_resolves_to_none():
    assert _resolve_ref("missing_step.value", {}) is None


def test_ref_to_a_missing_field_resolves_to_none():
    assert _resolve_ref("step1.missing_field", {"step1": {"value": 1}}) is None


def test_ref_can_appear_nested_inside_dicts_and_lists():
    outputs = {"step1": {"value": "x"}}
    params = {
        "template_data": {"name": {"$ref": "step1.value"}},
        "items": [{"$ref": "step1.value"}, "literal"],
    }

    assert _resolve_params(params, outputs) == {
        "template_data": {"name": "x"},
        "items": ["x", "literal"],
    }


def test_a_dict_with_extra_keys_alongside_ref_is_treated_as_a_literal():
    # only an EXACT {"$ref": "..."} shape is special - anything else, including a
    # dict that happens to also use the key "$ref", is passed through as-is.
    params = {"a": {"$ref": "step1.value", "other": 1}}

    assert _resolve_params(params, {"step1": {"value": 1}}) == params
