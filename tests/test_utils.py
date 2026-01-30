"""Tests for utility functions."""

import datetime
from utils import sanitize_name, make_group_name, now_iso, set_condition


class TestSanitizeName:
    """Tests for sanitize_name function."""

    def test_lowercase(self):
        assert sanitize_name("MyProject") == "myproject"

    def test_dots_to_hyphens(self):
        assert sanitize_name("my.project.com") == "my-project-com"

    def test_underscores_to_hyphens(self):
        assert sanitize_name("my_project_name") == "my-project-name"

    def test_removes_special_chars(self):
        assert sanitize_name("my@project!name") == "myprojectname"

    def test_collapses_multiple_hyphens(self):
        assert sanitize_name("my--project") == "my-project"
        assert sanitize_name("my...project") == "my-project"

    def test_strips_leading_trailing_hyphens(self):
        assert sanitize_name("-project-") == "project"
        assert sanitize_name("...project...") == "project"

    def test_complex_example(self):
        assert sanitize_name("My_Project.Example.COM") == "my-project-example-com"


class TestMakeGroupName:
    """Tests for make_group_name function."""

    def test_appends_users_suffix(self):
        assert make_group_name("my-project") == "my-project-users"

    def test_sanitizes_input(self):
        assert make_group_name("My_Project.COM") == "my-project-com-users"


class TestNowIso:
    """Tests for now_iso function."""

    def test_returns_iso_format(self):
        result = now_iso()
        # Should be parseable as ISO format
        parsed = datetime.datetime.fromisoformat(result)
        assert parsed is not None

    def test_returns_utc(self):
        result = now_iso()
        parsed = datetime.datetime.fromisoformat(result)
        assert parsed.tzinfo is not None


class TestSetCondition:
    """Tests for set_condition function."""

    def test_adds_new_condition(self):
        status: dict = {}
        set_condition(status, "Ready", "True", "Completed", "All done")

        assert len(status["conditions"]) == 1
        assert status["conditions"][0]["type"] == "Ready"
        assert status["conditions"][0]["status"] == "True"
        assert status["conditions"][0]["reason"] == "Completed"
        assert status["conditions"][0]["message"] == "All done"
        assert "lastTransitionTime" in status["conditions"][0]

    def test_updates_existing_condition(self):
        status: dict = {
            "conditions": [
                {
                    "type": "Ready",
                    "status": "False",
                    "reason": "Pending",
                    "message": "",
                    "lastTransitionTime": "2024-01-01T00:00:00+00:00",
                }
            ]
        }
        set_condition(status, "Ready", "True", "Completed", "Done")

        assert len(status["conditions"]) == 1
        assert status["conditions"][0]["status"] == "True"
        assert status["conditions"][0]["reason"] == "Completed"
        # Transition time should be updated since status changed
        assert status["conditions"][0]["lastTransitionTime"] != "2024-01-01T00:00:00+00:00"

    def test_preserves_transition_time_if_status_unchanged(self):
        original_time = "2024-01-01T00:00:00+00:00"
        status: dict = {
            "conditions": [
                {
                    "type": "Ready",
                    "status": "True",
                    "reason": "Completed",
                    "message": "Done",
                    "lastTransitionTime": original_time,
                }
            ]
        }
        set_condition(status, "Ready", "True", "StillComplete", "Still done")

        assert status["conditions"][0]["lastTransitionTime"] == original_time
        assert status["conditions"][0]["reason"] == "StillComplete"

    def test_multiple_conditions(self):
        status: dict = {}
        set_condition(status, "Ready", "True", "", "")
        set_condition(status, "NetworkReady", "False", "Pending", "")

        assert len(status["conditions"]) == 2
        types = {c["type"] for c in status["conditions"]}
        assert types == {"Ready", "NetworkReady"}
