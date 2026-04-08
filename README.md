# JIRA Release Notes Generator

Generates formatted release notes from JIRA using OpenAI.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add your OpenAI API key (required). Optionally add JIRA credentials to pull issues automatically.

## Usage

```bash
python automated_release_notes.py
```

If JIRA creds are in `.env`, issues are pulled directly from JIRA. Otherwise, drop a JIRA CSV export into `jira-exports/` and run the script.

Output HTML goes to `output/`.
