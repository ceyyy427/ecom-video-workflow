import copy

import pytest


def row():
    return {
        "index": 1,
        "file": "pour.mp4",
        "seconds": 10,
        "measurement_valid": True,
        "payload": {
            "model": "same-local-model",
            "messages": [{"role": "user", "content": "inspect", "image_sha256": ["a" * 64]}],
            "format": {"type": "object"},
            "options": {"num_ctx": 3072, "num_predict": 512},
        },
    }


def test_elapsed_can_change_but_inputs_are_exact():
    from scripts.check_vision_inputs import compare

    a = row()
    b = copy.deepcopy(a)
    b["seconds"] = 8
    assert compare([a], [b])["exact_request_inputs"]


@pytest.mark.parametrize("field", ["pixels", "schema", "budget", "file", "order", "clock"])
def test_changed_inputs_cannot_pass_as_runtime_only(field):
    from scripts.check_vision_inputs import compare

    a = row()
    b = copy.deepcopy(a)
    if field == "pixels":
        b["payload"]["messages"][0]["image_sha256"] = ["b" * 64]
    elif field == "schema":
        b["payload"]["format"]["required"] = ["x"]
    elif field == "budget":
        b["payload"]["options"]["num_predict"] = 128
    elif field == "file":
        b["file"] = "other.mp4"
    elif field == "order":
        b["index"] = 2
    else:
        b["measurement_valid"] = False
    with pytest.raises(ValueError):
        compare([a], [b])


def test_empty_or_missing_requests_are_not_evidence():
    from scripts.check_vision_inputs import compare

    for a, b in (([], []), ([row()], [])):
        with pytest.raises(ValueError):
            compare(a, b)


@pytest.mark.parametrize("value,changed", [(False, 0), (True, 1)])
def test_json_boolean_and_number_are_distinct(value, changed):
    from scripts.check_vision_inputs import compare

    a = row()
    a["payload"]["format"]["const"] = value
    b = copy.deepcopy(a)
    b["payload"]["format"]["const"] = changed
    with pytest.raises(ValueError):
        compare([a], [b])


@pytest.mark.parametrize("field,value", [("measurement_valid", 1), ("index", True), ("file", None)])
def test_invalid_audit_header_cannot_certify_inputs(field, value):
    from scripts.check_vision_inputs import compare

    a = row()
    a[field] = value
    with pytest.raises(ValueError):
        compare([a], [copy.deepcopy(a)])
