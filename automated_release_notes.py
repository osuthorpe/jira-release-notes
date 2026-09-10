#!/usr/bin/env python3
"""
JIRA Release Notes Generator

Pulls the tickets for one or more fix versions from JIRA, rewrites each one as a
short plain-language release note with OpenAI, groups the notes into sections,
saves the page as HTML in output/, and, when configured, creates a Zendesk draft
article and posts the link to Slack.

Usage:
    python automated_release_notes.py                        # today's date as the fix version
    python automated_release_notes.py 06-12-2026             # one fix version
    python automated_release_notes.py 06-12-2026 06-05-2026  # several versions on one page
    python automated_release_notes.py --dry-run 06-12-2026   # generate only; skip Zendesk and Slack
    python automated_release_notes.py test                   # check access to each service

FIX_VERSION may also be given as an environment variable (comma-separated for several).
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from jira import JIRA
from llm_expect import llm_expect
from openai import OpenAI

load_dotenv()


class _CleanFormatter(logging.Formatter):
    """Plain lines for normal progress; a level prefix only for warnings and errors."""

    def format(self, record: logging.LogRecord) -> str:
        prefix = "" if record.levelno < logging.WARNING else f"{record.levelname}: "
        return prefix + super().format(record)


_handler = logging.StreamHandler()
_handler.setFormatter(_CleanFormatter("%(message)s"))
logging.basicConfig(level=logging.WARNING, handlers=[_handler])  # quiet third-party libraries
log = logging.getLogger("release_notes")
log.setLevel(os.getenv("LOG_LEVEL", "INFO"))

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
EVALS_DIR = BASE_DIR / "evals"

HTTP_TIMEOUT = 30  # seconds, applied to every Zendesk and Slack request
DEFAULT_MODEL = "gpt-4o"
FIX_VERSION_FORMATS = ("%m-%d-%Y", "%m-%d-%y")

# Which tickets count as release notes. Set JIRA_JQL_QUERY in .env to replace the whole query.
JIRA_PROJECT = "BPD"
JIRA_LABEL = "Release_Notes"

# Sections on the finished page, in display order. The model assigns each note to exactly
# one of these; sections with no notes are left out of the page.
GENERAL_SECTION = "General Bug Fixes and Enhancements"
SECTIONS = (GENERAL_SECTION, "Project Room", "Whiteboard", "Hackathon")

SUPPORT_PORTAL_URL = (
    "https://support.brightidea.com/hc/en-us/sections/200825397-Product-Release-Notes"
)


@dataclass
class Issue:
    key: str
    summary: str
    description: str
    issue_type: str
    labels: list[str]


# --- Fix versions and dates -----------------------------------------------------------------


def parse_versions(raw: str | None) -> list[str]:
    """Split a comma-separated FIX_VERSION value into a clean list."""
    if not raw:
        return []
    return [v.strip() for v in raw.split(",") if v.strip()]


def parse_version_date(fix_version: str) -> datetime:
    """Turn a fix version such as '06-12-2026' or '06-12-26' into a date."""
    for fmt in FIX_VERSION_FORMATS:
        try:
            return datetime.strptime(fix_version, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Fix version {fix_version!r} is not a date in MM-DD-YYYY form (for example 06-12-2026)."
    )


def day_suffix(day: int) -> str:
    if 11 <= day <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def long_date(date: datetime) -> str:
    """'June 12th, 2026'"""
    return f"{date:%B} {date.day}{day_suffix(date.day)}, {date.year}"


# --- JIRA -----------------------------------------------------------------------------------


def jira_credentials() -> tuple[str, str, str] | None:
    server = os.getenv("JIRA_SERVER")
    username = os.getenv("JIRA_USERNAME")
    token = os.getenv("JIRA_API_TOKEN")
    if server and username and token:
        return server, username, token
    return None


def build_jql(fix_versions: list[str]) -> str:
    """The default ticket query. Versions must be dates (digits and dashes) so the JQL is safe."""
    for version in fix_versions:
        if not re.fullmatch(r"[\d-]+", version):
            raise ValueError(f"Fix version {version!r} may only contain digits and dashes.")
    versions = ", ".join(f'"{v}"' for v in fix_versions)
    return (
        f'project = "{JIRA_PROJECT}" AND labels = {JIRA_LABEL} '
        f"AND fixVersion in ({versions}) ORDER BY key DESC"
    )


def plain_text(value: object) -> str:
    """JIRA descriptions arrive as text (API v2) or a document tree (API v3). Flatten either."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        own = value.get("text", "")
        children = " ".join(plain_text(child) for child in value.get("content", []))
        return f"{own} {children}".strip()
    if isinstance(value, list):
        return " ".join(plain_text(item) for item in value)
    return str(value)


def fetch_jira_issues(fix_versions: list[str]) -> list[Issue]:
    """Every ticket matching the query. Fails, rather than returning nothing, on an empty result."""
    creds = jira_credentials()
    if creds is None:
        raise RuntimeError("JIRA_SERVER, JIRA_USERNAME and JIRA_API_TOKEN must all be set in .env.")
    server, username, token = creds
    jql = os.getenv("JIRA_JQL_QUERY") or build_jql(fix_versions)

    log.info("Connecting to JIRA at %s", server)
    client = JIRA(server=server, basic_auth=(username, token))
    log.info("Running JQL: %s", jql)
    results = client.search_issues(
        jql,
        maxResults=False,  # follow every page instead of stopping at the first
        fields="summary,description,labels,issuetype",
    )

    issues = []
    for item in results:
        fields = item.raw.get("fields", {})
        issues.append(
            Issue(
                key=item.key,
                summary=fields.get("summary") or "",
                description=plain_text(fields.get("description")),
                issue_type=(fields.get("issuetype") or {}).get("name") or "",
                labels=[str(label) for label in fields.get("labels") or []],
            )
        )

    if not issues:
        raise RuntimeError(
            f"JIRA returned 0 issues for: {jql}\n"
            f"Check that the tickets have the {JIRA_LABEL} label and the right fix version, "
            "then re-run."
        )
    log.info("Fetched %d issues from JIRA", len(issues))
    return issues


# --- OpenAI ---------------------------------------------------------------------------------

_openai_client: OpenAI | None = None


def model_name() -> str:
    return os.getenv("OPENAI_MODEL") or DEFAULT_MODEL


def openai_client() -> OpenAI:
    """One shared client, created on first use so importing this module needs no key."""
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in .env.")
        _openai_client = OpenAI(api_key=api_key, max_retries=3, timeout=60)
    return _openai_client


SYSTEM_PROMPT = f"""You write customer-facing release notes for Brightidea, a software product.
You will be given one JIRA ticket. Respond with a JSON object containing three fields:

- "title": a short headline of 3 to 7 words in Title Case, with no ending punctuation.
- "note": exactly one sentence in plain language for a non-technical audience, usually starting
  with "We". Say what changed for the customer. Do not add details that are not in the ticket.
- "area": the section of the release notes this belongs in. Use "Whiteboard" for anything about
  the Whiteboard feature (tickets often abbreviate it "WB"), "Project Room" for the Project Room
  feature, "Hackathon" for the Hackathon feature, and "{GENERAL_SECTION}" for everything else.

Rules:
1. If the ticket's issue type is Bug, its area is not Whiteboard, and its labels do not include
   "global", the note must end with "for some systems" (or "that had affected some systems") so
   customers know the problem did not affect every instance. Otherwise do not add that phrase.
2. Expand abbreviations: WB means Whiteboard, VI means View Idea, RTE means Rich Text Editor,
   and so on. Never leave an abbreviation in the output.
3. Never include a person's name or a company or customer name.
4. Do not mention ticket numbers, internal system names, vulnerability identifiers, or
   implementation details such as database queries or API endpoints.
5. Plain text only: no HTML, no Markdown, no quotation marks around the sentence.

Examples of well-written output:
{{"title": "Addressed Confusion with Team Workspace Submit", "note": "We removed the active Submit button from the Team Workspace page when Submission is turned off to reduce confusion.", "area": "{GENERAL_SECTION}"}}
{{"title": "View Idea 3 Dropdown Transparency Fix", "note": "We fixed a transparency issue within a dropdown on View Idea 3.", "area": "{GENERAL_SECTION}"}}
{{"title": "Restored Unordered List Button", "note": "We fixed the unresponsive Unordered List button in the Initiative-level Rich Text Editor 2.0 that had affected some systems.", "area": "{GENERAL_SECTION}"}}
{{"title": "Blue Diamond Gate Object", "note": "We updated the default Gate object to display a blue diamond emoji instead of an orange diamond.", "area": "{GENERAL_SECTION}"}}
{{"title": "Toggle Logic for Table Tool", "note": "We updated the logic in the Whiteboard Left Toolbar to ensure that the Tables feature is displayed when enabled.", "area": "Whiteboard"}}
"""  # noqa: E501

NOTE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "release_note",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "note": {"type": "string"},
                "area": {"type": "string", "enum": list(SECTIONS)},
            },
            "required": ["title", "note", "area"],
            "additionalProperties": False,
        },
    },
}

MAX_DESCRIPTION_CHARS = 6000  # plenty for a one-sentence note; bounds cost on huge tickets


def ticket_prompt(title: str, description: str, labels: list[str], issue_type: str) -> str:
    return (
        f"Issue type: {issue_type or 'Unknown'}\n"
        f"Labels: {', '.join(labels) if labels else 'none'}\n"
        f"Title: {title}\n"
        f"Description:\n{description.strip()[:MAX_DESCRIPTION_CHARS] or '(no description)'}"
    )


SCOPE_PHRASE = "for some systems"


def ensure_scope_phrase(note: dict[str, str], issue_type: str, labels: list[str]) -> dict[str, str]:
    """Guarantee rule 1 in code: a non-global Bug outside Whiteboard must say "for some systems".

    The model usually phrases this naturally; when it forgets, the phrase is added before the
    closing period so customers still learn the problem did not affect every instance.
    """
    is_bug = issue_type.strip().lower() == "bug"
    is_global = any(label.strip().lower() == "global" for label in labels)
    if not is_bug or is_global or note["area"] == "Whiteboard":
        return note
    if "some systems" in note["note"].lower():
        return note
    sentence = note["note"].strip().rstrip(".")
    return {**note, "note": f"{sentence} {SCOPE_PHRASE}."}


def write_note(
    title: str, description: str, labels: list[str], issue_type: str = ""
) -> dict[str, str]:
    """Ask the model for {"title", "note", "area"} describing one ticket. Raises on failure."""
    response = openai_client().chat.completions.create(
        model=model_name(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": ticket_prompt(title, description, labels, issue_type)},
        ],
        response_format=NOTE_SCHEMA,
        max_completion_tokens=300,
    )
    message = response.choices[0].message
    if not message.content:
        raise RuntimeError(f"OpenAI returned no note for {title!r}: {message.refusal or 'empty'}")
    note = json.loads(message.content)
    if note.get("area") not in SECTIONS:
        note["area"] = GENERAL_SECTION
    return ensure_scope_phrase(note, issue_type, labels)


def note_html(note: dict[str, str]) -> str:
    """'<strong>Title-</strong> Sentence.' Both parts are escaped, so model output is never HTML."""
    return (
        f"<strong>{html.escape(note['title'], quote=False)}-</strong> "
        f"{html.escape(note['note'], quote=False)}"
    )


@llm_expect(
    dataset=str(EVALS_DIR / "release_notes.jsonl"),
    tests=["accuracy", "instruction_adherence"],
    thresholds={"accuracy": 0.7, "instruction_adherence": 0.8},
    judge_provider="openai",
    judge_model=model_name(),
)
def create_release_note(
    title: str, description: str, labels: list[str], issue_type: str = ""
) -> str:
    """One finished release note as HTML. This is the function the LLM evaluation exercises."""
    return note_html(write_note(title, description, labels, issue_type))


# --- Page -----------------------------------------------------------------------------------


def group_notes(notes: list[dict[str, str]]) -> dict[str, list[str]]:
    """Section name -> note HTML, in SECTIONS order, with empty sections dropped."""
    grouped: dict[str, list[str]] = {section: [] for section in SECTIONS}
    for note in notes:
        section = note["area"] if note["area"] in grouped else GENERAL_SECTION
        grouped[section].append(note_html(note))
    return {section: items for section, items in grouped.items() if items}


def build_page(release_date: datetime, sections: dict[str, list[str]]) -> str:
    """The article body: two intro paragraphs, then a heading and list for each section."""
    date_text = f"{release_date:%A}, {long_date(release_date)}"
    parts = [
        (
            f"<p>Our latest product release took effect <strong>{date_text}.</strong> "
            "This post may be different from the release notes received via email.</p>"
        ),
        (
            "<p>To read Brightidea's complete documentation, you can visit the "
            f'<a href="{SUPPORT_PORTAL_URL}">Product Release Notes</a> '
            "forum in the Support Portal.</p>"
        ),
    ]
    for section, items in sections.items():
        parts.append(f"<p><strong>{html.escape(section, quote=False)}</strong></p>")
        parts.append("<ul>\n" + "\n".join(f"<li>{item}</li>" for item in items) + "\n</ul>")
    return "\n".join(parts) + "\n"


def save_page(body: str, release_date: datetime) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"release_notes_{release_date:%Y-%m-%d}.html"
    path.write_text(body, encoding="utf-8")
    return path


# --- Zendesk --------------------------------------------------------------------------------


def zendesk_settings() -> dict | None:
    subdomain = os.getenv("ZENDESK_SUBDOMAIN")
    email = os.getenv("ZENDESK_EMAIL")
    token = os.getenv("ZENDESK_API_TOKEN")
    section_id = os.getenv("ZENDESK_SECTION_ID")
    if not (subdomain and email and token and section_id):
        return None
    return {
        "base": f"https://{subdomain}.zendesk.com",
        "auth": (f"{email}/token", token),
        "section_id": section_id,
        "permission_group_id": os.getenv("ZENDESK_PERMISSION_GROUP_ID"),
    }


def find_existing_article(zd: dict, title: str) -> dict | None:
    """The newest article in the section with exactly this title, or None."""
    url = f"{zd['base']}/api/v2/help_center/sections/{zd['section_id']}/articles.json"
    params = {"sort_by": "created_at", "sort_order": "desc", "per_page": 100}
    response = requests.get(url, auth=zd["auth"], params=params, timeout=HTTP_TIMEOUT)
    if not response.ok:
        raise RuntimeError(
            f"Zendesk error {response.status_code} listing articles: {response.text[:500]}"
        )
    for article in response.json().get("articles", []):
        if article.get("title") == title:
            return article
    return None


def publish_to_zendesk(title: str, body: str) -> str | None:
    """Create or update a DRAFT article and return its URL; None when Zendesk is not configured.

    Never touches an article that has already been published: that would silently change what
    customers see, so the run stops with an error instead.
    """
    zd = zendesk_settings()
    if zd is None:
        log.info("Zendesk is not configured; skipping.")
        return None

    existing = find_existing_article(zd, title)
    if existing and not existing.get("draft", False):
        raise RuntimeError(
            f"A Zendesk article titled {title!r} is already published "
            f"({existing.get('html_url')}). Refusing to overwrite live content. "
            "Edit that article in Zendesk, or delete it and re-run."
        )

    if existing:
        article_id = existing["id"]
        url = f"{zd['base']}/api/v2/help_center/articles/{article_id}/translations/en-us.json"
        payload = {"translation": {"title": title, "body": body, "draft": True}}
        log.info("Updating existing Zendesk draft %s", article_id)
        response = requests.put(url, json=payload, auth=zd["auth"], timeout=HTTP_TIMEOUT)
    else:
        url = f"{zd['base']}/api/v2/help_center/sections/{zd['section_id']}/articles.json"
        article: dict = {
            "title": title,
            "body": body,
            "locale": "en-us",
            "draft": True,
            "user_segment_id": None,
        }
        if zd["permission_group_id"]:
            article["permission_group_id"] = int(zd["permission_group_id"])
        payload = {"article": article, "notify_subscribers": False}
        log.info("Creating Zendesk draft: %s", title)
        response = requests.post(url, json=payload, auth=zd["auth"], timeout=HTTP_TIMEOUT)

    if not response.ok:
        raise RuntimeError(f"Zendesk error {response.status_code}: {response.text[:500]}")
    if not existing:
        article_id = response.json()["article"]["id"]
    return f"{zd['base']}/hc/en-us/articles/{article_id}"


# --- Slack ----------------------------------------------------------------------------------


def post_to_slack(title: str, url: str) -> bool:
    """Post the draft link. Returns False (and logs why) when skipped or rejected."""
    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")
    if not token:
        return False
    if not channel:
        log.warning("SLACK_BOT_TOKEN is set but SLACK_CHANNEL is not; skipping Slack.")
        return False

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel, "text": f"*{title}*\n{url}"},
        timeout=HTTP_TIMEOUT,
    )
    try:
        data = response.json()
    except ValueError:
        data = {"ok": False, "error": f"HTTP {response.status_code}"}
    if not data.get("ok"):
        log.error("Slack rejected the message: %s", data.get("error"))
        return False
    log.info("Posted to Slack channel %s", channel)
    return True


# --- Pipeline -------------------------------------------------------------------------------


def generate(fix_versions: list[str] | None = None, dry_run: bool = False) -> Path:
    """Run the whole pipeline and return the path of the saved HTML page."""
    fix_versions = fix_versions or [datetime.today().strftime("%m-%d-%Y")]
    # Validate everything we can before any network call or OpenAI spend.
    release_date = max(parse_version_date(v) for v in fix_versions)
    openai_client()
    if len(fix_versions) > 1:
        log.info("Combining %d fix versions into one page: %s", len(fix_versions), fix_versions)

    issues = fetch_jira_issues(fix_versions)

    log.info("Writing %d release notes with %s", len(issues), model_name())
    notes = []
    for i, issue in enumerate(issues, 1):
        log.info("  [%d/%d] %s: %s", i, len(issues), issue.key, issue.summary[:60])
        notes.append(write_note(issue.summary, issue.description, issue.labels, issue.issue_type))

    title = f"Product Release Notes - {long_date(release_date)}"
    body = build_page(release_date, group_notes(notes))
    path = save_page(body, release_date)
    log.info("Saved: %s", path)

    if dry_run:
        log.info("Dry run: skipping Zendesk and Slack.")
        return path

    article_url = publish_to_zendesk(title, body)
    if article_url:
        log.info("Zendesk draft: %s", article_url)
        post_to_slack(title, article_url)
    return path


# --- Connection check -----------------------------------------------------------------------


def check_connections() -> bool:
    """Try each configured service with a harmless read. Returns True when nothing failed."""
    failed = False

    def report(status: str, service: str, detail: str) -> None:
        nonlocal failed
        failed = failed or status == "FAIL"
        log.info("[%s] %-8s %s", status, service, detail)

    creds = jira_credentials()
    if creds is None:
        report("SKIP", "JIRA", "credentials not set")
    else:
        try:
            me = JIRA(server=creds[0], basic_auth=creds[1:]).myself()
            report("OK", "JIRA", f"{me.get('displayName')} <{me.get('emailAddress')}>")
        except Exception as exc:  # report every failure the same way
            report("FAIL", "JIRA", str(exc))

    if not os.getenv("OPENAI_API_KEY"):
        report("SKIP", "OpenAI", "OPENAI_API_KEY not set")
    else:
        try:
            model = openai_client().models.retrieve(model_name())
            report("OK", "OpenAI", f"model {model.id} available")
        except Exception as exc:
            report("FAIL", "OpenAI", str(exc))

    zd = zendesk_settings()
    if zd is None:
        report("SKIP", "Zendesk", "credentials not set")
    else:
        try:
            url = f"{zd['base']}/api/v2/help_center/sections/{zd['section_id']}.json"
            response = requests.get(url, auth=zd["auth"], timeout=HTTP_TIMEOUT)
            if response.ok:
                name = response.json().get("section", {}).get("name")
                report("OK", "Zendesk", f"section {zd['section_id']}: {name}")
            else:
                report("FAIL", "Zendesk", f"{response.status_code}: {response.text[:200]}")
        except Exception as exc:
            report("FAIL", "Zendesk", str(exc))

    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        report("SKIP", "Slack", "SLACK_BOT_TOKEN not set")
    else:
        try:
            response = requests.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
                timeout=HTTP_TIMEOUT,
            )
            data = response.json()
            if data.get("ok"):
                channel = os.getenv("SLACK_CHANNEL") or "SLACK_CHANNEL NOT SET"
                detail = f"bot {data.get('user')} in {data.get('team')} (channel {channel})"
                report("OK", "Slack", detail)
            else:
                report("FAIL", "Slack", str(data.get("error")))
        except Exception as exc:
            report("FAIL", "Slack", str(exc))

    return not failed


# --- Command line ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--dry-run"]
    dry_run = len(args) != len(argv)
    if args and args[0] == "test":
        return 0 if check_connections() else 1

    versions = parse_versions(",".join(args)) or parse_versions(os.getenv("FIX_VERSION"))
    try:
        generate(versions or None, dry_run=dry_run)
    except Exception as exc:  # a clean message beats a traceback for operators
        log.error("%s", exc, exc_info=log.isEnabledFor(logging.DEBUG))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
