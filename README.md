# JIRA Release Notes Generator

This tool turns Jira tickets into customer-friendly release notes — automatically.

When you run it, it:

1. Pulls the tickets for a release from Jira
2. Uses AI (OpenAI) to rewrite each ticket as a short, plain-language release note
3. Groups the notes into sections (General fixes, Project Room, Whiteboard, Hackathon)
4. Saves the finished page as an HTML file in the `output/` folder
5. Creates (or updates) a **draft** article in Zendesk — nothing is published to customers automatically, and the tool refuses to touch an article that has already been published
6. Posts a link to the draft in Slack so the team can review it

You only have to set things up once. After that, generating release notes is a single command.

---

## Part 1: One-time computer setup

You need a Mac with Python 3.11 or newer. Check with `python3 --version` in Terminal; if it is older or missing, install it with `brew install python` or from <https://www.python.org/downloads/>.

1. Open the **Terminal** app.
2. Download this project (if you haven't already) and go into its folder:

   ```bash
   cd ~/Documents/GitHub/jira-release-notes
   ```

3. Install everything the tool needs:

   ```bash
   make install
   ```

4. Create your personal settings file:

   ```bash
   make setup
   ```

   This creates a file called `.env`. This is where all your keys and passwords go (Parts 2–4 below explain how to get each one). Open it in any text editor — TextEdit is fine.

   > **Important:** The `.env` file contains secrets. Never email it, paste it in Slack, or commit it to GitHub.

---

## Part 2: Set up Jira (where the tickets come from)

### How tickets must be labeled in Jira

The tool only picks up tickets that meet **all three** of these rules:

| Rule | What to use |
| --- | --- |
| Project | **BPD** |
| Label | **Release_Notes** (exactly, with the underscore) |
| Fix Version | The release date, written as **MM-DD-YYYY** (example: `06-12-2026`) |

So before running the tool, make sure every ticket you want in the release notes:

- Is in the **BPD** project
- Has the label **Release_Notes**
- Has its **Fix Version** set to the release date (e.g. `06-12-2026`)

Tickets missing any of these will simply not appear in the notes.

> Tip: writing a clear ticket **Summary** and **Description** matters — the AI uses those, plus the ticket's issue type, to write the customer-facing note. If a bug only affected some customers, do **not** add the label `global`; the tool will then add "for some systems" wording so customers don't think their instance was broken.

### Get your Jira login details for the `.env` file

1. **JIRA_SERVER** — your company's Jira web address, e.g. `https://yourcompany.atlassian.net`
2. **JIRA_USERNAME** — the email address you use to log in to Jira
3. **JIRA_API_TOKEN** — a special password for tools like this one:
   1. Go to <https://id.atlassian.com/manage-profile/security/api-tokens>
   2. Click **Create API token**
   3. Give it a name like `release-notes`, click **Create**
   4. Click **Copy** and paste it into your `.env` file right away (you can't see it again later)

Your `.env` should now contain lines like:

```ini
JIRA_SERVER=https://yourcompany.atlassian.net
JIRA_USERNAME=you@yourcompany.com
JIRA_API_TOKEN=paste-your-token-here
```

> Advanced (optional): if you ever need to pull tickets from a different project or with different rules, you can add a `JIRA_JQL_QUERY=` line to replace the default query entirely. Most people should leave this out.

---

## Part 3: Set up Zendesk (where the draft article goes)

You need a Zendesk account with permission to create Help Center articles.

1. **ZENDESK_SUBDOMAIN** — the first part of your Zendesk web address. If you go to `https://brightidea.zendesk.com`, the subdomain is `brightidea`.
2. **ZENDESK_EMAIL** — the email address you use to log in to Zendesk.
3. **ZENDESK_API_TOKEN** — created by a Zendesk admin:
   1. In Zendesk, open **Admin Center** (the gear/four-squares icon)
   2. Go to **Apps and integrations → APIs → Zendesk API**
   3. Make sure **Token access** is enabled
   4. Click **Add API token**, give it a description like `release-notes`, and copy the token into your `.env` file (it's only shown once)
4. **ZENDESK_SECTION_ID** — the section of the Help Center where release notes live:
   1. In your browser, open the **Product Release Notes** section of the Support Portal
   2. Look at the web address — it contains a long number, e.g. `.../sections/200825397-Product-Release-Notes`
   3. That number (`200825397`) is the section ID
5. **ZENDESK_PERMISSION_GROUP_ID** *(optional)* — only needed if your Help Center requires articles to belong to a permission group. A Zendesk admin can find this under **Admin Center → Help Center → Permission groups** (the number is in the web address when you click a group). If you're not sure, leave it out and add it only if the tool reports an error about permission groups.

Your `.env` should now also contain:

```ini
ZENDESK_SUBDOMAIN=brightidea
ZENDESK_EMAIL=you@yourcompany.com
ZENDESK_API_TOKEN=paste-your-token-here
ZENDESK_SECTION_ID=200825397
```

The tool always creates the Zendesk article as a **draft**. A person still reviews and publishes it.

- If a **draft** with the same title already exists (for example, you run the tool twice for the same release), it updates that draft instead of creating a duplicate.
- If an article with the same title has already been **published**, the tool stops with an error rather than overwriting what customers can see. Edit the live article in Zendesk, or delete it and run the tool again.

---

## Part 4: Set up OpenAI and Slack

### OpenAI (required — this writes the notes)

1. Go to <https://platform.openai.com/api-keys>
2. Sign in (or ask whoever manages the company OpenAI account)
3. Click **Create new secret key**, copy it, and add it to `.env`:

```ini
OPENAI_API_KEY=paste-your-key-here
```

> Optional: add `OPENAI_MODEL=` to choose a different model. If you leave it out, the tool uses `gpt-4o`.

### Slack (optional — posts the draft link for review)

If you skip this, everything still works; you just won't get the Slack message. If you set it up, you need **both** values.

1. **SLACK_BOT_TOKEN** — a bot token starting with `xoxb-`. Ask whoever manages your Slack apps, or create one at <https://api.slack.com/apps> (the app needs the `chat:write` permission and must be invited to the channel).
2. **SLACK_CHANNEL** — the channel ID to post in. In Slack, right-click the channel → **View channel details** → the ID (starts with `C`) is at the bottom.

```ini
SLACK_BOT_TOKEN=xoxb-paste-your-token-here
SLACK_CHANNEL=C0123456789
```

---

## Part 5: Check that everything is connected

Before your first real run, test all the connections:

```bash
make test
```

You should see `[OK]` next to JIRA, OpenAI, Zendesk, and Slack. If anything says `[FAIL]`, the message next to it tells you which key in `.env` to double-check. `[SKIP]` just means you left that service unconfigured, which is fine for the optional ones.

---

## Part 6: Generate release notes

In Terminal, from the project folder:

```bash
make run FIX_VERSION="06-12-2026"
```

Replace `06-12-2026` with the Fix Version date of your release (the same one set on the Jira tickets).

**Combining two releases into one page** — list both dates, separated by a comma:

```bash
make run FIX_VERSION="06-12-2026, 06-05-2026"
```

**No date given?** If you run plain `make run`, it uses today's date as the Fix Version.

**Want to look before anything goes to Zendesk?** A dry run writes the HTML file and stops there — no Zendesk draft, no Slack message:

```bash
make dry-run FIX_VERSION="06-12-2026"
```

### What you'll see

The tool prints each ticket as it processes it, then finishes with something like:

```text
Saved: /Users/you/Documents/GitHub/jira-release-notes/output/release_notes_2026-06-12.html
Zendesk draft: https://brightidea.zendesk.com/hc/en-us/articles/123456789
Posted to Slack channel C0123456789
```

### After it runs

1. Open the Zendesk draft link and **read the notes** — the AI is good but not perfect
2. Fix any wording directly in Zendesk
3. Publish the article when you're happy with it

---

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `make: command not found` | You may need to install Apple's developer tools: run `xcode-select --install` and try again |
| `OPENAI_API_KEY is not set` | Open `.env` and make sure the OpenAI key line is filled in (no quotes needed) |
| `Fix version ... is not a date` | Dates must look like `06-12-2026` (month-day-year with dashes) |
| `[FAIL] JIRA` in `make test` | Re-check `JIRA_SERVER` (full `https://...` address), your email, and the API token. Tokens expire — create a fresh one if needed |
| `[FAIL] OpenAI` in `make test` | Re-check `OPENAI_API_KEY`. If you set `OPENAI_MODEL`, make sure the name is spelled exactly as OpenAI lists it |
| `[FAIL] Zendesk` | Re-check the subdomain, email, token, and section ID. Confirm **Token access** is enabled in the Zendesk Admin Center |
| It stops with `JIRA returned 0 issues` | The run fails on purpose rather than publishing empty notes. Check Project = **BPD**, label = **Release_Notes**, and that the Fix Version date matches exactly what you typed in the command. Fix the tickets and run again |
| It stops with `already published` | An article with this title is live in Zendesk. Edit it there, or delete it and run the tool again |
| Slack message didn't appear | Make sure the bot was invited to the channel and `SLACK_CHANNEL` is the channel **ID** (starts with `C`), not the channel name. Both `SLACK_BOT_TOKEN` and `SLACK_CHANNEL` must be set |
| Something else went wrong | Run the same command with `LOG_LEVEL=DEBUG` in front of it to see the full error details |

---

## For developers

- `make unit` runs the unit tests (no network or keys needed); `make lint` runs ruff.
- `make eval` runs the LLM quality evaluation in `evals/release_notes.jsonl` against the live model. It costs OpenAI credits, so it is skipped unless `RUN_LLM_EVALS=1` is set.
- GitHub Actions: **CI** (lint + unit tests on Python 3.11 and 3.13), **Security** (dependency audit, static analysis, secret scan, weekly), and **LLM Evaluation** (pull requests that touch the prompt or eval set, or manual). Dependabot proposes dependency and action updates weekly.
- Dependencies are pinned in `requirements.txt` (runtime) and `requirements-dev.txt` (tooling).
