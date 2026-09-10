"""Unit tests. No network: every external call is mocked and env vars are controlled per test."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import automated_release_notes as rn

GENERAL = rn.GENERAL_SECTION

ALL_ENV = (
    "OPENAI_API_KEY", "OPENAI_MODEL", "JIRA_SERVER", "JIRA_USERNAME", "JIRA_API_TOKEN",
    "JIRA_JQL_QUERY", "ZENDESK_SUBDOMAIN", "ZENDESK_EMAIL", "ZENDESK_API_TOKEN",
    "ZENDESK_SECTION_ID", "ZENDESK_PERMISSION_GROUP_ID", "SLACK_BOT_TOKEN", "SLACK_CHANNEL",
    "FIX_VERSION",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Tests never see the developer's real .env values or a cached OpenAI client."""
    for key in ALL_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(rn, "_openai_client", None)


def _set_jira(monkeypatch):
    monkeypatch.setenv("JIRA_SERVER", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_USERNAME", "me@acme.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "token")


def _set_zendesk(monkeypatch):
    monkeypatch.setenv("ZENDESK_SUBDOMAIN", "acme")
    monkeypatch.setenv("ZENDESK_EMAIL", "me@acme.com")
    monkeypatch.setenv("ZENDESK_API_TOKEN", "token")
    monkeypatch.setenv("ZENDESK_SECTION_ID", "42")


def _response(status=200, payload=None):
    response = MagicMock()
    response.ok = status < 400
    response.status_code = status
    response.json.return_value = payload if payload is not None else {}
    response.text = json.dumps(payload or {})
    return response


def _completion(payload):
    response = MagicMock()
    response.choices[0].message.content = json.dumps(payload)
    response.choices[0].message.refusal = None
    return response


# --- Fix versions and dates -----------------------------------------------------------------


def test_parse_versions_splits_and_trims():
    assert rn.parse_versions(" 06-12-2026, 06-05-2026 ,") == ["06-12-2026", "06-05-2026"]
    assert rn.parse_versions("") == []
    assert rn.parse_versions(None) == []


@pytest.mark.parametrize("raw", ["06-12-2026", "06-12-26"])
def test_parse_version_date_accepts_both_year_forms(raw):
    assert rn.parse_version_date(raw) == datetime(2026, 6, 12)


def test_parse_version_date_rejects_other_formats():
    with pytest.raises(ValueError, match="not a date"):
        rn.parse_version_date("2026/06/12")


@pytest.mark.parametrize(
    "day,suffix",
    [(1, "st"), (2, "nd"), (3, "rd"), (4, "th"), (11, "th"), (12, "th"), (13, "th"),
     (21, "st"), (22, "nd"), (23, "rd"), (30, "th"), (31, "st")],
)
def test_day_suffix(day, suffix):
    assert rn.day_suffix(day) == suffix


def test_long_date():
    assert rn.long_date(datetime(2026, 6, 12)) == "June 12th, 2026"


# --- JIRA -----------------------------------------------------------------------------------


def test_build_jql_quotes_each_version():
    jql = rn.build_jql(["06-12-2026", "06-05-26"])
    assert 'project = "BPD"' in jql
    assert "labels = Release_Notes" in jql
    assert 'fixVersion in ("06-12-2026", "06-05-26")' in jql


def test_build_jql_rejects_anything_but_digits_and_dashes():
    with pytest.raises(ValueError):
        rn.build_jql(['06-12-2026" OR project = "X'])


def test_fetch_jira_issues_requires_credentials():
    with pytest.raises(RuntimeError, match="JIRA_SERVER"):
        rn.fetch_jira_issues(["06-12-2026"])


def _jira_item(key, summary, description, issue_type, labels):
    item = MagicMock()
    item.key = key
    item.raw = {
        "fields": {
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
            "labels": labels,
        }
    }
    return item


@patch("automated_release_notes.JIRA")
def test_fetch_jira_issues_maps_fields_and_follows_every_page(mock_jira, monkeypatch):
    _set_jira(monkeypatch)
    mock_jira.return_value.search_issues.return_value = [
        _jira_item("BPD-1", "WB - Fix crash", "Crash on paste", "Bug", ["Release_Notes"]),
        _jira_item("BPD-2", "New thing", None, "Improvement", []),
    ]

    issues = rn.fetch_jira_issues(["06-12-2026"])

    assert issues == [
        rn.Issue("BPD-1", "WB - Fix crash", "Crash on paste", "Bug", ["Release_Notes"]),
        rn.Issue("BPD-2", "New thing", "", "Improvement", []),
    ]
    kwargs = mock_jira.return_value.search_issues.call_args.kwargs
    assert kwargs["maxResults"] is False


@patch("automated_release_notes.JIRA")
def test_fetch_jira_issues_prefers_custom_jql(mock_jira, monkeypatch):
    _set_jira(monkeypatch)
    monkeypatch.setenv("JIRA_JQL_QUERY", "project = X")
    mock_jira.return_value.search_issues.return_value = [_jira_item("X-1", "s", "d", "Bug", [])]

    rn.fetch_jira_issues(["06-12-2026"])

    assert mock_jira.return_value.search_issues.call_args.args[0] == "project = X"


@patch("automated_release_notes.JIRA")
def test_fetch_jira_issues_fails_on_empty_result(mock_jira, monkeypatch):
    _set_jira(monkeypatch)
    mock_jira.return_value.search_issues.return_value = []
    with pytest.raises(RuntimeError, match="0 issues"):
        rn.fetch_jira_issues(["06-12-2026"])


def test_plain_text_handles_strings_trees_and_empty():
    tree = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "world"}]},
        ],
    }
    assert rn.plain_text(tree).split() == ["Hello", "world"]
    assert rn.plain_text("as is") == "as is"
    assert rn.plain_text(None) == ""


# --- OpenAI ---------------------------------------------------------------------------------


def test_openai_client_requires_key():
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        rn.openai_client()


def test_model_name_defaults_and_overrides(monkeypatch):
    assert rn.model_name() == rn.DEFAULT_MODEL
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    assert rn.model_name() == "gpt-test"


@patch("automated_release_notes.openai_client")
def test_write_note_sends_issue_type_and_labels_and_parses_json(mock_client):
    create = mock_client.return_value.chat.completions.create
    create.return_value = _completion(
        {"title": "Whiteboard Paste Fix", "note": "We fixed a crash.", "area": "Whiteboard"}
    )

    note = rn.write_note("WB - crash", "Crash on paste", ["Release_Notes"], "Bug")

    assert note == {
        "title": "Whiteboard Paste Fix", "note": "We fixed a crash.", "area": "Whiteboard",
    }
    kwargs = create.call_args.kwargs
    user_message = kwargs["messages"][-1]["content"]
    assert "Issue type: Bug" in user_message
    assert "Labels: Release_Notes" in user_message
    assert "Title: WB - crash" in user_message
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["model"] == rn.DEFAULT_MODEL


@patch("automated_release_notes.openai_client")
def test_write_note_unknown_area_falls_back_to_general(mock_client):
    mock_client.return_value.chat.completions.create.return_value = _completion(
        {"title": "T", "note": "N.", "area": "Somewhere Else"}
    )
    assert rn.write_note("t", "d", [], "Bug")["area"] == rn.GENERAL_SECTION


@patch("automated_release_notes.openai_client")
def test_write_note_raises_instead_of_inventing_a_note(mock_client):
    response = MagicMock()
    response.choices[0].message.content = None
    response.choices[0].message.refusal = "declined"
    mock_client.return_value.chat.completions.create.return_value = response
    with pytest.raises(RuntimeError, match="declined"):
        rn.write_note("t", "d", [], "Bug")


@patch("automated_release_notes.openai_client")
def test_create_release_note_returns_escaped_html(mock_client):
    mock_client.return_value.chat.completions.create.return_value = _completion(
        {"title": "Tables & Charts", "note": "We fixed <b>it</b>.", "area": rn.GENERAL_SECTION}
    )
    assert rn.create_release_note("t", "d", [], "Improvement") == (
        "<strong>Tables &amp; Charts-</strong> We fixed &lt;b&gt;it&lt;/b&gt;."
    )


@patch("automated_release_notes.openai_client")
def test_write_note_adds_scope_phrase_when_model_forgets_it(mock_client):
    mock_client.return_value.chat.completions.create.return_value = _completion(
        {"title": "Invite Email Fix", "note": "We fixed the invite email.", "area": GENERAL}
    )
    note = rn.write_note("t", "d", ["Release_Notes"], "Bug")
    assert note["note"] == "We fixed the invite email for some systems."


def _note(text, area=GENERAL):
    return {"title": "T", "note": text, "area": area}


@pytest.mark.parametrize(
    "issue_type,labels,area,text,expected",
    [
        ("Bug", ["Release_Notes"], GENERAL, "We fixed it.", "We fixed it for some systems."),
        ("Bug", ["Release_Notes"], GENERAL, "We fixed it", "We fixed it for some systems."),
        ("bug", [], "Project Room", "We fixed it.", "We fixed it for some systems."),
        ("Bug", ["Release_Notes", "GLOBAL"], GENERAL, "We fixed it.", "We fixed it."),
        ("Bug", [], "Whiteboard", "We fixed it.", "We fixed it."),
        ("Improvement", [], GENERAL, "We added it.", "We added it."),
        ("Bug", [], GENERAL, "We fixed it that had affected some systems.",
         "We fixed it that had affected some systems."),
    ],
)
def test_ensure_scope_phrase(issue_type, labels, area, text, expected):
    assert rn.ensure_scope_phrase(_note(text, area), issue_type, labels)["note"] == expected


# --- Page -----------------------------------------------------------------------------------


def test_group_notes_keeps_section_order_and_drops_empty_sections():
    notes = [
        {"title": "A", "note": "a.", "area": "Whiteboard"},
        {"title": "B", "note": "b.", "area": rn.GENERAL_SECTION},
        {"title": "C", "note": "c.", "area": "Whiteboard"},
    ]
    grouped = rn.group_notes(notes)
    assert list(grouped) == [rn.GENERAL_SECTION, "Whiteboard"]
    assert grouped["Whiteboard"] == ["<strong>A-</strong> a.", "<strong>C-</strong> c."]


def test_build_page_contains_date_sections_and_items():
    page = rn.build_page(datetime(2026, 6, 12), {"Whiteboard": ["<strong>A-</strong> a."]})
    assert "<strong>Friday, June 12th, 2026.</strong>" in page
    assert rn.SUPPORT_PORTAL_URL in page
    assert "<p><strong>Whiteboard</strong></p>" in page
    assert "<li><strong>A-</strong> a.</li>" in page


def test_save_page_writes_dated_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rn, "OUTPUT_DIR", tmp_path / "out")
    path = rn.save_page("<p>hi</p>", datetime(2026, 6, 12))
    assert path == tmp_path / "out" / "release_notes_2026-06-12.html"
    assert path.read_text(encoding="utf-8") == "<p>hi</p>"


# --- Zendesk --------------------------------------------------------------------------------


def test_publish_to_zendesk_skips_when_not_configured():
    assert rn.publish_to_zendesk("T", "<p>b</p>") is None


@patch("automated_release_notes.requests")
def test_publish_to_zendesk_creates_a_draft_when_no_title_matches(mock_requests, monkeypatch):
    _set_zendesk(monkeypatch)
    monkeypatch.setenv("ZENDESK_PERMISSION_GROUP_ID", "77")
    mock_requests.get.return_value = _response(
        200, {"articles": [{"id": 1, "title": "Other", "draft": True}]}
    )
    mock_requests.post.return_value = _response(201, {"article": {"id": 99}})

    url = rn.publish_to_zendesk("T", "<p>b</p>")

    assert url == "https://acme.zendesk.com/hc/en-us/articles/99"
    list_kwargs = mock_requests.get.call_args.kwargs
    assert list_kwargs["params"] == {"sort_by": "created_at", "sort_order": "desc", "per_page": 100}
    assert list_kwargs["timeout"] == rn.HTTP_TIMEOUT
    post_kwargs = mock_requests.post.call_args.kwargs
    assert post_kwargs["timeout"] == rn.HTTP_TIMEOUT
    article = post_kwargs["json"]["article"]
    assert article["draft"] is True
    assert article["title"] == "T"
    assert article["permission_group_id"] == 77
    assert post_kwargs["json"]["notify_subscribers"] is False


@patch("automated_release_notes.requests")
def test_publish_to_zendesk_updates_an_existing_draft(mock_requests, monkeypatch):
    _set_zendesk(monkeypatch)
    mock_requests.get.return_value = _response(
        200, {"articles": [{"id": 7, "title": "T", "draft": True}]}
    )
    mock_requests.put.return_value = _response(200, {})

    url = rn.publish_to_zendesk("T", "<p>b</p>")

    assert url == "https://acme.zendesk.com/hc/en-us/articles/7"
    put_args = mock_requests.put.call_args
    assert "articles/7/translations/en-us" in put_args.args[0]
    assert put_args.kwargs["json"]["translation"]["draft"] is True
    assert put_args.kwargs["timeout"] == rn.HTTP_TIMEOUT
    mock_requests.post.assert_not_called()


@patch("automated_release_notes.requests")
def test_publish_to_zendesk_refuses_to_overwrite_a_published_article(mock_requests, monkeypatch):
    _set_zendesk(monkeypatch)
    mock_requests.get.return_value = _response(
        200,
        {"articles": [{"id": 7, "title": "T", "draft": False, "html_url": "https://acme/7"}]},
    )
    with pytest.raises(RuntimeError, match="already published"):
        rn.publish_to_zendesk("T", "<p>b</p>")
    mock_requests.put.assert_not_called()
    mock_requests.post.assert_not_called()


@patch("automated_release_notes.requests")
def test_publish_to_zendesk_surfaces_api_errors(mock_requests, monkeypatch):
    _set_zendesk(monkeypatch)
    mock_requests.get.return_value = _response(200, {"articles": []})
    mock_requests.post.return_value = _response(422, {"error": "RecordInvalid"})
    with pytest.raises(RuntimeError, match="422"):
        rn.publish_to_zendesk("T", "<p>b</p>")


@patch("automated_release_notes.requests")
def test_publish_to_zendesk_fails_if_it_cannot_check_for_duplicates(mock_requests, monkeypatch):
    _set_zendesk(monkeypatch)
    mock_requests.get.return_value = _response(401, {"error": "Couldn't authenticate you"})
    with pytest.raises(RuntimeError, match="401"):
        rn.publish_to_zendesk("T", "<p>b</p>")
    mock_requests.post.assert_not_called()


# --- Slack ----------------------------------------------------------------------------------


def test_post_to_slack_skips_without_token():
    assert rn.post_to_slack("T", "https://x") is False


def test_post_to_slack_skips_without_channel(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    assert rn.post_to_slack("T", "https://x") is False


@patch("automated_release_notes.requests")
def test_post_to_slack_posts_to_the_configured_channel(mock_requests, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    monkeypatch.setenv("SLACK_CHANNEL", "C123")
    mock_requests.post.return_value = _response(200, {"ok": True})

    assert rn.post_to_slack("T", "https://x") is True

    kwargs = mock_requests.post.call_args.kwargs
    assert kwargs["json"] == {"channel": "C123", "text": "*T*\nhttps://x"}
    assert kwargs["headers"]["Authorization"] == "Bearer xoxb-1"
    assert kwargs["timeout"] == rn.HTTP_TIMEOUT


@patch("automated_release_notes.requests")
def test_post_to_slack_reports_api_errors(mock_requests, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-1")
    monkeypatch.setenv("SLACK_CHANNEL", "C123")
    mock_requests.post.return_value = _response(200, {"ok": False, "error": "not_in_channel"})
    assert rn.post_to_slack("T", "https://x") is False


# --- Pipeline and command line --------------------------------------------------------------


def test_generate_validates_fix_version_before_any_api_call():
    with pytest.raises(ValueError, match="not a date"):
        rn.generate(["2026/06/12"])


def test_generate_requires_openai_key_before_fetching(monkeypatch):
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        rn.generate(["06-12-2026"])


@patch("automated_release_notes.publish_to_zendesk")
@patch("automated_release_notes.write_note")
@patch("automated_release_notes.fetch_jira_issues")
def test_generate_dry_run_builds_the_page_and_skips_publishing(
    mock_fetch, mock_write, mock_publish, tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(rn, "OUTPUT_DIR", tmp_path)
    mock_fetch.return_value = [rn.Issue("BPD-1", "WB crash", "d", "Bug", [])]
    mock_write.return_value = {
        "title": "Whiteboard Crash Fix", "note": "We fixed it.", "area": "Whiteboard",
    }

    path = rn.generate(["06-05-2026", "06-12-2026"], dry_run=True)

    assert path.name == "release_notes_2026-06-12.html"  # the latest of the two versions
    page = path.read_text(encoding="utf-8")
    assert "<p><strong>Whiteboard</strong></p>" in page
    assert "<li><strong>Whiteboard Crash Fix-</strong> We fixed it.</li>" in page
    mock_fetch.assert_called_once_with(["06-05-2026", "06-12-2026"])
    mock_write.assert_called_once_with("WB crash", "d", [], "Bug")
    mock_publish.assert_not_called()


@patch("automated_release_notes.post_to_slack")
@patch("automated_release_notes.publish_to_zendesk", return_value="https://acme/hc/1")
@patch("automated_release_notes.write_note")
@patch("automated_release_notes.fetch_jira_issues")
def test_generate_publishes_and_notifies(
    mock_fetch, mock_write, mock_publish, mock_slack, tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(rn, "OUTPUT_DIR", tmp_path)
    mock_fetch.return_value = [rn.Issue("BPD-1", "s", "d", "Bug", [])]
    mock_write.return_value = {"title": "T", "note": "N.", "area": rn.GENERAL_SECTION}

    rn.generate(["06-12-2026"])

    title, body = mock_publish.call_args.args
    assert title == "Product Release Notes - June 12th, 2026"
    assert "<li><strong>T-</strong> N.</li>" in body
    mock_slack.assert_called_once_with(title, "https://acme/hc/1")


def test_main_collects_versions_and_dry_run_from_args(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        rn, "generate", lambda versions, dry_run: seen.update(versions=versions, dry_run=dry_run)
    )
    assert rn.main(["--dry-run", "06-12-2026", "06-05-2026"]) == 0
    assert seen == {"versions": ["06-12-2026", "06-05-2026"], "dry_run": True}


def test_main_falls_back_to_fix_version_env(monkeypatch):
    seen = {}
    monkeypatch.setenv("FIX_VERSION", "06-12-2026, 06-05-2026")
    monkeypatch.setattr(rn, "generate", lambda versions, dry_run: seen.update(versions=versions))
    assert rn.main([]) == 0
    assert seen == {"versions": ["06-12-2026", "06-05-2026"]}


def test_main_reports_errors_and_exits_nonzero(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(rn, "generate", boom)
    assert rn.main([]) == 1


def test_main_test_subcommand_runs_connection_check(monkeypatch):
    monkeypatch.setattr(rn, "check_connections", lambda: False)
    assert rn.main(["test"]) == 1
