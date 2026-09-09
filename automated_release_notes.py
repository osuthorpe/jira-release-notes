#!/usr/bin/env python3
"""
JIRA Release Notes Generator

Drop a JIRA CSV export into jira-exports/, run this script, get HTML in output/.
"""

import os
import glob
import re
import time
import logging
from datetime import datetime
from typing import List, Dict, Any
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv
from jira import JIRA
import requests
from llm_expect import llm_expect

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JIRA_EXPORTS_DIR = os.path.join(BASE_DIR, 'jira-exports')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
EVALS_DIR = os.path.join(BASE_DIR, 'evals')


def retry(max_retries=3, delay=2, backoff=2):
    """Retry decorator with exponential backoff."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            retries = 0
            current_delay = delay
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries >= max_retries:
                        raise
                    logger.warning(f"Attempt {retries} failed: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
        return wrapper
    return decorator


def strip_code_fences(text: str) -> str:
    return re.sub(r'```\w*\n?', '', text).strip()


def get_day_suffix(day: int) -> str:
    if 4 <= day <= 20 or 24 <= day <= 30:
        return "th"
    return ["st", "nd", "rd"][day % 10 - 1]


def format_date(date_obj: datetime = None) -> tuple:
    if date_obj is None:
        date_obj = datetime.today()
    day = date_obj.day
    month = date_obj.strftime("%B")
    year = date_obj.year
    day_of_week = date_obj.strftime("%A")
    return day_of_week, f"{month} {day}{get_day_suffix(day)}, {year}"


def find_latest_csv() -> str:
    csv_files = glob.glob(os.path.join(JIRA_EXPORTS_DIR, '*.csv'))
    if not csv_files:
        return None
    return max(csv_files, key=os.path.getmtime)


def parse_version_date(fix_version: str) -> datetime:
    """Parse a fix-version string like '06-01-2026' or '06-01-26' into a date."""
    for fmt in ('%m-%d-%Y', '%m-%d-%y'):
        try:
            return datetime.strptime(fix_version, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized fix version date format: {fix_version!r}")


def get_fix_version_env() -> str:
    """Read the fix version from the environment, accepting upper- or lowercase var name."""
    return os.getenv('FIX_VERSION') or os.getenv('fix_version')


def parse_versions(raw: str) -> List[str]:
    """Split a comma-separated FIX_VERSION value into a clean list of versions."""
    if not raw:
        return []
    return [v.strip() for v in raw.split(',') if v.strip()]


def fetch_jira_issues(fix_versions: List[str] = None) -> List[Dict[str, Any]]:
    server = os.getenv('JIRA_SERVER')
    username = os.getenv('JIRA_USERNAME')
    token = os.getenv('JIRA_API_TOKEN')
    jql = os.getenv('JIRA_JQL_QUERY')

    if not all([server, username, token]):
        return None

    logger.info(f"Connecting to JIRA: {server}")
    client = JIRA(server=server, basic_auth=(username, token))

    if not jql:
        if not fix_versions:
            fix_versions = [datetime.today().strftime('%m-%d-%Y')]
        version_list = ', '.join(f'"{v}"' for v in fix_versions)
        jql = (f'project = "BPD" AND labels = Release_Notes '
               f'AND fixVersion in ({version_list}) '
               f'ORDER BY key DESC, created DESC')

    logger.info(f"Running JQL: {jql}")
    results = client.search_issues(
        jql, maxResults=100,
        fields='summary,description,labels,issuetype,status'
    )

    issues = []
    for issue in results:
        labels = [str(l) for l in issue.fields.labels] if issue.fields.labels else []
        issues.append({
            'key': issue.key,
            'summary': issue.fields.summary,
            'description': issue.fields.description or '',
            'labels': labels,
        })

    logger.info(f"Fetched {len(issues)} issues from JIRA")
    if not issues:
        raise RuntimeError(
            f"JIRA returned 0 issues for JQL: {jql}\n"
            "Refusing to fall back to a CSV export. Check that the tickets have the "
            "Release_Notes label and the correct fix version, then re-run."
        )
    return issues


def read_csv(csv_path: str) -> List[Dict[str, Any]]:
    logger.info(f"Reading: {csv_path}")
    df = pd.read_csv(csv_path)
    issues = []
    for _, row in df.iterrows():
        issues.append({
            'key': row.get('Issue key', 'N/A'),
            'summary': row.get('Summary', ''),
            'description': row.get('Description', ''),
            'labels': row.get('Labels', '').split(',') if pd.notna(row.get('Labels')) else [],
        })
    logger.info(f"Found {len(issues)} issues")
    return issues


@retry(max_retries=3, delay=2)
def call_openai(client, messages, max_tokens=500):
    return client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=max_tokens,
        timeout=30
    )


@llm_expect(
    dataset=os.path.join(EVALS_DIR, 'release_notes.jsonl'),
    tests=["accuracy", "instruction_adherence"],
    thresholds={"accuracy": 0.7, "instruction_adherence": 0.8},
    judge_provider="openai",
    judge_model="gpt-4o",
)
def create_release_note(client, title: str, description: str, labels: List[str]) -> str:
    labels_str = ', '.join(labels) if labels else 'No labels'
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content":
            f"Create a single-sentence release note for the following issue:\n\n"
            f"Title: {title}\nDescription: {description}.\n\n"
            f"If it is a bug and not labeled with 'global' then make sure we include the note 'for some systems. This rule only applies to non whiteboard issues.' "
            f"so people don't think it was broken in their instance as well."
            f"Here are the labels for the issue {labels_str} \n\n"
            f"The note should be in plane language and be as short as possible. Assume this is a non-technical audience.\n"
            f"Please avoid rephrasing or expanding on my statements. Just provide the specific term or concept I'm asking for without additional context or suggestions.\n"
            f"If the title has WB then it is for whiteboard.\n"
            f"DO NOT hullucinate.\n"
            f"DO NOT use any abbreviations, if you see VI make it View Idea, etc..\n\n"
            f"DO NOT include anyones name or any business names.\n"
            f"DO NOT inclue ``` or html anywhere in the response.\n"
            f"ONLY return valid HTML, nothing outside of the <ul></ul> elements.\n"
            f"Here are 5 examples of really well written release notes:\n"
            f"<strong>Addressed Confusion with Team Workspace Submit-</strong> We removed the active Submit button from the Team Workspace page when Submission is turned off to reduce confusion.\n"
            f"<strong>View Idea 3 Dropdown Transparency Fix-</strong> We fixed a transparency issue within a dropdown on View Idea 3.\n"
            f"<strong>Restored Unordered List Button-</strong> We fixed the unresponsive Unordered List button in the Initiative-level Rich Text Editor 2.0 that had affected some systems.\n"
            f"<strong>Blue Diamond Gate Object-</strong> We updated the default Gate object to display a blue diamond emoji instead of an orange diamond.\n"
            f"<strong>Toggle Logic for Table Tool-</strong> We updated the logic in the Whiteboard Left Toolbar to ensure that Tables feature is displayed when enabled."
        }
    ]
    try:
        response = call_openai(client, messages)
        return strip_code_fences(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Failed to generate note for '{title}': {e}")
        return f"<strong>{title}-</strong> Issue resolved."


def categorize_notes(client, release_notes: str) -> str:
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content":
            f"Categorize the following release notes into sections like:"
            f"'General bug fixes and enhancements', 'Project Room', 'Whiteboard', and 'Hackathon':\n\n"
            f"{release_notes}.\n\n"
            f"Make sure to return the list in the correct HTML format:\n\n"
            f"<p><strong>Category Title</strong></p>"
            f"<ul>"
            f"<li>Release note.</li>"
            f"<li>Release note</li>"
            f"<li>...</li>"
            f"</ul>"
            f"DO NOT inclue ``` or html anywhere in the response.\n"
        }
    ]
    try:
        response = call_openai(client, messages, max_tokens=4096)
        return strip_code_fences(response.choices[0].message.content)
    except Exception as e:
        logger.error(f"Failed to categorize: {e}")
        return f"<p><strong>General bug fixes and enhancements</strong></p><ul>{release_notes}</ul>"


def generate(csv_path: str = None, fix_versions: List[str] = None):
    """Generate one combined release-notes page across the given fix versions.

    Pulls from the JIRA API if configured (and fails if it matches no issues);
    uses the newest CSV in jira-exports/ only when JIRA creds are not set.
    """
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in .env file")

    client = OpenAI(api_key=api_key)

    issues = None

    # Use the JIRA API when creds are set (and no explicit CSV given).
    # fetch_jira_issues returns None only when creds are missing; it raises
    # if JIRA is reachable but matches nothing, so we never silently publish
    # a stale CSV export.
    if csv_path is None:
        issues = fetch_jira_issues(fix_versions)
        if issues is not None:
            print(f"Pulled {len(issues)} issues from JIRA API")

    # CSV is only used when JIRA creds are not configured or a CSV was passed explicitly
    if issues is None:
        if csv_path is None:
            csv_path = find_latest_csv()
        if csv_path is None:
            print("No JIRA creds configured and no CSV files in jira-exports/.")
            return
        issues = read_csv(csv_path)

    if not issues:
        print("No issues found.")
        return

    # Generate individual release notes
    print(f"Processing {len(issues)} issues...")
    all_notes = ""
    for i, issue in enumerate(issues, 1):
        print(f"  [{i}/{len(issues)}] {issue['summary'][:60]}")
        note = create_release_note(client, issue['summary'], issue['description'], issue['labels'])
        all_notes += f"<li>{note}</li>\n"

    # Categorize
    print("Categorizing...")
    categorized = categorize_notes(client, all_notes)

    # Build HTML — use the most recent fix version date if set, else today
    fix_versions = fix_versions or parse_versions(get_fix_version_env())
    if fix_versions:
        release_date = max(parse_version_date(v) for v in fix_versions)
    else:
        release_date = datetime.today()
    day_of_week, formatted_date = format_date(release_date)
    title = f"Product Release Notes - {formatted_date}"

    body = f"""<p>Our latest product release took effect <strong>{day_of_week}, {formatted_date}.</strong> This post may be different from the release notes received via email.</p>
<p>To read Brightidea's complete documentation, you can visit the <a href="https://support.brightidea.com/hc/en-us/sections/200825397-Product-Release-Notes">Product Release Notes</a> forum in the Support Portal.</p>
{categorized}
"""

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip().replace(' ', '_')
    filename = f"{safe_title}_{release_date.strftime('%m_%d_%Y')}.html"
    file_path = os.path.join(OUTPUT_DIR, filename)

    full_html = body

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(full_html)

    print(f"\nDone! Output saved to: {file_path}")

    # Publish to Zendesk if configured
    zendesk_url = publish_to_zendesk(title, body)
    if zendesk_url:
        print(f"\nZendesk draft created: \033]8;;{zendesk_url}\033\\{zendesk_url}\033]8;;\033\\")
        post_to_slack(title, zendesk_url)

    return file_path


def publish_to_zendesk(title: str, body: str) -> str:
    subdomain = os.getenv('ZENDESK_SUBDOMAIN')
    email = os.getenv('ZENDESK_EMAIL')
    token = os.getenv('ZENDESK_API_TOKEN')
    section_id = os.getenv('ZENDESK_SECTION_ID')

    if not all([subdomain, email, token, section_id]):
        return None

    auth = (f"{email}/token", token)
    headers = {"Content-Type": "application/json"}
    permission_group_id = os.getenv('ZENDESK_PERMISSION_GROUP_ID')

    # Check if article with same title already exists in this section
    existing_id = find_existing_article(subdomain, auth, section_id, title)

    if existing_id:
        # Update existing article
        url = f"https://{subdomain}.zendesk.com/api/v2/help_center/articles/{existing_id}/translations/en-us"
        payload = {"translation": {"body": body, "title": title}}
        logger.info(f"Updating existing Zendesk article {existing_id}: {title}")
        response = requests.put(url, json=payload, auth=auth, headers=headers)
    else:
        # Create new article
        url = f"https://{subdomain}.zendesk.com/api/v2/help_center/sections/{section_id}/articles"
        payload = {
            "article": {
                "title": title,
                "body": body,
                "locale": "en-us",
                "draft": True,
                "user_segment_id": None,
            },
            "notify_subscribers": False,
        }
        if permission_group_id:
            payload["article"]["permission_group_id"] = int(permission_group_id)
        logger.info(f"Creating new Zendesk article: {title}")
        response = requests.post(url, json=payload, auth=auth, headers=headers)

    if not response.ok:
        logger.error(f"Zendesk error: {response.status_code} - {response.text}")
        response.raise_for_status()

    if existing_id:
        article_id = existing_id
    else:
        article_id = response.json()["article"]["id"]

    article_url = f"https://{subdomain}.zendesk.com/hc/en-us/articles/{article_id}"
    logger.info(f"Zendesk article {'updated' if existing_id else 'created'}: {article_url}")
    return article_url


def find_existing_article(subdomain, auth, section_id, title):
    url = f"https://{subdomain}.zendesk.com/api/v2/help_center/sections/{section_id}/articles"
    response = requests.get(url, auth=auth)
    if not response.ok:
        return None
    for article in response.json().get("articles", []):
        if article["title"] == title:
            return article["id"]
    return None


def post_to_slack(title: str, zendesk_url: str):
    token = os.getenv('SLACK_BOT_TOKEN')
    channel = os.getenv('SLACK_CHANNEL', 'C03BD30JG58')

    if not token:
        return

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "channel": channel,
            "text": f"*{title}*\n{zendesk_url}",
        },
    )
    data = response.json()
    if data.get("ok"):
        print(f"Posted to Slack: #{channel}")
    else:
        logger.error(f"Slack error: {data.get('error')}")


def test_connections():
    """Verify access to JIRA, Zendesk, and Slack."""
    ok = True

    # JIRA
    server = os.getenv('JIRA_SERVER')
    username = os.getenv('JIRA_USERNAME')
    token = os.getenv('JIRA_API_TOKEN')
    if not all([server, username, token]):
        print("[SKIP] JIRA  — creds not set")
    else:
        try:
            client = JIRA(server=server, basic_auth=(username, token))
            user = client.myself()
            print(f"[OK]   JIRA  — {user.get('displayName')} <{user.get('emailAddress')}>")
        except Exception as e:
            print(f"[FAIL] JIRA  — {e}")
            ok = False

    # Zendesk
    subdomain = os.getenv('ZENDESK_SUBDOMAIN')
    email = os.getenv('ZENDESK_EMAIL')
    zd_token = os.getenv('ZENDESK_API_TOKEN')
    section_id = os.getenv('ZENDESK_SECTION_ID')
    if not all([subdomain, email, zd_token, section_id]):
        print("[SKIP] Zendesk — creds not set")
    else:
        try:
            url = f"https://{subdomain}.zendesk.com/api/v2/help_center/sections/{section_id}.json"
            r = requests.get(url, auth=(f"{email}/token", zd_token), timeout=10)
            if r.ok:
                section = r.json().get('section', {})
                print(f"[OK]   Zendesk — section {section_id}: {section.get('name')}")
            else:
                print(f"[FAIL] Zendesk — {r.status_code}: {r.text}")
                ok = False
        except Exception as e:
            print(f"[FAIL] Zendesk — {e}")
            ok = False

    # Slack
    slack_token = os.getenv('SLACK_BOT_TOKEN')
    channel = os.getenv('SLACK_CHANNEL')
    if not slack_token:
        print("[SKIP] Slack — token not set")
    else:
        try:
            r = requests.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {slack_token}"},
                timeout=10,
            )
            data = r.json()
            if data.get("ok"):
                print(f"[OK]   Slack — bot {data.get('user')} in {data.get('team')} (channel: {channel})")
            else:
                print(f"[FAIL] Slack — {data.get('error')}")
                ok = False
        except Exception as e:
            print(f"[FAIL] Slack — {e}")
            ok = False

    return ok


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        sys.exit(0 if test_connections() else 1)

    versions = parse_versions(get_fix_version_env())
    if len(versions) > 1:
        print(f"Combining {len(versions)} versions into one page: {', '.join(versions)}")
    generate(fix_versions=versions or None)
