"""Scope changes on an existing connection: omitting project_id must not be read as 'make it global'."""
from app.schemas.integrations import ConnectionUpdate


def test_omitted_project_id_is_distinguishable_from_explicit_null():
    assert "project_id" not in ConnectionUpdate(display_name="x").model_fields_set
    assert "project_id" in ConnectionUpdate.model_validate({"project_id": None}).model_fields_set
    assert ConnectionUpdate.model_validate({"project_id": None}).project_id is None


def test_explicit_project_id_is_parsed():
    pid = "d64a2305-2e08-4b58-b530-18a8770939c2"
    body = ConnectionUpdate.model_validate({"project_id": pid})
    assert str(body.project_id) == pid
