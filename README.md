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

1. **Export from JIRA**: Export your issues as CSV from JIRA
2. **Place CSV**: Put the CSV file in the `jira-exports/` folder  
3. **Run**: Execute the script - it will automatically use the latest CSV file
   ```bash
   python automated_release_notes.py
   ```

### Output
- Saves professionally formatted HTML file to `output/` folder
- Complete with CSS styling and responsive design
- Includes title, timestamp, and footer information
- Ready to copy/paste content or share file directly

**Content includes:**
- Date and day information
- Categorized sections (General, Project Room, Whiteboard, Hackathon)
- Links to documentation
- Professional formatting matching your existing style

- Professional formatting matching your existing style

## Testing

We use `pytest` and `vald8` for testing and evaluation.

### Running Tests
```bash
pytest
```

### Quality Evaluation
The `tests/test_evaluation.py` script uses `vald8` to evaluate the quality of generated release notes, checking for:
- Completeness
- Clarity
- Tone

## Troubleshooting

- Check the `release_notes.log` file for detailed logs
- Verify all API credentials are correct
- Ensure JIRA JQL query returns results

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