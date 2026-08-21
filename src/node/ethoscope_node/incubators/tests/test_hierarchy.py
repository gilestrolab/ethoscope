"""Tests for the virtual-incubator parenting rules."""

from __future__ import annotations

import pytest

from ethoscope_node.incubators.hierarchy import (
    ROOM,
    children_of,
    effective_location,
    is_virtual,
    normalise_type,
    validate_parent,
)

RECORDS = {
    "Big": {"name": "Big", "type": "normal", "location": "Room 101"},
    "Smart1": {"name": "Smart1", "type": "smart", "location": ""},
    "Box A": {"name": "Box A", "type": "virtual", "parent": "Big"},
    "Box B": {"name": "Box B", "type": "virtual", "parent": ROOM},
}


def lookup(name):
    return RECORDS.get(name)


class TestNormaliseType:
    def test_known_types_pass_through(self):
        assert normalise_type("virtual") == "virtual"
        assert normalise_type("SMART") == "smart"

    def test_unknown_and_empty_fall_back_to_normal(self):
        assert normalise_type("bogus") == "normal"
        assert normalise_type(None) == "normal"

    def test_is_virtual(self):
        assert is_virtual(RECORDS["Box A"])
        assert not is_virtual(RECORDS["Big"])
        assert not is_virtual(None)


class TestValidateParent:
    def test_physical_incubators_never_carry_a_parent(self):
        parent, error = validate_parent(
            "Big", incubator_type="normal", self_name="Other", lookup=lookup
        )
        assert (parent, error) == ("", None)

    def test_virtual_defaults_to_room_when_unspecified(self):
        for requested in (None, "", "   ", "room", ROOM):
            parent, error = validate_parent(
                requested, incubator_type="virtual", self_name="Box C", lookup=lookup
            )
            assert (parent, error) == (ROOM, None)

    def test_virtual_accepts_a_physical_parent(self):
        assert validate_parent(
            "Big", incubator_type="virtual", self_name="Box C", lookup=lookup
        ) == ("Big", None)
        assert validate_parent(
            " Smart1 ", incubator_type="virtual", self_name="Box C", lookup=lookup
        ) == ("Smart1", None)

    def test_unknown_parent_is_rejected_and_falls_back_to_room(self):
        parent, error = validate_parent(
            "Nope", incubator_type="virtual", self_name="Box C", lookup=lookup
        )
        assert parent == ROOM
        assert "no incubator named 'Nope'" in error

    def test_virtual_cannot_nest_inside_another_virtual(self):
        parent, error = validate_parent(
            "Box A", incubator_type="virtual", self_name="Box C", lookup=lookup
        )
        assert parent == ROOM
        assert "itself a virtual incubator" in error

    def test_self_parenting_is_rejected(self):
        parent, error = validate_parent(
            "Box A", incubator_type="virtual", self_name="Box A", lookup=lookup
        )
        assert parent == ROOM
        assert "own parent" in error

    def test_promoting_a_box_to_normal_drops_its_parent(self):
        """The category decided by the patch wins, not the stored one."""
        assert validate_parent(
            "Big", incubator_type="normal", self_name="Box A", lookup=lookup
        ) == ("", None)


class TestChildrenOf:
    def test_lists_only_boxes_with_that_parent(self):
        assert children_of(RECORDS, "Big") == ["Box A"]

    def test_room_and_blank_have_no_children(self):
        assert children_of(RECORDS, ROOM) == []
        assert children_of(RECORDS, "") == []

    def test_unknown_parent_has_no_children(self):
        assert children_of(RECORDS, "Nope") == []


class TestEffectiveLocation:
    def test_physical_reports_its_own_location(self):
        assert effective_location(RECORDS["Big"], lookup) == "Room 101"

    def test_placed_box_reports_parent_and_its_room(self):
        assert effective_location(RECORDS["Box A"], lookup) == "Big (Room 101)"

    def test_placed_box_without_parent_room_reports_just_the_parent(self):
        record = {"name": "Box D", "type": "virtual", "parent": "Smart1"}
        assert effective_location(record, lookup) == "Smart1"

    def test_unplaced_box_falls_back_to_its_own_location_then_room(self):
        assert effective_location(RECORDS["Box B"], lookup) == ROOM
        record = {"type": "virtual", "parent": ROOM, "location": "Bench"}
        assert effective_location(record, lookup) == "Bench"

    def test_dangling_parent_still_names_where_it_was_put(self):
        record = {"name": "Box E", "type": "virtual", "parent": "Deleted"}
        assert effective_location(record, lookup) == "Deleted"


@pytest.mark.parametrize("value", ["Room", "room", "  ROOM  ", "", None])
def test_room_sentinel_is_case_and_space_insensitive(value):
    parent, error = validate_parent(
        value, incubator_type="virtual", self_name="Box C", lookup=lookup
    )
    assert (parent, error) == (ROOM, None)
