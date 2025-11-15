# Automated JIRA Release Notes to Zendesk

This tool automatically pulls release information from JIRA, generates formatted release notes using OpenAI, and creates articles in Zendesk.

## Setup

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment Variables**
   - Copy `.env.example` to `.env`
   - Fill in your API credentials and configuration

3. **API Token Setup**

   **JIRA API Token:**
   - Go to https://id.atlassian.com/manage-profile/security/api-tokens
   - Create an API token
   - Use your email as username and the token as password

   **Zendesk API Token:**
   - Go to Admin → Channels → API
   - Enable Token Access
   - Create a new API token

   **OpenAI API Key:**
   - Go to https://platform.openai.com/api-keys
   - Create a new API key

## Usage

### Option 1: CSV File Workflow (Recommended)
1. **Export from JIRA**: Export your issues as CSV from JIRA
2. **Place CSV**: Put the CSV file in the `jira-exports/` folder  
3. **Run**: Execute the script - it will automatically use the latest CSV file
   ```bash
   python automated_release_notes.py
   ```

### Option 2: Direct JIRA API
Configure JIRA credentials in `.env` and run:
```bash
python automated_release_notes.py
```

### Option 3: Force API (ignore CSV files)
```bash
# Set environment variable to force API usage
FORCE_JIRA_API=true python automated_release_notes.py
```

### Customization

You can customize the behavior by modifying environment variables:

- `JIRA_JQL_QUERY`: Custom JQL query for fetching issues
- `ZENDESK_SECTION_ID`: Target section in Zendesk for the article

### Example JQL Queries

**Recent releases (last 7 days):**
```
project = "MYPROJECT" AND fixVersion in releasedVersions() AND updated >= -7d ORDER BY updated DESC
```

**Specific version:**
```
project = "MYPROJECT" AND fixVersion = "1.2.3" ORDER BY updated DESC
```

**Issues with specific labels:**
```
project = "MYPROJECT" AND labels = "release-notes" AND updated >= -7d ORDER BY updated DESC
```

## Features

- ✅ **Flexible Input**: CSV files OR direct JIRA API
- ✅ **Automatic CSV Detection**: Uses latest CSV in `jira-exports/` folder
- ✅ **Flexible Output**: Zendesk articles OR local HTML files
- ✅ AI-powered release note generation using OpenAI
- ✅ Automatic categorization of release notes
- ✅ Professional HTML formatting with CSS styling
- ✅ Configurable JQL queries
- ✅ Comprehensive logging
- ✅ Error handling and recovery

## Output Options

### Zendesk Article (if configured)
- Automatically publishes to your Zendesk help center
- Returns article URL for immediate access

### Local HTML File (fallback)
- Saves professionally formatted HTML file to `output/` folder
- Complete with CSS styling and responsive design
- Includes title, timestamp, and footer information
- Ready to copy/paste content or share file directly

**Content includes:**
- Date and day information
- Categorized sections (General, Project Room, Whiteboard, Hackathon)
- Links to documentation
- Professional formatting matching your existing style

## Troubleshooting

- Check the `release_notes.log` file for detailed logs
- Verify all API credentials are correct
- Ensure JIRA JQL query returns results
- Check Zendesk section ID is valid

## Workflow Options

### CSV Workflow (No API Setup Required)
1. Export CSV from JIRA manually
2. Drop file in `jira-exports/` folder
3. Run script - automatically processes latest CSV

### API Workflow (Fully Automated)  
1. Configure API credentials in `.env`
2. Run script - fetches data and publishes automatically

### Hybrid Approach
- Use CSV for testing/development
- Use API for production automation
- Script automatically detects and uses CSV if available