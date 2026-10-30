"""Watch unraid/api releases and schema changes for library impact.

`scan` is read-only. It lists upstream releases newer than the last one
recorded in this repository's issues, diffs `api/generated-schema.graphql`
between consecutive release tags and from the latest release to `main`,
validates every library operation against each new schema, flags release
notes that change request handling, and writes one JSON report. The report
carries ready-to-create issue payloads and a job summary; the workflow's
report job only creates what is not there yet.

Usage:
  uv run python script/upstream_watch.py scan --output report.json
  uv run python script/upstream_watch.py scan --since v4.37.6 --until v4.37.9

Set GITHUB_TOKEN to raise the GitHub API rate limit.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from packaging.version import Version

from schema_tools import (
    SHA_RE,
    TAG_RE,
    UPSTREAM_REPO,
    FetchError,
    Inventory,
    NotFoundError,
    SchemaChange,
    Selection,
    SelectionIndex,
    build_inventory,
    diff_schemas,
    https_get,
    input_usage,
    load_sdl,
    merge_selections,
    schema_url,
    selected_coordinates,
    validate_inventory,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from graphql import GraphQLSchema

    Fetcher = Callable[[str], bytes]

BOT_LOGIN = "github-actions[bot]"
DEFAULT_REPO = "tinkerologie/unraid-api"
STATE_TITLE = "Upstream watch state"
PER_PAGE = 100
MAX_PULLS_PER_RELEASE = 30
BODY_LIMIT = 60000
# Hidden markers per issue are capped so the visible body always has room;
# larger groups are split across several issues.
MARKER_BUDGET = BODY_LIMIT // 2
TEXT_LIMIT = 300
REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
API = "https://api.github.com"

RELEASE_MARKER_RE = re.compile(r"<!-- upstream-release: (v\d+\.\d+\.\d+) -->")
MAIN_MARKER_RE = re.compile(r"<!-- upstream-main: ([0-9a-f]{40}) -->")
CHANGE_MARKER_RE = re.compile(r"<!-- upstream-change: (\S+) -->")
GROUP_MARKER_RE = re.compile(r"<!-- upstream-group: (\S+) -->")
PULL_RE = re.compile(r"(?:github\.com/unraid/api/(?:pull|issues)/|(?<![\w/])#)(\d+)")

# Release-note and PR text that signals a change in how requests are handled.
BEHAVIOUR_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("introspection", r"introspection|__schema|__type\b"),
        ("sandbox", r"\bsandbox\b"),
        (
            "request limits",
            r"request[- ]?(?:size|body)?[- ]?limit|body[- ]?limit|payload[- ]?limit",
        ),
        ("complexity/depth", r"complexity|query[- ]depth|depth[- ]limit"),
        ("auth/API key", r"\bauth(?:entication|orization)?\b|\bapi[- ]?keys?\b"),
        ("rate limiting", r"rate[- ]?limit|throttl"),
        ("CORS/CSRF", r"\bcors\b|\bcsrf\b"),
        ("WebSocket", r"websocket|graphql-ws"),
        ("error shape", r"error (?:shape|format|response|code)s?|extensions\.code"),
    )
)

BREAKING_KINDS = frozenset({"field_removed", "field_nullable", "field_type_changed"})
# Breaking when the input object or enum type is sent in a library variable.
INPUT_BREAKING_KINDS = frozenset(
    {
        "input_field_removed",
        "input_field_type_changed",
        "input_field_default_removed",
        "enum_value_removed",
    }
)
ENHANCEMENT_KINDS = frozenset({"type_added", "field_added", "root_field_added"})
CHANGE_LABELS = {
    "type_added": "type added",
    "type_removed": "type removed",
    "field_added": "field added",
    "root_field_added": "root field added",
    "field_removed": "field removed",
    "field_nullable": "non-null → nullable",
    "field_non_null": "nullable → non-null",
    "field_type_changed": "type changed",
    "arg_added": "argument added",
    "arg_removed": "argument removed",
    "arg_type_changed": "argument type changed",
    "input_field_added": "input field added",
    "input_field_removed": "input field removed",
    "input_field_type_changed": "input field type changed",
    "input_field_default_removed": "input field default removed (now required)",
    "enum_value_added": "enum value added",
    "enum_value_removed": "enum value removed",
    "deprecation_field": "field deprecated",
    "deprecation_arg": "argument deprecated",
    "deprecation_enum_value": "enum value deprecated",
    "deprecation_input_field": "input field deprecated",
    "validation_error": "operation no longer validates",
}


class ScanError(Exception):
    """The scan cannot proceed (bad input or missing upstream data)."""


# =============================================================================
# GitHub access
# =============================================================================


def fetch_json(fetch: Fetcher, url: str) -> Any:
    return json.loads(fetch(url))


@dataclass(frozen=True)
class Release:
    tag: str
    body: str
    url: str

    @property
    def version(self) -> Version:
        return Version(self.tag[1:])


def list_releases(fetch: Fetcher) -> list[Release]:
    """Published, non-prerelease upstream releases, oldest first."""
    releases: list[Release] = []
    page = 1
    while True:
        batch = fetch_json(
            fetch,
            f"{API}/repos/{UPSTREAM_REPO}/releases?per_page={PER_PAGE}&page={page}",
        )
        for item in batch:
            tag = item.get("tag_name") or ""
            if item.get("draft") or item.get("prerelease") or not TAG_RE.match(tag):
                continue
            releases.append(Release(tag, item.get("body") or "", item["html_url"]))
        if len(batch) < PER_PAGE:
            break
        page += 1
    return sorted(releases, key=lambda release: release.version)


def main_head_sha(fetch: Fetcher) -> str:
    sha = str(fetch_json(fetch, f"{API}/repos/{UPSTREAM_REPO}/commits/main")["sha"])
    if not SHA_RE.match(sha):
        raise ScanError(f"Unexpected upstream main SHA: {sha!r}")
    return sha


def fetch_schema(fetch: Fetcher, ref: str) -> GraphQLSchema | None:
    """The upstream schema at `ref`, or None when the file does not exist."""
    try:
        return load_sdl(fetch(schema_url(ref)).decode("utf-8"))
    except NotFoundError:
        return None


@dataclass
class Markers:
    """Hidden markers found in bot-authored issues of this repository."""

    release: str | None = None
    main: str | None = None
    changes: dict[str, int] = field(default_factory=dict)
    groups: dict[str, int] = field(default_factory=dict)


def read_markers(fetch: Fetcher, repo: str) -> Markers:
    """Read markers from every bot-authored issue, open or closed.

    Change and group markers come from every such issue; the release and
    main cursor only from the state issue. Uses the paginated REST listing,
    never the search API, which lags.
    """
    markers = Markers()
    page = 1
    while True:
        batch = fetch_json(
            fetch,
            f"{API}/repos/{repo}/issues?state=all&per_page={PER_PAGE}&page={page}",
        )
        for issue in batch:
            if "pull_request" in issue:
                continue
            if (issue.get("user") or {}).get("login") != BOT_LOGIN:
                continue
            number = int(issue["number"])
            body = issue.get("body") or ""
            # The cursor comes only from the state issue, which the report job
            # updates after every issue is created. Release markers in finding
            # issues are not a cursor: a run that fails midway must not skip.
            if issue.get("title") == STATE_TITLE:
                for tag in RELEASE_MARKER_RE.findall(body):
                    if markers.release is None or Version(tag[1:]) > Version(
                        markers.release[1:]
                    ):
                        markers.release = tag
                main = MAIN_MARKER_RE.search(body)
                if main:
                    markers.main = main.group(1)
            for change_id in CHANGE_MARKER_RE.findall(body):
                markers.changes.setdefault(change_id, number)
            for group in GROUP_MARKER_RE.findall(body):
                markers.groups.setdefault(group, number)
        if len(batch) < PER_PAGE:
            break
        page += 1
    return markers


def resolve_range(
    releases: list[Release],
    recorded: str | None,
    since: str | None,
    until: str | None,
) -> list[Release]:
    """Releases to walk, oldest first; the first entry is the diff base."""
    tags = [release.tag for release in releases]
    for name, tag in (("--since", since), ("--until", until)):
        if tag is None:
            continue
        if not TAG_RE.match(tag):
            raise ScanError(f"{name} {tag!r} is not a release tag like v4.37.9")
        if tag not in tags:
            raise ScanError(f"{name} {tag} is not a published unraid/api release")
    if not releases:
        raise ScanError("unraid/api has no published releases")

    end = tags.index(until) if until else len(tags) - 1
    if since:
        start = tags.index(since)
    elif recorded in tags and (until is None or tags.index(recorded) < end):
        start = tags.index(recorded)
    else:
        start = max(end - 1, 0)
    if start > end:
        raise ScanError(f"--since {since} is newer than --until {until}")
    return releases[start : end + 1]


# =============================================================================
# Behaviour notes
# =============================================================================


def pull_numbers(text: str) -> list[int]:
    """Linked unraid/api PR numbers, in order, up to the fixed limit."""
    numbers: list[int] = []
    for match in PULL_RE.findall(text):
        number = int(match)
        if number not in numbers:
            numbers.append(number)
    return numbers[:MAX_PULLS_PER_RELEASE]


def behaviour_matches(text: str) -> list[str]:
    return [label for label, pattern in BEHAVIOUR_RULES if pattern.search(text)]


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def release_behaviour(
    fetch: Fetcher, release: Release
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Behaviour notes and linked PRs for one release."""
    by_pull: dict[int, dict[str, Any]] = {}
    notes: list[dict[str, Any]] = []
    pulls: list[dict[str, Any]] = []
    for number in pull_numbers(release.body):
        # Only "not found" means the link is not a PR. Rate limits, server and
        # network errors propagate so the scan fails and nothing advances.
        try:
            pr = fetch_json(fetch, f"{API}/repos/{UPSTREAM_REPO}/pulls/{number}")
        except NotFoundError:
            continue
        title = str(pr.get("title") or "")
        url = str(pr.get("html_url") or "")
        pulls.append({"number": number, "title": title, "url": url})
        rules = behaviour_matches(f"{title}\n{pr.get('body') or ''}")
        if rules:
            by_pull[number] = {
                "id": f"behaviour:{release.tag}:pr-{number}",
                "source": f"unraid/api#{number}",
                "title": title,
                "url": url,
                "rules": rules,
            }
            notes.append(by_pull[number])
    for line in release.body.splitlines():
        text = line.strip(" *-\t")
        rules = behaviour_matches(text) if text else []
        if not rules:
            continue
        linked = pull_numbers(text)
        existing = next((by_pull[n] for n in linked if n in by_pull), None)
        if existing is not None:
            # Same PR already noted: merge the line's rules into that note.
            existing["rules"] += [r for r in rules if r not in existing["rules"]]
            continue
        if linked:
            note_id = f"behaviour:{release.tag}:pr-{linked[0]}"
            source = f"unraid/api#{linked[0]}"
            url = f"https://github.com/{UPSTREAM_REPO}/pull/{linked[0]}"
        else:
            note_id = f"behaviour:{release.tag}:note-{_short_hash(text)}"
            source, url = "release notes", release.url
        note: dict[str, Any] = {
            "id": note_id,
            "source": source,
            "title": text,
            "url": url,
            "rules": rules,
        }
        for number in linked:
            by_pull[number] = note
        notes.append(note)
    return notes, pulls


# =============================================================================
# Classification
# =============================================================================


def _type_selection(type_name: str, selections: SelectionIndex) -> Selection | None:
    found = [s for c, s in selections.items() if c.split(".", 1)[0] == type_name]
    if not found:
        return None
    merged = Selection()
    for selection in found:
        merged.methods.update(selection.methods)
        merged.locations.update(selection.locations)
    return merged


def classify(
    change: SchemaChange,
    selections: SelectionIndex,
    inputs: SelectionIndex | None = None,
) -> tuple[str, Selection | None]:
    """Classify a change as `bug`, `enhancement` or `no_action`.

    `inputs` maps input object and enum types the library sends in variables
    to the methods that send them.
    """
    usage = (inputs or {}).get(change.type_name)
    if change.kind in INPUT_BREAKING_KINDS or (
        change.kind == "input_field_added" and change.detail == "required"
    ):
        return ("bug" if usage else "no_action"), usage
    if change.kind == "type_removed":
        selection = _type_selection(change.coordinate, selections) or usage
        return ("bug" if selection else "no_action"), selection
    coordinate = change.field_coordinate
    selection = selections.get(coordinate) if coordinate else None
    if change.kind in BREAKING_KINDS:
        return ("bug" if selection else "no_action"), selection
    if change.kind in ENHANCEMENT_KINDS or change.kind.startswith("deprecation_"):
        # Flag deprecations the library selects, or sends in its variables.
        return "enhancement", selection or usage
    return "no_action", selection


def _change_entry(
    change: SchemaChange, classification: str, selection: Selection | None
) -> dict[str, Any]:
    return {
        "id": change.id,
        "kind": change.kind,
        "coordinate": change.coordinate,
        "before": change.before,
        "after": change.after,
        "detail": change.detail,
        "classification": classification,
        "selected": selection is not None,
        "methods": sorted(selection.methods) if selection else [],
        "locations": sorted(selection.locations) if selection else [],
        "already_reported": None,
    }


# =============================================================================
# Steps
# =============================================================================


@dataclass
class Analysis:
    """A schema with the library inventory rendered and checked against it."""

    schema: GraphQLSchema
    inventory: Inventory
    selections: SelectionIndex
    inputs: SelectionIndex
    failures: set[tuple[str, str]]


class SchemaCache:
    """Fetched schemas and their analyses, per upstream ref."""

    def __init__(self, fetch: Fetcher) -> None:
        self.fetch = fetch
        self._analyses: dict[str, Analysis | None] = {}

    def analysis(self, ref: str) -> Analysis | None:
        if ref not in self._analyses:
            schema = fetch_schema(self.fetch, ref)
            if schema is None:
                self._analyses[ref] = None
            else:
                inventory = build_inventory(schema)
                self._analyses[ref] = Analysis(
                    schema,
                    inventory,
                    selected_coordinates(schema, inventory),
                    input_usage(schema, inventory),
                    {f.key for f in validate_inventory(schema, inventory)},
                )
        return self._analyses[ref]


def analyse_step(
    cache: SchemaCache, key: str, kind: str, base: str, ref: str
) -> dict[str, Any]:
    """Diff the schema from `base` to `ref` and assess library impact."""
    entry: dict[str, Any] = {
        "key": key,
        "kind": kind,
        "base": base,
        "ref": ref,
        "compare_url": f"https://github.com/{UPSTREAM_REPO}/compare/{base}...{ref}",
        "schema_status": "ok",
        "missing_schema": [],
        "changes": [],
        "behaviour_notes": [],
        "pull_requests": [],
    }
    old, new = cache.analysis(base), cache.analysis(ref)
    if old is None or new is None:
        entry["schema_status"] = "unavailable"
        entry["missing_schema"] = [r for r, a in ((base, old), (ref, new)) if a is None]
        return entry

    selections = merge_selections(old.selections, new.selections)
    inputs = merge_selections(old.inputs, new.inputs)
    for change in diff_schemas(old.schema, new.schema):
        classification, selection = classify(change, selections, inputs)
        entry["changes"].append(_change_entry(change, classification, selection))

    # Only operations that validated against the old schema are new breakage.
    old_failures = old.failures | {
        f.key for f in validate_inventory(old.schema, new.inventory)
    }
    for failure in validate_inventory(new.schema, new.inventory):
        if failure.key in old_failures:
            continue
        change = SchemaChange(
            "validation_error",
            failure.methods[0] if failure.methods else "unknown",
            detail=failure.message,
        )
        item = _change_entry(change, "bug", None)
        item["id"] = (
            f"validation_error:{change.coordinate}:"
            f"{_short_hash(failure.document.strip() + failure.stable_message)}"
        )
        item["selected"] = True
        item["methods"] = list(failure.methods)
        item["locations"] = list(failure.locations)
        entry["changes"].append(item)
    return entry


# =============================================================================
# Rendering
# =============================================================================


def sanitise(text: str, limit: int = TEXT_LIMIT) -> str:
    """Make upstream text inert in an issue body.

    HTML comments are removed and remaining angle brackets escaped, so the
    text cannot carry markers or HTML. Mentions are broken with a zero-width
    space and bare `#123` references point at unraid/api.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"@(?=[A-Za-z0-9])", "@\u200b", text)
    text = re.sub(r"(?<![\w/#])#(\d+)\b", rf"{UPSTREAM_REPO}#\1", text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe_change(change: dict[str, Any]) -> str:
    label = CHANGE_LABELS.get(change["kind"], change["kind"])
    if change["kind"] == "validation_error":
        return f"`{change['coordinate']}`: {label}: {sanitise(change['detail'])}"
    text = f"`{change['coordinate']}`: {label}"
    if change["before"] or change["after"]:
        text += f" (`{change['before'] or '∅'}` → `{change['after'] or '∅'}`)"
    if change["detail"]:
        text += f" ({sanitise(change['detail'])})"
    return text


def _impact_lines(change: dict[str, Any]) -> list[str]:
    if not change["methods"]:
        return []
    methods = ", ".join(f"`{m}`" for m in change["methods"])
    locations = ", ".join(f"`{loc}`" for loc in change["locations"])
    return [f"  - Library methods: {methods}", f"  - Source: {locations}"]


def _version_label(entry: dict[str, Any]) -> str:
    if entry["kind"] == "main":
        return f"main@{entry['ref'][:7]}"
    return str(entry["ref"])


def render_issue(
    entry: dict[str, Any],
    group: str,
    label: str,
    changes: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    *,
    title_suffix: str = "",
) -> dict[str, Any]:
    """Render one issue payload for a step's `bug` or `enhancement` group."""
    version = _version_label(entry)
    ids = [c["id"] for c in changes] + [n["id"] for n in notes]
    header = [f"<!-- upstream-group: {group} -->"]
    if entry["kind"] == "main":
        header.append(f"<!-- upstream-main: {entry['ref']} -->")
    else:
        header.append(f"<!-- upstream-release: {entry['ref']} -->")
    header.extend(f"<!-- upstream-change: {change_id} -->" for change_id in ids)

    lines = [
        f"Upstream watch found changes in unraid/api {version}, compared with "
        f"{entry['base']} ([diff]({entry['compare_url']})).",
        "",
    ]
    if entry.get("release_url"):
        lines += [f"Release notes: {entry['release_url']}", ""]
    if label == "bug":
        title_kind = "breaking changes" if changes else "behaviour changes to review"
        title = f"[Bug]: Upstream unraid/api {version}: {title_kind}"
        breaking = [c for c in changes if c["kind"] != "validation_error"]
        invalid = [c for c in changes if c["kind"] == "validation_error"]
        if breaking:
            lines.append("## Breaking schema changes")
            lines.append("")
            for change in breaking:
                lines.append(f"- {describe_change(change)}")
                lines.extend(_impact_lines(change))
            lines.append("")
        if invalid:
            lines.append("## Operations that no longer validate")
            lines.append("")
            for change in invalid:
                lines.append(f"- {describe_change(change)}")
                lines.extend(_impact_lines(change))
            lines.append("")
        if notes:
            lines.append("## Behaviour changes")
            lines.append("")
            for note in notes:
                rules = ", ".join(note["rules"])
                lines.append(
                    f"- [{sanitise(note['source'])}]({note['url']}): "
                    f"{sanitise(note['title'])} (matched: {rules})"
                )
            lines.append("")
    else:
        title = f"[Enhancement]: Upstream unraid/api {version}: new schema surface"
        lines.append("## New and deprecated schema surface")
        lines.append("")
        for change in changes:
            selected = " (selected by the library)" if change["selected"] else ""
            lines.append(f"- {describe_change(change)}{selected}")
            lines.extend(_impact_lines(change))
        lines.append("")
    if entry["changes"]:
        lines.append("<details><summary>Full schema diff for this step</summary>")
        lines.append("")
        lines.extend(
            f"- {describe_change(c)} ({c['classification']})" for c in entry["changes"]
        )
        lines.append("")
        lines.append("</details>")
        lines.append("")
    if entry["pull_requests"]:
        lines.append("## Linked pull requests")
        lines.append("")
        lines.extend(
            f"- [unraid/api#{pr['number']}]({pr['url']}): {sanitise(pr['title'])}"
            for pr in entry["pull_requests"]
        )
        lines.append("")
    lines.append("_Opened by the Upstream watch workflow._")

    head = "\n".join(header) + "\n\n"
    body = "\n".join(lines)
    if len(head) + len(body) > BODY_LIMIT:
        notice = "\n\n_Truncated; see the workflow run summary for the full report._"
        body = body[: max(0, BODY_LIMIT - len(head) - len(notice))] + notice
    return {
        "group": group,
        "title": title + title_suffix,
        "labels": [label, "upstream"],
        "body": head + body,
        "change_ids": ids,
    }


def _marker_length(item: dict[str, Any]) -> int:
    return len(f"<!-- upstream-change: {item['id']} -->\n")


def render_issues(
    entry: dict[str, Any],
    label: str,
    changes: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    existing_groups: dict[str, int],
) -> list[dict[str, Any]]:
    """Render a group's payloads, split so every body stays within BODY_LIMIT.

    A group that fits in one issue keeps the plain `<key>:<label>` group
    marker. Larger groups are split into parts whose group markers carry a
    hash of their change IDs, so a retry after a partial run only reopens
    the parts that were never created.
    """
    items = [("change", c) for c in changes] + [("note", n) for n in notes]
    chunks: list[list[tuple[str, dict[str, Any]]]] = [[]]
    used = 0
    for item in items:
        size = _marker_length(item[1])
        if chunks[-1] and used + size > MARKER_BUDGET:
            chunks.append([])
            used = 0
        chunks[-1].append(item)
        used += size

    base = f"{entry['key']}:{label}"
    if len(chunks) == 1:
        if base in existing_groups:
            return []
        return [render_issue(entry, base, label, changes, notes)]
    payloads = []
    for index, chunk in enumerate(chunks, 1):
        part_changes = [i for kind, i in chunk if kind == "change"]
        part_notes = [i for kind, i in chunk if kind == "note"]
        ids = " ".join(i["id"] for _, i in chunk)
        group = f"{base}:part-{_short_hash(ids)}"
        if group in existing_groups:
            continue
        suffix = f" (part {index} of {len(chunks)})"
        payloads.append(
            render_issue(
                entry, group, label, part_changes, part_notes, title_suffix=suffix
            )
        )
    return payloads


def render_summary(report: dict[str, Any]) -> str:
    """Markdown summary of every release and change checked."""
    rng = report["range"]
    lines = [
        "# Upstream watch",
        "",
        f"Releases: {', '.join(rng['releases']) or 'none new'} "
        f"(base {rng['since']}); main: `{rng['main'][:7]}`.",
        "",
    ]
    for entry in report["entries"]:
        lines.append(f"## {_version_label(entry)} (vs {entry['base']})")
        lines.append("")
        if entry["schema_status"] != "ok":
            missing = ", ".join(entry["missing_schema"])
            lines.append(f"Schema unavailable at {missing}; diff skipped.")
            lines.append("")
        elif not entry["changes"]:
            lines.append("No schema changes.")
            lines.append("")
        else:
            lines.append("| Change | Classification | Library methods | Status |")
            lines.append("| --- | --- | --- | --- |")
            for change in entry["changes"]:
                methods = ", ".join(change["methods"]) or "-"
                status = (
                    f"already reported in #{change['already_reported']}"
                    if change["already_reported"]
                    else "new"
                )
                description = describe_change(change).replace("|", "\\|")
                lines.append(
                    f"| {description} | {change['classification']} | {methods} "
                    f"| {status} |"
                )
            lines.append("")
        for note in entry["behaviour_notes"]:
            status = (
                f"already reported in #{note['already_reported']}"
                if note["already_reported"]
                else "new"
            )
            lines.append(
                f"- Behaviour: {sanitise(note['source'])}: {sanitise(note['title'])} "
                f"({', '.join(note['rules'])}; {status})"
            )
        if entry["behaviour_notes"]:
            lines.append("")
    lines.append("## Issues to open")
    lines.append("")
    if report["issues"]:
        lines.extend(f"- {issue['title']}" for issue in report["issues"])
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


# =============================================================================
# Scan
# =============================================================================


def _mark_reported(
    items: list[dict[str, Any]], markers: Markers, seen: set[str]
) -> list[dict[str, Any]]:
    """Fill `already_reported` and return items not reported anywhere yet."""
    fresh: list[dict[str, Any]] = []
    for item in items:
        item["already_reported"] = markers.changes.get(item["id"])
        if item["already_reported"] is None and item["id"] not in seen:
            seen.add(item["id"])
            fresh.append(item)
    return fresh


def scan(
    fetch: Fetcher,
    repo: str,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Run the read-only scan and return the report."""
    if not REPO_RE.match(repo):
        raise ScanError(f"Invalid repository: {repo!r}")
    releases = list_releases(fetch)
    markers = read_markers(fetch, repo)
    chain = resolve_range(releases, markers.release, since, until)
    latest = releases[-1]
    sha = main_head_sha(fetch)
    cache = SchemaCache(fetch)

    entries: list[dict[str, Any]] = []
    for base, release in itertools.pairwise(chain):
        entry = analyse_step(cache, release.tag, "release", base.tag, release.tag)
        entry["release_url"] = release.url
        notes, pulls = release_behaviour(fetch, release)
        entry["behaviour_notes"] = notes
        entry["pull_requests"] = pulls
        entries.append(entry)
    main_entry = analyse_step(cache, f"main@{sha[:7]}", "main", latest.tag, sha)
    main_entry["release_url"] = None
    entries.append(main_entry)

    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        changes = _mark_reported(entry["changes"], markers, seen)
        notes = _mark_reported(entry["behaviour_notes"], markers, seen)
        bugs = [c for c in changes if c["classification"] == "bug"]
        enhancements = [c for c in changes if c["classification"] == "enhancement"]
        for label, items, group_notes in (
            ("bug", bugs, notes),
            ("enhancement", enhancements, []),
        ):
            if items or group_notes:
                issues.extend(
                    render_issues(entry, label, items, group_notes, markers.groups)
                )

    recorded = markers.release
    newest = chain[-1].tag
    if recorded and Version(recorded[1:]) > Version(newest[1:]):
        newest = recorded
    report: dict[str, Any] = {
        "range": {
            "since": chain[0].tag,
            "until": chain[-1].tag,
            "releases": [release.tag for release in chain[1:]],
            "latest": latest.tag,
            "main": sha,
            "recorded_release": markers.release,
            "recorded_main": markers.main,
        },
        "entries": entries,
        "issues": issues,
        "state": {"upstream_release": newest, "upstream_main": sha},
    }
    report["summary_markdown"] = render_summary(report)
    return report


def main(argv: list[str] | None = None, fetch: Fetcher | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan", help="Read-only scan; writes a JSON report")
    scan_parser.add_argument("--since", help="Base release tag (e.g. v4.37.6)")
    scan_parser.add_argument("--until", help="Last release tag to process")
    scan_parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO,
        help="Repository whose issues hold the markers (owner/name)",
    )
    scan_parser.add_argument("--output", default="report.json", type=Path)
    args = parser.parse_args(argv)

    if fetch is None:
        token = os.environ.get("GITHUB_TOKEN") or None

        def fetch(url: str) -> bytes:
            return https_get(url, token)

    try:
        report = scan(fetch, args.repo, args.since or None, args.until or None)
    except (ScanError, FetchError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Scanned {report['range']['since']}..{report['range']['until']} and main; "
        f"{len(report['issues'])} issue(s) to open. Report: {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
