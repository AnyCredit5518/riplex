from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx


DEFAULT_REPO = "AnyCredit5518/riplex"
DEFAULT_CONTRIBUTORS_FILE = Path("CONTRIBUTORS.md")
DEFAULT_OVERRIDES_FILE = Path(".github/contributors-overrides.json")
DEFAULT_GIT_REF = "origin/main"
START_MARKER = "<!-- BUG_BASHERS:START -->"
END_MARKER = "<!-- BUG_BASHERS:END -->"
OWNER_LOGIN = "AnyCredit5518"
ISSUE_REF_RE = re.compile(
    r"(?i)(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|issue|issues)?\s*#(\d+)"
)


@dataclass(frozen=True)
class Issue:
    number: int
    author: str
    labels: frozenset[str]
    url: str

    @property
    def is_bug(self) -> bool:
        return any(label.lower() == "bug" for label in self.labels)


@dataclass(frozen=True)
class Overrides:
    include: frozenset[int]
    exclude: frozenset[int]

    @classmethod
    def empty(cls) -> "Overrides":
        return cls(include=frozenset(), exclude=frozenset())


@dataclass(frozen=True)
class Contributor:
    username: str
    issue_numbers: tuple[int, ...]
    issue_urls: dict[int, str]


def rank_for_count(count: int) -> str:
    if count >= 25:
        return "💎"
    if count >= 15:
        return "🛡️"
    if count >= 8:
        return "🔍"
    if count >= 4:
        return "🐛"
    return "🧪"


def parse_issue(item: dict[str, Any]) -> Issue | None:
    if "pull_request" in item:
        return None

    user = item.get("user") or {}
    login = user.get("login")
    if not login:
        return None

    labels = item.get("labels") or []
    label_names = frozenset(
        label.get("name", "") if isinstance(label, dict) else str(label)
        for label in labels
    )
    return Issue(
        number=int(item["number"]),
        author=str(login),
        labels=label_names,
        url=str(item.get("html_url") or ""),
    )


def fetch_closed_issues(repo: str, token: str | None = None) -> list[Issue]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    issues: list[Issue] = []
    page = 1
    per_page = 100
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        while True:
            response = client.get(
                f"https://api.github.com/repos/{repo}/issues",
                params={"state": "closed", "per_page": per_page, "page": page},
            )
            response.raise_for_status()
            items = response.json()
            if not items:
                break

            for item in items:
                issue = parse_issue(item)
                if issue is not None:
                    issues.append(issue)

            if len(items) < per_page:
                break
            page += 1

    return issues


def extract_issue_references(text: str) -> frozenset[int]:
    return frozenset(int(match.group(1)) for match in ISSUE_REF_RE.finditer(text))


def git_ref_exists(repo_root: Path, git_ref: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", git_ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def find_referenced_issues(repo_root: Path, git_ref: str = DEFAULT_GIT_REF) -> frozenset[int]:
    log_ref = git_ref if git_ref_exists(repo_root, git_ref) else "HEAD"
    result = subprocess.run(
        ["git", "log", log_ref, "--format=%B"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return extract_issue_references(result.stdout)


def load_overrides(path: Path) -> Overrides:
    if not path.exists():
        return Overrides.empty()

    data = json.loads(path.read_text(encoding="utf-8"))
    return Overrides(
        include=frozenset(_parse_override_numbers(data.get("include", []), "include")),
        exclude=frozenset(_parse_override_numbers(data.get("exclude", []), "exclude")),
    )


def _parse_override_numbers(entries: Any, field_name: str) -> list[int]:
    if not isinstance(entries, list):
        raise ValueError(f"overrides field {field_name!r} must be a list")

    numbers: list[int] = []
    for entry in entries:
        if isinstance(entry, int):
            numbers.append(entry)
            continue
        if isinstance(entry, dict) and isinstance(entry.get("number"), int):
            numbers.append(entry["number"])
            continue
        raise ValueError(
            f"overrides field {field_name!r} must contain issue numbers or objects with a number"
        )
    return numbers


def should_exclude_author(username: str, owner_login: str = OWNER_LOGIN) -> bool:
    return username.lower() == owner_login.lower() or username.lower().endswith("[bot]")


def eligible_issues(
    issues: Iterable[Issue], referenced_issue_numbers: set[int] | frozenset[int], overrides: Overrides
) -> list[Issue]:
    selected: list[Issue] = []
    for issue in issues:
        if issue.number in overrides.exclude:
            continue
        if should_exclude_author(issue.author):
            continue

        has_strict_signal = issue.is_bug and issue.number in referenced_issue_numbers
        has_manual_signal = issue.number in overrides.include
        if has_strict_signal or has_manual_signal:
            selected.append(issue)
    return selected


def build_contributors(issues: Iterable[Issue]) -> list[Contributor]:
    grouped: dict[str, dict[int, str]] = {}
    display_names: dict[str, str] = {}
    for issue in issues:
        key = issue.author.lower()
        display_names.setdefault(key, issue.author)
        grouped.setdefault(key, {})[issue.number] = issue.url

    contributors = [
        Contributor(
            username=display_names[key],
            issue_numbers=tuple(sorted(issue_urls)),
            issue_urls=issue_urls,
        )
        for key, issue_urls in grouped.items()
    ]
    return sorted(
        contributors,
        key=lambda contributor: (-len(contributor.issue_numbers), contributor.username.lower()),
    )


def render_table(contributors: Sequence[Contributor]) -> str:
    lines = ["| User | Issues |", "|------|--------|"]
    for contributor in contributors:
        rank = rank_for_count(len(contributor.issue_numbers))
        user = f"{rank} [@{contributor.username}](https://github.com/{contributor.username})"
        issue_links = ", ".join(
            f"[#{number}]({contributor.issue_urls[number]})"
            for number in contributor.issue_numbers
        )
        lines.append(f"| {user} | {issue_links} |")
    return "\n".join(lines)


def replace_marker_block(content: str, replacement: str) -> str:
    start = content.find(START_MARKER)
    end = content.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"Could not find ordered {START_MARKER!r} and {END_MARKER!r} markers"
        )

    block_start = start + len(START_MARKER)
    before = content[:block_start]
    after = content[end:]
    return f"{before}\n{replacement.rstrip()}\n{after}"


def unified_diff(original: str, updated: str, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path.as_posix()}",
            tofile=f"b/{path.as_posix()}",
        )
    )


def update_contributors_file(
    contributors_file: Path, table: str, dry_run: bool = False
) -> tuple[bool, str]:
    original = contributors_file.read_text(encoding="utf-8")
    updated = replace_marker_block(original, table)
    if original == updated:
        return False, ""

    diff = unified_diff(original, updated, contributors_file)
    if not dry_run:
        contributors_file.write_text(updated, encoding="utf-8")
    return True, diff


def generate_table(
    repo: str,
    repo_root: Path,
    overrides_file: Path,
    token: str | None,
    git_ref: str = DEFAULT_GIT_REF,
) -> str:
    issues = fetch_closed_issues(repo, token=token)
    referenced_issue_numbers = find_referenced_issues(repo_root, git_ref=git_ref)
    overrides = load_overrides(overrides_file)
    selected_issues = eligible_issues(issues, referenced_issue_numbers, overrides)
    contributors = build_contributors(selected_issues)
    return render_table(contributors)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update the generated Bug Bashers table in CONTRIBUTORS.md."
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo as owner/name.")
    parser.add_argument(
        "--contributors-file",
        type=Path,
        default=DEFAULT_CONTRIBUTORS_FILE,
        help="Path to CONTRIBUTORS.md.",
    )
    parser.add_argument(
        "--overrides-file",
        type=Path,
        default=DEFAULT_OVERRIDES_FILE,
        help="Path to the manual include/exclude override JSON file.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root used for local git history scanning.",
    )
    parser.add_argument(
        "--git-ref",
        default=DEFAULT_GIT_REF,
        help="Git ref to scan for issue references. Falls back to HEAD if missing.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub token. Defaults to GITHUB_TOKEN when omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the diff without writing CONTRIBUTORS.md.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    contributors_file = (repo_root / args.contributors_file).resolve()
    overrides_file = (repo_root / args.overrides_file).resolve()
    token = args.token or os.environ.get("GITHUB_TOKEN")

    if not token:
        print(
            "GITHUB_TOKEN is not set; using unauthenticated GitHub API requests with a lower rate limit.",
            file=sys.stderr,
        )

    table = generate_table(
        args.repo, repo_root, overrides_file, token=token, git_ref=args.git_ref
    )
    changed, diff = update_contributors_file(
        contributors_file, table=table, dry_run=args.dry_run
    )
    if args.dry_run:
        print(diff or "CONTRIBUTORS.md is already up to date.")
    elif changed:
        print(f"Updated {contributors_file.relative_to(repo_root)}")
    else:
        print("CONTRIBUTORS.md is already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())