"""Unit Tests for Pydantic Schemas & Prohibited Metadata Validation."""

import pytest
from pydantic import ValidationError
from api.app.schemas.event import SingleEventSchema


def test_valid_event_schema_instantiation():
    """Verify that a compliant event payload passes validation."""
    event = SingleEventSchema(
        event_name="page_view",
        page_path="/products/view",
        metadata={"theme": "dark", "tab": "reviews"},
    )
    assert event.event_name == "page_view"
    assert event.page_path == "/products/view"
    assert event.metadata["theme"] == "dark"


@pytest.mark.parametrize("prohibited_key", ["vin", "VIN", "chat_message", "password", "token", "ssn", "credit_card"])
def test_prohibited_metadata_fields_raise_validation_error(prohibited_key: str):
    """Verify that payloads with prohibited PII or sensitive keys are strictly rejected."""
    with pytest.raises(ValidationError) as exc_info:
        SingleEventSchema(
            event_name="form_submit",
            page_path="/contact",
            metadata={"user_name": "Alice", prohibited_key: "forbidden_value_123"},
        )
    assert "Prohibited telemetry fields detected in metadata" in str(exc_info.value)
