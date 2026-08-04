import pytest

from mesa_legal_data.pipeline import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransition,
    transition_state,
)


def test_valid_transitions():
    assert transition_state("discovered", "fetched") == "fetched"
    assert transition_state("discovered", "failed") == "failed"

    assert transition_state("privacy_pending", "needs_review") == "needs_review"
    assert transition_state("needs_review", "approved") == "approved"
    assert transition_state("approved", "released") == "released"


def test_invalid_transitions():
    with pytest.raises(InvalidStateTransition):
        transition_state("discovered", "transport_verified")

    with pytest.raises(InvalidStateTransition):
        transition_state("approved", "failed")

    with pytest.raises(InvalidStateTransition):
        transition_state("released", "approved")


def test_unknown_state():
    with pytest.raises(InvalidStateTransition):
        transition_state("unknown_state", "fetched")


def test_all_keys_have_values():
    for transitions in ALLOWED_TRANSITIONS.values():
        assert isinstance(transitions, set)
