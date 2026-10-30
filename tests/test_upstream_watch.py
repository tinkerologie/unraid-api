"""Tests for the upstream watcher in script/upstream_watch.py."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import schema_tools as st
import upstream_watch as uw

FIXTURES = Path(__file__).parent / "fixtures" / "upstream"
GITHUB = json.loads((FIXTURES / "github.json").read_text())
SDL_OLD = (FIXTURES / "v4.37.6.graphql").read_text()
SDL_NEW = (FIXTURES / "v4.37.9.graphql").read_text()
MAIN_SHA = "0123456789abcdef" * 2 + "01234567"  # a fake 40-hex commit SHA
REPO = "tinkerologie/unraid-api"

EXPECTED_METHODS = {
    "typed_get_containers",
    "typed_get_containers_safe",
    "get_containers",
    "typed_get_vms",
    "get_vms",
    "get_container_update_statuses",
    "get_docker_port_conflicts",
    "get_docker_networks",
    "typed_get_docker_networks",
    "get_container_logs",
    "typed_get_container_logs",
    "get_docker_organizer",
    "typed_get_docker_organizer",
}


class FakeGitHub:
    """Serve GitHub REST and raw schema URLs from in-memory fixtures."""

    def __init__(
        self,
        releases: list[dict[str, Any]] | None = None,
        schemas: dict[str, str] | None = None,
        issues: list[dict[str, Any]] | None = None,
        main_sha: str = MAIN_SHA,
    ) -> None:
        self.releases = copy.deepcopy(
            GITHUB["releases"] if releases is None else releases
        )
        self.pulls: dict[str, Any] = copy.deepcopy(GITHUB["pulls"])
        self.schemas = (
            {
                "v4.37.6": SDL_OLD,
                "v4.37.7": SDL_OLD,
                "v4.37.8": SDL_NEW,
                "v4.37.9": SDL_NEW,
                MAIN_SHA: SDL_NEW,
            }
            if schemas is None
            else schemas
        )
        self.issues = issues or []
        self.main_sha = main_sha
        self.urls: list[str] = []
        self.pull_errors: dict[str, Exception] = {}

    @staticmethod
    def _page(items: list[Any], url: str) -> bytes:
        page = int(url.rsplit("page=", 1)[1])
        start = (page - 1) * uw.PER_PAGE
        return json.dumps(items[start : start + uw.PER_PAGE]).encode()

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        api = "https://api.github.com/repos/"
        raw = "https://raw.githubusercontent.com/unraid/api/"
        if url.startswith(f"{api}unraid/api/releases?"):
            return self._page(self.releases, url)
        if url.startswith(f"{api}{REPO}/issues?state=all"):
            return self._page(self.issues, url)
        if url == f"{api}unraid/api/commits/main":
            return json.dumps({"sha": self.main_sha}).encode()
        if url.startswith(f"{api}unraid/api/pulls/"):
            number = url.rsplit("/", 1)[1]
            if number in self.pull_errors:
                raise self.pull_errors[number]
            if number in self.pulls:
                return json.dumps(self.pulls[number]).encode()
        if url.startswith(raw):
            ref = url[len(raw) :].split("/", 1)[0]
            if ref in self.schemas:
                return self.schemas[ref].encode()
        raise st.NotFoundError(url, 404, "Not Found")

    def file_issues(self, report: dict[str, Any], login: str = uw.BOT_LOGIN) -> None:
        """Create the report's issues and state issue as the report job would."""
        for payload in report["issues"]:
            self.issues.insert(
                0,
                {
                    "number": len(self.issues) + 1,
                    "title": payload["title"],
                    "body": payload["body"],
                    "state": "closed",
                    "user": {"login": login},
                },
            )
        state = report["state"]
        self.issues.insert(
            0,
            {
                "number": len(self.issues) + 1,
                "title": uw.STATE_TITLE,
                "body": (
                    f"<!-- upstream-release: {state['upstream_release']} -->\n"
                    f"<!-- upstream-main: {state['upstream_main']} -->"
                ),
                "state": "closed",
                "user": {"login": login},
            },
        )


def _entry(report: dict[str, Any], key: str) -> dict[str, Any]:
    return next(e for e in report["entries"] if e["key"] == key)


def _change(entry: dict[str, Any], coordinate: str) -> dict[str, Any]:
    return next(c for c in entry["changes"] if c["coordinate"] == coordinate)


class TestAcceptance:
    def test_v4376_to_v4379_reports_nullable_roots_and_introspection(self) -> None:
        report = uw.scan(FakeGitHub(), REPO, since="v4.37.6", until="v4.37.9")

        assert report["range"]["since"] == "v4.37.6"
        assert report["range"]["releases"] == ["v4.37.7", "v4.37.8", "v4.37.9"]
        assert _entry(report, "v4.37.7")["changes"] == []

        step = _entry(report, "v4.37.8")
        docker = _change(step, "Query.docker")
        vms = _change(step, "Query.vms")
        assert docker["classification"] == vms["classification"] == "bug"
        assert docker["kind"] == "field_nullable"
        assert (docker["before"], docker["after"]) == ("Docker!", "Docker")
        assert set(docker["methods"]) | set(vms["methods"]) == EXPECTED_METHODS
        assert all(loc.startswith(st.CLIENT_PATH) for loc in docker["locations"])

        notes = {n["source"]: n for n in step["behaviour_notes"]}
        assert "introspection" in notes["unraid/api#2095"]["rules"]
        assert notes["release notes"]["rules"] == ["sandbox"]
        assert "unraid/api#2123" not in notes
        assert [pr["number"] for pr in step["pull_requests"]] == [2123, 2095, 2126]
        later = _entry(report, "v4.37.9")["behaviour_notes"]
        assert [n["source"] for n in later] == ["unraid/api#2129"]
        assert "introspection" in later[0]["rules"]

        issues = {issue["group"]: issue for issue in report["issues"]}
        assert set(issues) == {"v4.37.8:bug", "v4.37.9:bug"}
        bug = issues["v4.37.8:bug"]
        assert bug["labels"] == ["bug", "upstream"]
        assert bug["title"] == "[Bug]: Upstream unraid/api v4.37.8: breaking changes"
        assert bug["body"].startswith("<!-- upstream-group: v4.37.8:bug -->\n")
        assert "<!-- upstream-release: v4.37.8 -->" in bug["body"]
        assert (
            "<!-- upstream-change: field_nullable:Query.docker:Docker!..Docker -->"
            in bug["body"]
        )
        assert "## Behaviour changes" in bug["body"]
        assert "`typed_get_containers_safe`" in bug["body"]
        assert "field_nullable:Query.vms:Vms!..Vms" in bug["change_ids"]
        behaviour_only = issues["v4.37.9:bug"]
        assert behaviour_only["title"].endswith("behaviour changes to review")
        assert behaviour_only["change_ids"] == ["behaviour:v4.37.9:pr-2129"]

        assert report["state"] == {
            "upstream_release": "v4.37.9",
            "upstream_main": MAIN_SHA,
        }
        summary = report["summary_markdown"]
        assert "## v4.37.7 (vs v4.37.6)" in summary
        assert "No schema changes." in summary
        assert "## main@0123456 (vs v4.37.9)" in summary
        assert "[Bug]: Upstream unraid/api v4.37.8: breaking changes" in summary


class TestDeduplication:
    def test_rerun_with_markers_in_closed_issues_opens_nothing(self) -> None:
        github = FakeGitHub()
        first = uw.scan(github, REPO, since="v4.37.6", until="v4.37.9")
        github.file_issues(first)

        again = uw.scan(github, REPO, since="v4.37.6", until="v4.37.9")
        assert again["issues"] == []
        docker = _change(_entry(again, "v4.37.8"), "Query.docker")
        assert isinstance(docker["already_reported"], int)
        assert (
            f"already reported in #{docker['already_reported']}"
            in (again["summary_markdown"])
        )

        default = uw.scan(github, REPO)
        assert default["range"]["recorded_release"] == "v4.37.9"
        assert default["range"]["recorded_main"] == MAIN_SHA
        assert default["range"]["releases"] == []
        assert default["issues"] == []
        assert "none new" in default["summary_markdown"]

    def test_markers_from_other_authors_are_ignored(self) -> None:
        github = FakeGitHub()
        first = uw.scan(github, REPO, since="v4.37.6", until="v4.37.9")
        github.file_issues(first, login="someone")

        again = uw.scan(github, REPO, since="v4.37.6", until="v4.37.9")
        assert len(again["issues"]) == len(first["issues"])
        assert again["range"]["recorded_release"] is None

    def test_group_marker_suppresses_its_group(self) -> None:
        github = FakeGitHub()
        github.issues = [
            {
                "number": 7,
                "title": "manual",
                "body": "<!-- upstream-group: v4.37.8:bug -->",
                "state": "open",
                "user": {"login": uw.BOT_LOGIN},
            }
        ]
        report = uw.scan(github, REPO, since="v4.37.6", until="v4.37.9")
        assert [i["group"] for i in report["issues"]] == ["v4.37.9:bug"]

    def test_main_change_is_not_reported_again_when_released(self) -> None:
        unreleased = [r for r in GITHUB["releases"] if r["tag_name"] not in {"v4.37.9"}]
        schemas = {
            "v4.37.6": SDL_OLD,
            "v4.37.7": SDL_OLD,
            "v4.37.8": SDL_OLD,
            MAIN_SHA: SDL_NEW,
        }
        github = FakeGitHub(releases=unreleased, schemas=schemas)
        first = uw.scan(github, REPO)
        assert first["range"]["since"] == "v4.37.7"
        groups = [issue["group"] for issue in first["issues"]]
        assert "main@0123456:bug" in groups
        main_bug = next(i for i in first["issues"] if i["group"] == "main@0123456:bug")
        assert f"<!-- upstream-main: {MAIN_SHA} -->" in main_bug["body"]
        assert main_bug["title"].startswith("[Bug]: Upstream unraid/api main@0123456")
        github.file_issues(first)

        released_sha = "f" * 40
        github.releases.insert(0, copy.deepcopy(GITHUB["releases"][0]))
        github.schemas["v4.37.9"] = SDL_NEW
        github.schemas[released_sha] = SDL_NEW
        github.main_sha = released_sha
        second = uw.scan(github, REPO)
        assert second["range"]["since"] == "v4.37.8"
        assert second["range"]["releases"] == ["v4.37.9"]
        docker = _change(_entry(second, "v4.37.9"), "Query.docker")
        assert docker["already_reported"] is not None
        assert [i["group"] for i in second["issues"]] == ["v4.37.9:bug"]
        assert all("Query" not in cid for cid in second["issues"][0]["change_ids"])

    def test_pagination_skips_pull_requests(self) -> None:
        pull_requests = [
            {
                "number": 1000 + n,
                "title": "pr",
                "body": "<!-- upstream-release: v9.9.9 -->",
                "pull_request": {},
                "user": {"login": uw.BOT_LOGIN},
            }
            for n in range(uw.PER_PAGE)
        ]
        state = {
            "number": 1,
            "title": uw.STATE_TITLE,
            "body": "<!-- upstream-release: v4.37.8 -->",
            "user": {"login": uw.BOT_LOGIN},
        }
        github = FakeGitHub(issues=[*pull_requests, state])
        markers = uw.read_markers(github, REPO)
        assert markers.release == "v4.37.8"
        assert markers.main is None
        issue_pages = [u for u in github.urls if "/issues?" in u]
        assert [u.rsplit("page=", 1)[1] for u in issue_pages] == ["1", "2"]
        assert "search" not in " ".join(github.urls)

    def test_cursor_comes_only_from_the_state_issue(self) -> None:
        sha = "ab" * 20
        finding = {
            "number": 9,
            "title": "[Bug]: Upstream unraid/api v4.37.9: breaking changes",
            "body": (
                "<!-- upstream-group: v4.37.9:bug -->\n"
                "<!-- upstream-release: v4.37.9 -->\n"
                f"<!-- upstream-main: {sha} -->\n"
                "<!-- upstream-change: field_removed:A.b -->"
            ),
            "user": {"login": uw.BOT_LOGIN},
        }
        states = [
            {
                "number": n,
                "title": uw.STATE_TITLE,
                "body": f"<!-- upstream-release: {tag} -->",
                "user": {"login": uw.BOT_LOGIN},
            }
            for n, tag in ((1, "v4.37.7"), (2, "v4.37.6"))
        ]
        markers = uw.read_markers(FakeGitHub(issues=[finding, *states]), REPO)
        # Finding markers still deduplicate, but never move the cursor.
        assert markers.release == "v4.37.7"
        assert markers.main is None
        assert markers.changes == {"field_removed:A.b": 9}
        assert markers.groups == {"v4.37.9:bug": 9}

    def test_report_job_failure_before_state_update_does_not_skip(self) -> None:
        github = FakeGitHub()
        first = uw.scan(github, REPO, since="v4.37.7", until="v4.37.8")
        # Simulate a report job that created only the first issue, then died
        # before recording state: the next default run must still cover it.
        github.issues = [
            {
                "number": 1,
                "title": first["issues"][0]["title"],
                "body": first["issues"][0]["body"],
                "user": {"login": uw.BOT_LOGIN},
            }
        ]
        again = uw.scan(github, REPO)
        assert again["range"]["recorded_release"] is None
        assert again["range"]["since"] == "v4.37.8"
        assert [i["group"] for i in again["issues"]] == ["v4.37.9:bug"]


class TestRange:
    @pytest.mark.parametrize(
        ("since", "until", "message"),
        [
            ("4.37.6", None, "is not a release tag"),
            (None, "v4.37.9; rm", "is not a release tag"),
            ("v9.9.9", None, "is not a published unraid/api release"),
            ("v4.38.0-beta.1", None, "is not a release tag"),
            ("v4.37.10", None, "is not a published"),
            ("v4.37.9", "v4.37.7", "is newer than"),
        ],
    )
    def test_invalid_and_missing_tags_fail(
        self, since: str | None, until: str | None, message: str
    ) -> None:
        with pytest.raises(uw.ScanError, match=message):
            uw.scan(FakeGitHub(), REPO, since=since, until=until)

    def test_releases_skip_drafts_prereleases_and_bad_tags(self) -> None:
        releases = [*GITHUB["releases"], {"tag_name": "nightly", "html_url": "u"}]
        tags = [r.tag for r in uw.list_releases(FakeGitHub(releases=releases))]
        assert tags == ["v4.37.6", "v4.37.7", "v4.37.8", "v4.37.9"]

    def test_release_pagination(self) -> None:
        releases = [
            {"tag_name": f"v1.0.{n}", "html_url": "u", "body": ""}
            for n in range(uw.PER_PAGE + 5)
        ]
        github = FakeGitHub(releases=releases)
        assert len(uw.list_releases(github)) == uw.PER_PAGE + 5
        assert uw.list_releases(github)[-1].tag == f"v1.0.{uw.PER_PAGE + 4}"

    def test_no_releases(self) -> None:
        with pytest.raises(uw.ScanError, match="no published releases"):
            uw.scan(FakeGitHub(releases=[]), REPO)

    def test_until_only_uses_recorded_release(self) -> None:
        releases = uw.list_releases(FakeGitHub())
        chain = uw.resolve_range(releases, "v4.37.6", None, "v4.37.8")
        assert [r.tag for r in chain] == ["v4.37.6", "v4.37.7", "v4.37.8"]
        chain = uw.resolve_range(releases, "v4.37.9", None, "v4.37.8")
        assert [r.tag for r in chain] == ["v4.37.7", "v4.37.8"]
        chain = uw.resolve_range(releases, None, "v4.37.8", None)
        assert [r.tag for r in chain] == ["v4.37.8", "v4.37.9"]

    def test_single_release_has_no_steps(self) -> None:
        github = FakeGitHub(releases=[GITHUB["releases"][-1]])
        report = uw.scan(github, REPO)
        assert report["range"]["releases"] == []
        assert [e["kind"] for e in report["entries"]] == ["main"]

    def test_recorded_newer_release_is_kept(self) -> None:
        github = FakeGitHub()
        github.issues = [
            {
                "number": 1,
                "title": uw.STATE_TITLE,
                "body": "<!-- upstream-release: v4.37.9 -->",
                "user": {"login": uw.BOT_LOGIN},
            }
        ]
        report = uw.scan(github, REPO, since="v4.37.6", until="v4.37.7")
        assert report["state"]["upstream_release"] == "v4.37.9"

    def test_invalid_repo_and_main_sha(self) -> None:
        with pytest.raises(uw.ScanError, match="Invalid repository"):
            uw.scan(FakeGitHub(), "not a repo")
        with pytest.raises(uw.ScanError, match="Unexpected upstream main SHA"):
            uw.scan(FakeGitHub(main_sha="main"), REPO)


class TestSchemaSteps:
    def test_missing_schema_file_is_reported_unavailable(self) -> None:
        schemas = {"v4.37.6": SDL_OLD, "v4.37.8": SDL_NEW, "v4.37.9": SDL_NEW}
        report = uw.scan(
            FakeGitHub(schemas=schemas), REPO, since="v4.37.6", until="v4.37.9"
        )
        for key in ("v4.37.7", "v4.37.8"):
            entry = _entry(report, key)
            assert entry["schema_status"] == "unavailable"
            assert entry["missing_schema"] == ["v4.37.7"]
            assert entry["changes"] == []
        assert _entry(report, "main@0123456")["missing_schema"] == [MAIN_SHA]
        assert (
            "Schema unavailable at v4.37.7; diff skipped."
            in (report["summary_markdown"])
        )

    def test_new_validation_failures_and_removed_selections_are_bugs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "lib.py").write_text(
            "class Client:\n"
            "    def get_thing(self):\n"
            '        return "query { thing { a b } }"\n'
        )

        def fake_inventory(schema: Any) -> st.Inventory:
            return st.build_inventory(
                schema, root=tmp_path, sources=("lib.py",), registry=()
            )

        monkeypatch.setattr(uw, "build_inventory", fake_inventory)
        old = "type Query { thing: Thing }\ntype Thing { a: Int b: Int }"
        new = "type Query { thing: Thing other: Int }\ntype Thing { a: Int }"
        schemas = {"v4.37.6": old, "v4.37.7": new, MAIN_SHA: new}
        releases = [r for r in GITHUB["releases"] if r["tag_name"] <= "v4.37.7"]
        report = uw.scan(FakeGitHub(releases=releases, schemas=schemas), REPO)

        entry = _entry(report, "v4.37.7")
        removed = _change(entry, "Thing.b")
        assert removed["classification"] == "bug"
        assert removed["methods"] == ["get_thing"]
        assert removed["locations"] == ["lib.py:3"]
        invalid = next(c for c in entry["changes"] if c["kind"] == "validation_error")
        assert invalid["classification"] == "bug"
        assert invalid["detail"].startswith("Cannot query field 'b' on type 'Thing'.")
        assert invalid["id"].startswith("validation_error:get_thing:")
        added = _change(entry, "Query.other")
        assert added["classification"] == "enhancement"

        groups = {issue["group"]: issue for issue in report["issues"]}
        bug = groups["v4.37.7:bug"]["body"]
        assert "## Breaking schema changes" in bug
        assert "## Operations that no longer validate" in bug
        enhancement = groups["v4.37.7:enhancement"]
        assert enhancement["labels"] == ["enhancement", "upstream"]
        assert "`Query.other`: root field added" in enhancement["body"]
        assert enhancement["title"] == (
            "[Enhancement]: Upstream unraid/api v4.37.7: new schema surface"
        )


class TestInputBreakage:
    OLD = (
        "type Query { a: Int }\n"
        "type Mutation {\n"
        "  updateTemperatureConfig(input: TemperatureConfigInput!): Int\n"
        "}\n"
        "input TemperatureConfigInput {\n"
        "  enabled: Boolean sensor: SensorInput unit: Unit retype: Int\n"
        "  forced: Boolean! = false\n"
        "}\n"
        "input SensorInput { id: ID }\n"
        "enum Unit { C F }\n"
        "input Unused { x: Int z: Int! = 1 }\n"
        "enum Mode { A B }\n"
    )
    NEW = (
        "type Query { a: Int }\n"
        "type Mutation {\n"
        "  updateTemperatureConfig(input: TemperatureConfigInput!): Int\n"
        "}\n"
        "input TemperatureConfigInput {\n"
        "  sensor: SensorInput unit: Unit retype: String\n"
        "  forced: Boolean!\n"
        "}\n"
        "input SensorInput { id: ID required: Int! optional: Int! = 1 }\n"
        "enum Unit { C }\n"
        "input Unused { y: Int z: Int! }\n"
        "enum Mode { A }\n"
    )

    def test_input_changes_on_sent_types_are_breaking(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "lib.py").write_text(
            "class Client:\n"
            "    def update_temperature_config(self):\n"
            '        return """mutation ($input: TemperatureConfigInput!) {\n'
            "            updateTemperatureConfig(input: $input)\n"
            '        }"""\n'
        )

        def fake_inventory(schema: Any) -> st.Inventory:
            return st.build_inventory(
                schema, root=tmp_path, sources=("lib.py",), registry=()
            )

        monkeypatch.setattr(uw, "build_inventory", fake_inventory)
        schemas = {"v4.37.6": self.OLD, "v4.37.7": self.NEW, MAIN_SHA: self.NEW}
        releases = [r for r in GITHUB["releases"] if r["tag_name"] <= "v4.37.7"]
        report = uw.scan(FakeGitHub(releases=releases, schemas=schemas), REPO)
        entry = _entry(report, "v4.37.7")
        result = {c["coordinate"]: c["classification"] for c in entry["changes"]}
        assert result == {
            "TemperatureConfigInput.enabled": "bug",
            "TemperatureConfigInput.retype": "bug",
            "SensorInput.required": "bug",
            "SensorInput.optional": "no_action",
            "Unit.F": "bug",
            "Unused.x": "no_action",
            "Unused.y": "no_action",
            "TemperatureConfigInput.forced": "bug",
            "Unused.z": "no_action",
            "Mode.B": "no_action",
        }
        removed = _change(entry, "TemperatureConfigInput.enabled")
        assert removed["methods"] == ["update_temperature_config"]
        assert removed["locations"] == ["lib.py:3"]
        # graphql.validate cannot see these; no validation error is reported.
        assert not [c for c in entry["changes"] if c["kind"] == "validation_error"]
        bug = next(i for i in report["issues"] if i["group"] == "v4.37.7:bug")
        assert "`TemperatureConfigInput.enabled`: input field removed" in bug["body"]
        assert "`update_temperature_config`" in bug["body"]


class TestValidationIdentity:
    def test_new_suggestions_do_not_create_new_failures(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "lib.py").write_text(
            "class Client:\n"
            "    def create_api_key(self):\n"
            '        return """mutation ($input: ApiKeyCreateInput!) {\n'
            "            create(input: $input)\n"
            '        }"""\n'
        )

        def fake_inventory(schema: Any) -> st.Inventory:
            return st.build_inventory(
                schema, root=tmp_path, sources=("lib.py",), registry=()
            )

        monkeypatch.setattr(uw, "build_inventory", fake_inventory)
        old = "type Query { a: Int }\ntype Mutation { create(input: Other): Int }\n"
        old += "input Other { a: Int }\n"
        # An unrelated addition makes graphql-core suggest the new name.
        new = old + "input ApiKeyCreateInputV2 { a: Int }\n"
        schemas = {"v4.37.6": old, "v4.37.7": new, MAIN_SHA: new}
        releases = [r for r in GITHUB["releases"] if r["tag_name"] <= "v4.37.7"]
        report = uw.scan(FakeGitHub(releases=releases, schemas=schemas), REPO)

        new_failures = st.validate_inventory(
            st.load_sdl(new), fake_inventory(st.load_sdl(new))
        )
        assert any("Did you mean" in f.message for f in new_failures)
        entry = _entry(report, "v4.37.7")
        assert [c["kind"] for c in entry["changes"]] == ["type_added"]
        assert [i["group"] for i in report["issues"]] == ["v4.37.7:enhancement"]


class TestClassification:
    @pytest.mark.parametrize(
        ("change", "selected", "expected"),
        [
            (st.SchemaChange("field_removed", "A.b"), True, "bug"),
            (st.SchemaChange("field_removed", "A.z"), False, "no_action"),
            (st.SchemaChange("field_nullable", "A.b", "Int!", "Int"), True, "bug"),
            (st.SchemaChange("field_type_changed", "A.b", "Int", "S"), True, "bug"),
            (
                st.SchemaChange("field_non_null", "A.b", "Int", "Int!"),
                True,
                "no_action",
            ),
            (st.SchemaChange("type_removed", "A"), True, "bug"),
            (st.SchemaChange("type_removed", "Z"), False, "no_action"),
            (st.SchemaChange("type_added", "Z"), False, "enhancement"),
            (st.SchemaChange("field_added", "A.c"), False, "enhancement"),
            (st.SchemaChange("root_field_added", "Query.z"), False, "enhancement"),
            (st.SchemaChange("deprecation_field", "A.b"), True, "enhancement"),
            (st.SchemaChange("deprecation_enum_value", "E.V"), False, "enhancement"),
            (st.SchemaChange("deprecation_input_field", "In.f"), True, "enhancement"),
            (st.SchemaChange("deprecation_input_field", "Z.f"), False, "enhancement"),
            (st.SchemaChange("arg_removed", "A.b(x:)"), True, "no_action"),
            (st.SchemaChange("enum_value_removed", "E.V"), False, "no_action"),
            (st.SchemaChange("input_field_added", "I.x"), False, "no_action"),
            (st.SchemaChange("input_field_removed", "In.x"), True, "bug"),
            (st.SchemaChange("input_field_removed", "Z.x"), False, "no_action"),
            (
                st.SchemaChange(
                    "input_field_added", "In.y", after="Int!", detail="required"
                ),
                True,
                "bug",
            ),
            (
                st.SchemaChange("input_field_added", "In.y", after="Int"),
                False,
                "no_action",
            ),
            (st.SchemaChange("enum_value_removed", "In.V"), True, "bug"),
            (st.SchemaChange("type_removed", "In"), True, "bug"),
            (st.SchemaChange("input_field_default_removed", "In.f"), True, "bug"),
            (
                st.SchemaChange("input_field_default_removed", "Z.f"),
                False,
                "no_action",
            ),
        ],
    )
    def test_classify(
        self, change: st.SchemaChange, selected: bool, expected: str
    ) -> None:
        selections = {
            "A.b": st.Selection({"get_a"}, {"x:1"}),
            "A.d": st.Selection({"get_d"}, {"x:2"}),
        }
        inputs = {"In": st.Selection({"set_in"}, {"x:3"})}
        classification, selection = uw.classify(change, selections, inputs)
        assert classification == expected
        assert (selection is not None) == selected
        if change.kind == "type_removed" and change.coordinate == "A":
            assert selection is not None
            assert selection.methods == {"get_a", "get_d"}


class TestRendering:
    def test_sanitise_neutralises_markers_mentions_and_references(self) -> None:
        text = uw.sanitise(
            "<!-- upstream-change: evil --> hi @someone see #12 and "
            "<<!---->!-- upstream-group: x --> owner/repo#3"
        )
        assert "<!--" not in text
        assert "-->" not in text
        assert "@\u200bsomeone" in text
        assert "unraid/api#12" in text
        assert "owner/repo#3" in text
        assert uw.sanitise("x" * 500, limit=10) == "x" * 9 + "…"

    def test_issue_bodies_sanitise_upstream_text(self) -> None:
        github = FakeGitHub()
        github.pulls["2095"]["title"] = (
            "<!-- upstream-change: field_nullable:Query.docker:Docker!..Docker --> "
            "@octocat introspection fix for #5"
        )
        report = uw.scan(github, REPO, since="v4.37.7", until="v4.37.8")
        body = next(i for i in report["issues"] if i["group"] == "v4.37.8:bug")["body"]
        assert body.count("upstream-change: field_nullable:Query.docker") == 1
        assert "@\u200boctocat" in body
        assert "unraid/api#5" in body

    def test_bodies_are_truncated_below_the_limit(self) -> None:
        change = {
            "id": "field_added:T.f",
            "kind": "field_added",
            "coordinate": "T.f",
            "before": None,
            "after": None,
            "detail": "x" * 200,
            "classification": "enhancement",
            "selected": False,
            "methods": [],
            "locations": [],
            "already_reported": None,
        }
        changes = [dict(change, id=f"field_added:T.f{n}") for n in range(400)]
        entry = {
            "key": "v1.0.0",
            "kind": "release",
            "base": "v0.9.0",
            "ref": "v1.0.0",
            "compare_url": "https://github.com/unraid/api/compare/v0.9.0...v1.0.0",
            "release_url": "https://github.com/unraid/api/releases/tag/v1.0.0",
            "changes": changes,
            "pull_requests": [],
        }
        issue = uw.render_issue(entry, "v1.0.0:enhancement", "enhancement", changes, [])
        assert len(issue["body"]) <= uw.BODY_LIMIT
        assert issue["body"].endswith("for the full report._")
        assert issue["body"].count("<!-- upstream-change:") == 400

    def test_large_groups_split_and_every_body_fits(self) -> None:
        change = {
            "kind": "field_added",
            "before": None,
            "after": None,
            "detail": "",
            "classification": "enhancement",
            "selected": False,
            "methods": [],
            "locations": [],
            "already_reported": None,
        }
        changes = [
            dict(
                change,
                id=f"field_added:SomeLongTypeName.field{n}",
                coordinate=f"T.f{n}",
            )
            for n in range(2000)
        ]
        entry = {
            "key": "v1.0.0",
            "kind": "release",
            "base": "v0.9.0",
            "ref": "v1.0.0",
            "compare_url": "https://github.com/unraid/api/compare/v0.9.0...v1.0.0",
            "release_url": None,
            "changes": changes,
            "pull_requests": [],
        }
        issues = uw.render_issues(entry, "enhancement", changes, [], {})
        assert len(issues) > 1
        assert all(len(issue["body"]) <= uw.BODY_LIMIT for issue in issues)
        ids = [cid for issue in issues for cid in issue["change_ids"]]
        assert ids == [c["id"] for c in changes]
        groups = [issue["group"] for issue in issues]
        assert len(set(groups)) == len(groups)
        assert all(g.startswith("v1.0.0:enhancement:part-") for g in groups)
        for issue in issues:
            assert f"<!-- upstream-group: {issue['group']} -->" in issue["body"]
            for cid in issue["change_ids"]:
                assert f"<!-- upstream-change: {cid} -->" in issue["body"]
        assert issues[0]["title"].endswith(f"(part 1 of {len(issues)})")

        # A retry after a partial run only reopens the missing parts.
        existing = {groups[0]: 1}
        retry = uw.render_issues(entry, "enhancement", changes, [], existing)
        assert [i["group"] for i in retry] == groups[1:]

        # Small groups keep the plain group key, and an existing one is skipped.
        single = uw.render_issues(entry, "enhancement", changes[:3], [], {})
        assert [i["group"] for i in single] == ["v1.0.0:enhancement"]
        assert (
            uw.render_issues(
                entry, "enhancement", changes[:3], [], {"v1.0.0:enhancement": 4}
            )
            == []
        )

    def test_describe_change(self) -> None:
        base = {"before": None, "after": None, "detail": ""}
        assert (
            uw.describe_change(
                dict(base, kind="arg_added", coordinate="A.b(x:)", after="Int")
            )
            == "`A.b(x:)`: argument added (`∅` → `Int`)"
        )
        assert (
            uw.describe_change(dict(base, kind="mystery", coordinate="A"))
            == "`A`: mystery"
        )

    def test_pull_numbers_and_behaviour_rules(self) -> None:
        text = (
            "fix ([#2095](https://github.com/unraid/api/issues/2095)) "
            "https://github.com/unraid/api/pull/2123 #2095 foo#9 x/#8"
        )
        assert uw.pull_numbers(text) == [2095, 2123]
        many = " ".join(f"#{n}" for n in range(100))
        assert len(uw.pull_numbers(many)) == uw.MAX_PULLS_PER_RELEASE
        assert uw.behaviour_matches("Disable INTROSPECTION by default") == [
            "introspection"
        ]
        assert uw.behaviour_matches("bound request size limit; CORS") == [
            "request limits",
            "CORS/CSRF",
        ]
        assert uw.behaviour_matches("query depth and rate limit errors") == [
            "complexity/depth",
            "rate limiting",
        ]
        assert uw.behaviour_matches("change error format") == ["error shape"]
        assert uw.behaviour_matches("fix typo in docs") == []


class TestBehaviourNotes:
    def test_transient_pr_errors_fail_the_scan(self, tmp_path: Path) -> None:
        for error in (
            st.FetchError("u", 403, "rate limit exceeded"),
            st.FetchError("u", 502, "Bad Gateway"),
            st.FetchError("u", None, "timed out"),
        ):
            github = FakeGitHub()
            github.pull_errors["2095"] = error
            with pytest.raises(st.FetchError):
                uw.scan(github, REPO, since="v4.37.7", until="v4.37.8")
            output = tmp_path / "report.json"
            argv = ["scan", "--since", "v4.37.7", "--output", str(output)]
            assert uw.main(argv, fetch=github) == 1
            assert not output.exists()

    def test_missing_pr_is_skipped(self) -> None:
        github = FakeGitHub()
        del github.pulls["2126"]
        report = uw.scan(github, REPO, since="v4.37.7", until="v4.37.8")
        numbers = [p["number"] for p in _entry(report, "v4.37.8")["pull_requests"]]
        assert numbers == [2123, 2095]

    def test_release_note_lines_with_pr_links_are_analysed(self) -> None:
        release = uw.Release(
            "v4.37.8",
            "* **api:** add rate limiting to websocket requests ([#3001]("
            "https://github.com/unraid/api/issues/3001))\n"
            "* **graphql:** disable introspection (#3002)\n"
            "* **ui:** tidy (#3003)\n",
            "https://github.com/unraid/api/releases/tag/v4.37.8",
        )
        github = FakeGitHub()
        github.pulls = {
            "3001": {"title": "chore: misc", "html_url": "pr1", "body": ""},
            "3002": {
                "title": "fix: introspection",
                "html_url": "pr2",
                "body": "Applies CORS checks.",
            },
            "3003": {"title": "chore: tidy", "html_url": "pr3", "body": ""},
        }
        notes, pulls = uw.release_behaviour(github, release)
        assert len(pulls) == 3
        by_id = {note["id"]: note for note in notes}
        # 3001: the PR text matches nothing, but its release-note line does.
        line_note = by_id["behaviour:v4.37.8:pr-3001"]
        assert line_note["source"] == "unraid/api#3001"
        assert line_note["rules"] == ["rate limiting", "WebSocket"]
        assert line_note["url"] == "https://github.com/unraid/api/pull/3001"
        # 3002: one note per PR; the line's rules merge into the PR note.
        assert [n["id"] for n in notes].count("behaviour:v4.37.8:pr-3002") == 1
        assert by_id["behaviour:v4.37.8:pr-3002"]["rules"] == [
            "introspection",
            "CORS/CSRF",
        ]
        assert set(by_id) == {"behaviour:v4.37.8:pr-3001", "behaviour:v4.37.8:pr-3002"}

    def test_lines_beyond_the_pr_limit_are_still_analysed(self) -> None:
        body = " ".join(f"#{n}" for n in range(uw.MAX_PULLS_PER_RELEASE))
        body += "\n* bound request size limit (#9000)\n"
        release = uw.Release("v4.37.8", body, "rel")
        notes, _ = uw.release_behaviour(FakeGitHub(), release)
        assert [(n["id"], n["rules"]) for n in notes] == [
            ("behaviour:v4.37.8:pr-9000", ["request limits"])
        ]


class TestCli:
    def test_scan_writes_report(self, tmp_path: Path, capsys: Any) -> None:
        output = tmp_path / "report.json"
        code = uw.main(
            [
                "scan",
                "--since",
                "v4.37.6",
                "--until",
                "v4.37.9",
                "--repo",
                REPO,
                "--output",
                str(output),
            ],
            fetch=FakeGitHub(),
        )
        assert code == 0
        report = json.loads(output.read_text())
        assert len(report["issues"]) == 2
        assert "2 issue(s) to open" in capsys.readouterr().out

    def test_scan_errors_exit_1(self, tmp_path: Path, capsys: Any) -> None:
        output = tmp_path / "report.json"
        code = uw.main(
            ["scan", "--since", "bad", "--output", str(output)], fetch=FakeGitHub()
        )
        assert code == 1
        assert not output.exists()
        assert "ERROR:" in capsys.readouterr().err

    def test_empty_inputs_and_default_fetcher(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        github = FakeGitHub()
        tokens: list[str | None] = []

        def fake_https_get(url: str, token: str | None = None) -> bytes:
            tokens.append(token)
            return github(url)

        monkeypatch.setattr(uw, "https_get", fake_https_get)
        monkeypatch.setenv("GITHUB_TOKEN", "secret")
        monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
        output = tmp_path / "report.json"
        code = uw.main(["scan", "--since", "", "--until", "", "--output", str(output)])
        assert code == 0
        assert set(tokens) == {"secret"}
        assert json.loads(output.read_text())["range"]["since"] == "v4.37.8"
