import json

import pytest

from scripts import update_contributors as updater


def issue(
    number: int,
    author: str = "reporter",
    labels: tuple[str, ...] = ("bug",),
    url: str | None = None,
) -> updater.Issue:
    return updater.Issue(
        number=number,
        author=author,
        labels=frozenset(labels),
        url=url or f"https://github.com/AnyCredit5518/riplex/issues/{number}",
    )


def test_rank_for_count() -> None:
    assert updater.rank_for_count(1) == "🧪"
    assert updater.rank_for_count(3) == "🧪"
    assert updater.rank_for_count(4) == "🐛"
    assert updater.rank_for_count(8) == "🔍"
    assert updater.rank_for_count(15) == "🛡️"
    assert updater.rank_for_count(25) == "💎"


def test_extract_issue_references_from_commit_text() -> None:
    text = """
    fix(metadata): rank TMDb search by relevance (#22)

    Closes #17 and resolves #20.
    Mention issue #21 in the packaging notes.
    """

    assert updater.extract_issue_references(text) == frozenset({17, 20, 21, 22})


def test_eligible_issues_require_bug_reference_or_manual_include() -> None:
    issues = [
        issue(1, author="manual", labels=()),
        issue(2, author="strict", labels=("bug",)),
        issue(3, author="support", labels=()),
        issue(4, author="AnyCredit5518", labels=("bug",)),
        issue(5, author="dependabot[bot]", labels=("bug",)),
        issue(6, author="excluded", labels=("bug",)),
    ]
    overrides = updater.Overrides(include=frozenset({1}), exclude=frozenset({6}))

    selected = updater.eligible_issues(
        issues, referenced_issue_numbers=frozenset({2, 3, 4, 5, 6}), overrides=overrides
    )

    assert [(selected_issue.number, selected_issue.author) for selected_issue in selected] == [
        (1, "manual"),
        (2, "strict"),
    ]


def test_build_contributors_sorts_by_count_then_username() -> None:
    contributors = updater.build_contributors(
        [
            issue(9, author="zeta"),
            issue(1, author="Alpha"),
            issue(3, author="beta"),
            issue(2, author="Alpha"),
        ]
    )

    assert [(contributor.username, contributor.issue_numbers) for contributor in contributors] == [
        ("Alpha", (1, 2)),
        ("beta", (3,)),
        ("zeta", (9,)),
    ]


def test_render_table_links_users_and_issues() -> None:
    table = updater.render_table(
        [
            updater.Contributor(
                username="JelloEmperor",
                issue_numbers=(1, 5, 6, 7),
                issue_urls={
                    1: "https://github.com/AnyCredit5518/riplex/issues/1",
                    5: "https://github.com/AnyCredit5518/riplex/issues/5",
                    6: "https://github.com/AnyCredit5518/riplex/issues/6",
                    7: "https://github.com/AnyCredit5518/riplex/issues/7",
                },
            )
        ]
    )

    assert table.splitlines()[0] == "| User | Issues |"
    assert "🐛 [@JelloEmperor](https://github.com/JelloEmperor)" in table
    assert "[#7](https://github.com/AnyCredit5518/riplex/issues/7)" in table


def test_replace_marker_block_preserves_surrounding_content() -> None:
    original = f"before\n{updater.START_MARKER}\nold table\n{updater.END_MARKER}\nafter\n"

    updated = updater.replace_marker_block(original, "new table")

    assert updated == f"before\n{updater.START_MARKER}\nnew table\n{updater.END_MARKER}\nafter\n"


def test_replace_marker_block_requires_ordered_markers() -> None:
    with pytest.raises(ValueError, match="Could not find"):
        updater.replace_marker_block("no markers", "table")


def test_update_contributors_file_dry_run_does_not_write(tmp_path) -> None:
    contributors_file = tmp_path / "CONTRIBUTORS.md"
    contributors_file.write_text(
        f"before\n{updater.START_MARKER}\nold table\n{updater.END_MARKER}\nafter\n",
        encoding="utf-8",
    )

    changed, diff = updater.update_contributors_file(
        contributors_file, "new table", dry_run=True
    )

    assert changed is True
    assert "new table" in diff
    assert "old table" in contributors_file.read_text(encoding="utf-8")


def test_load_overrides_accepts_number_objects_and_plain_numbers(tmp_path) -> None:
    overrides_file = tmp_path / "contributors-overrides.json"
    overrides_file.write_text(
        json.dumps(
            {
                "include": [{"number": 1, "reason": "fixture"}, 2],
                "exclude": [{"number": 3, "reason": "fixture"}],
            }
        ),
        encoding="utf-8",
    )

    overrides = updater.load_overrides(overrides_file)

    assert overrides == updater.Overrides(
        include=frozenset({1, 2}), exclude=frozenset({3})
    )


def test_parse_issue_ignores_pull_requests() -> None:
    assert updater.parse_issue({"number": 1, "pull_request": {}, "user": {"login": "u"}}) is None


def test_parse_issue_reads_author_labels_and_url() -> None:
    parsed = updater.parse_issue(
        {
            "number": 22,
            "user": {"login": "TallGeekyCool"},
            "labels": [{"name": "bug"}],
            "html_url": "https://github.com/AnyCredit5518/riplex/issues/22",
        }
    )

    assert parsed == issue(22, author="TallGeekyCool")


def test_fetch_closed_issues_uses_token_and_paginates(monkeypatch) -> None:
    requests = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, headers, timeout, follow_redirects):
            self.headers = headers
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def get(self, url, params):
            requests.append((self.headers, url, params))
            if params["page"] == 1:
                return FakeResponse(
                    [
                        {
                            "number": number,
                            "user": {"login": "reporter"},
                            "labels": [{"name": "bug"}],
                            "html_url": f"https://example.test/{number}",
                        }
                        for number in range(100)
                    ]
                )
            return FakeResponse(
                [
                    {
                        "number": 101,
                        "user": {"login": "reporter"},
                        "labels": [],
                        "html_url": "https://example.test/101",
                    },
                    {
                        "number": 102,
                        "pull_request": {},
                        "user": {"login": "reporter"},
                    },
                ]
            )

    monkeypatch.setattr(updater.httpx, "Client", FakeClient)

    issues = updater.fetch_closed_issues("AnyCredit5518/riplex", token="token-123")

    assert len(issues) == 101
    assert requests[0][0]["Authorization"] == "Bearer token-123"
    assert [request[2]["page"] for request in requests] == [1, 2]


def test_generate_table_combines_fetch_git_and_overrides(monkeypatch, tmp_path) -> None:
    overrides_file = tmp_path / "contributors-overrides.json"
    overrides_file.write_text(
        json.dumps({"include": [{"number": 8}], "exclude": []}), encoding="utf-8"
    )
    monkeypatch.setattr(
        updater,
        "fetch_closed_issues",
        lambda repo, token=None: [
            issue(8, author="manual", labels=()),
            issue(22, author="strict", labels=("bug",)),
        ],
    )
    monkeypatch.setattr(
        updater,
        "find_referenced_issues",
        lambda repo_root, git_ref=updater.DEFAULT_GIT_REF: frozenset({22}),
    )

    table = updater.generate_table(
        "AnyCredit5518/riplex", tmp_path, overrides_file, token=None
    )

    assert "[@manual]" in table
    assert "[@strict]" in table