#!/usr/bin/env python3
"""
Automated JIRA Release Notes to Zendesk Article Generator

This script automatically:
1. Pulls issues from JIRA CSV files or API
2. Generates release notes using OpenAI
3. Creates a Zendesk article OR saves HTML file locally
"""

import os
import glob
import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from jira import JIRA
from zenpy import Zenpy
from zenpy.lib.api_objects.help_centre_objects import Article
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv
from vald8 import vald8

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('release_notes.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def retry_on_failure(max_retries=3, delay=2, backoff=2):
    """Decorator to retry functions on failure with exponential backoff."""
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
                        logger.error(f"Function {func.__name__} failed after {max_retries} retries: {e}")
                        raise e
                    
                    logger.warning(f"Attempt {retries} failed for {func.__name__}: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
            
            return None
        return wrapper
    return decorator


class AutomatedReleaseNotes:
    def __init__(self):
        """Initialize the automated release notes generator with API clients."""
        self.jira_exports_dir = os.path.join(os.path.dirname(__file__), 'jira-exports')
        self.output_dir = os.path.join(os.path.dirname(__file__), 'output')
        self.max_retries = 3
        self.retry_delay = 2  # seconds
        self.setup_clients()
        
    def setup_clients(self):
        """Setup API clients for JIRA, Zendesk, and OpenAI."""
        try:
            # OpenAI Client (always needed)
            self.openai_client = OpenAI(
                api_key=os.getenv('OPENAI_API_KEY')
            )
            
            # JIRA Client (optional - only needed if no CSV files)
            jira_server = os.getenv('JIRA_SERVER')
            if jira_server:
                self.jira_client = JIRA(
                    server=jira_server,
                    basic_auth=(
                        os.getenv('JIRA_USERNAME'),
                        os.getenv('JIRA_API_TOKEN')
                    )
                )
            else:
                self.jira_client = None
                logger.info("JIRA client not configured - will use CSV files only")
            
            # Zendesk Client (optional - only needed for auto-publishing)
            zendesk_subdomain = os.getenv('ZENDESK_SUBDOMAIN')
            zendesk_email = os.getenv('ZENDESK_EMAIL')
            zendesk_token = os.getenv('ZENDESK_API_TOKEN')
            
            if zendesk_subdomain and zendesk_email and zendesk_token:
                self.zendesk_client = Zenpy(
                    subdomain=zendesk_subdomain,
                    email=zendesk_email,
                    password=zendesk_token
                )
                logger.info("Zendesk client configured successfully")
            else:
                self.zendesk_client = None
                logger.info("Zendesk client not configured - will save files locally")
            
            logger.info("API clients initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize API clients: {e}")
            raise

    def get_day_suffix(self, day: int) -> str:
        """Get the appropriate suffix for a day (st, nd, rd, th)."""
        if 4 <= day <= 20 or 24 <= day <= 30:
            return "th"
        else:
            return ["st", "nd", "rd"][day % 10 - 1]

    def format_date(self, date_obj: datetime = None) -> tuple:
        """Format date for display in release notes."""
        if date_obj is None:
            date_obj = datetime.today()
            
        day = date_obj.day
        month = date_obj.strftime("%B")
        year = date_obj.year
        day_of_week = date_obj.strftime("%A")
        
        formatted_date = f"{month} {day}{self.get_day_suffix(day)}, {year}"
        
        return day_of_week, formatted_date

    def find_latest_csv_file(self) -> Optional[str]:
        """Find the latest CSV file in the jira-exports directory."""
        try:
            csv_pattern = os.path.join(self.jira_exports_dir, '*.csv')
            csv_files = glob.glob(csv_pattern)
            
            if not csv_files:
                logger.info("No CSV files found in jira-exports directory")
                return None
            
            # Sort by modification time, get the latest
            latest_file = max(csv_files, key=os.path.getmtime)
            logger.info(f"Found latest CSV file: {latest_file}")
            return latest_file
            
        except Exception as e:
            logger.error(f"Error finding CSV files: {e}")
            return None

    def read_csv_issues(self, csv_file_path: str) -> List[Dict[str, Any]]:
        """Read issues from CSV file (original workflow)."""
        try:
            logger.info(f"Reading issues from CSV file: {csv_file_path}")
            
            df = pd.read_csv(csv_file_path)
            
            issues = []
            for _, row in df.iterrows():
                issue_dict = {
                    'key': row.get('Issue key', 'N/A'),
                    'summary': row.get('Summary', ''),
                    'description': row.get('Description', ''),
                    'labels': row.get('Labels', '').split(',') if pd.notna(row.get('Labels')) else [],
                    'issue_type': row.get('Issue Type', 'Task'),
                    'status': row.get('Status', 'Done')
                }
                issues.append(issue_dict)
            
            logger.info(f"Read {len(issues)} issues from CSV file")
            return issues
            
        except Exception as e:
            logger.error(f"Failed to read CSV file {csv_file_path}: {e}")
            raise

    def fetch_jira_issues(self, jql: str = None) -> List[Dict[str, Any]]:
        """
        Fetch issues from JIRA using JQL query.
        
        Args:
            jql: JIRA Query Language string. If None, uses default query for recent releases.
            
        Returns:
            List of issue dictionaries with relevant fields.
        """
        try:
            if jql is None:
                # Default JQL for recent releases - adjust as needed
                jql = 'project = "YOUR_PROJECT" AND fixVersion in releasedVersions() AND updated >= -7d ORDER BY updated DESC'
            
            logger.info(f"Fetching JIRA issues with JQL: {jql}")
            
            issues = self.jira_client.search_issues(
                jql,
                maxResults=100,
                fields='summary,description,labels,issuetype,status'
            )
            
            issue_data = []
            for issue in issues:
                issue_dict = {
                    'key': issue.key,
                    'summary': issue.fields.summary,
                    'description': getattr(issue.fields.description, 'content', '') if issue.fields.description else '',
                    'labels': [label for label in issue.fields.labels] if issue.fields.labels else [],
                    'issue_type': issue.fields.issuetype.name,
                    'status': issue.fields.status.name
                }
                issue_data.append(issue_dict)
                
            logger.info(f"Fetched {len(issue_data)} issues from JIRA")
            return issue_data
            
        except Exception as e:
            logger.error(f"Failed to fetch JIRA issues: {e}")
            raise

    @retry_on_failure(max_retries=3, delay=2)
    def _call_openai_for_release_note(self, messages):
        """Make OpenAI API call with retry logic."""
        return self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=500,
            timeout=30
        )

    def create_release_note_for_story(self, title: str, description: str, labels: List[str], progress_callback=None) -> str:
        """Create a single-sentence release note using OpenAI's ChatGPT."""
        try:
            if progress_callback:
                progress_callback(f"Generating release note for: {title[:50]}...")
                
            labels_str = ', '.join(labels) if labels else 'No labels'
            
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": 
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
            
            response = self._call_openai_for_release_note(messages)
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Failed to create release note for story '{title}': {e}")
            return f"<strong>{title}-</strong> Issue resolved."

    @retry_on_failure(max_retries=3, delay=3)
    def _call_openai_for_categorization(self, messages):
        """Make OpenAI API call for categorization with retry logic."""
        return self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=4096,
            timeout=45
        )

    def categorize_release_notes(self, release_notes: str, progress_callback=None) -> str:
        """Categorize release notes into sections using OpenAI's ChatGPT."""
        try:
            if progress_callback:
                progress_callback("Categorizing release notes...")
                
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
            
            response = self._call_openai_for_categorization(messages)
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Failed to categorize release notes: {e}")
            return f"<p><strong>General bug fixes and enhancements</strong></p><ul>{release_notes}</ul>"

    def generate_release_notes_html(self, issues: List[Dict[str, Any]], progress_callback=None) -> str:
        """Generate formatted HTML release notes from JIRA issues."""
        try:
            logger.info(f"Generating release notes for {len(issues)} issues")
            
            if progress_callback:
                progress_callback(f"Starting to process {len(issues)} issues...")
            
            release_notes = ""
            total_issues = len(issues)
            
            for i, issue in enumerate(issues, 1):
                title = issue['summary']
                description = issue['description']
                labels = issue['labels']
                
                if progress_callback:
                    progress_callback(f"Processing issue {i}/{total_issues}: {title[:30]}...")
                
                release_note = self.create_release_note_for_story(title, description, labels, progress_callback)
                release_notes += f"<li>{release_note}</li>\n"
                
                # Update progress
                if progress_callback:
                    progress_percent = int((i / total_issues) * 80)  # Reserve 20% for categorization
                    progress_callback(f"Progress: {progress_percent}% complete")
            
            if progress_callback:
                progress_callback("Categorizing release notes...")
                
            categorized_notes = self.categorize_release_notes(release_notes, progress_callback)
            
            if progress_callback:
                progress_callback("Finalizing HTML generation...")
            
            day_of_week, formatted_date = self.format_date()
            
            formatted_release_notes = f"""
<p>
  Our&nbsp;latest<span style="box-sizing: border-box;">&nbsp;</span><span style="box-sizing: border-box;">product release took effect</span><span style="box-sizing: border-box;">&nbsp;</span><strong style="box-sizing: border-box; font-weight: 600;">{day_of_week}</strong><strong style="box-sizing: border-box; font-weight: 600;">, {formatted_date}</strong><strong style="box-sizing: border-box; font-weight: 600;">.<span style="box-sizing: border-box;">&nbsp;</span></strong>This
  post may be different from the release notes received via email.
</p>
<p>
  <span style="box-sizing: border-box;">To read Brightidea's complete documentation, you can visit the </span><a style="box-sizing: border-box; background-color: transparent; color: #034678; text-decoration: none;" href="https://support.brightidea.com/hc/en-us/sections/200825397-Product-Release-Notes">Product Release Notes</a><span style="box-sizing: border-box;">&nbsp;forum in the Support Portal.</span>
</p>
{categorized_notes}
"""
            
            if progress_callback:
                progress_callback("Release notes generation completed!")
                
            logger.info("Release notes HTML generated successfully")
            return formatted_release_notes
            
        except Exception as e:
            logger.error(f"Failed to generate release notes HTML: {e}")
            raise

    def create_zendesk_article(self, title: str, body: str, section_id: int = None) -> str:
        """
        Create a new article in Zendesk.
        
        Args:
            title: Article title
            body: Article body (HTML)
            section_id: Zendesk section ID (optional)
            
        Returns:
            Article URL
        """
        try:
            # If no section_id provided, use default from environment
            if section_id is None:
                section_id = int(os.getenv('ZENDESK_SECTION_ID', '0'))
            
            article = Article(
                title=title,
                body=body,
                section_id=section_id,
                locale='en-us',
                draft=False
            )
            
            created_article = self.zendesk_client.help_center.articles.create(article)
            
            article_url = f"https://{os.getenv('ZENDESK_SUBDOMAIN')}.zendesk.com/hc/en-us/articles/{created_article.id}"
            
            logger.info(f"Zendesk article created successfully: {article_url}")
            return article_url
            
        except Exception as e:
            logger.error(f"Failed to create Zendesk article: {e}")
            raise

    def save_release_notes_locally(self, title: str, body: str) -> str:
        """
        Save release notes to a local HTML file.
        
        Args:
            title: Article title
            body: Article body (HTML)
            
        Returns:
            Local file path
        """
        try:
            # Create filename from title and current date
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title.replace(' ', '_')
            date_suffix = datetime.now().strftime("_%m_%d_%Y")
            filename = f"{safe_title}{date_suffix}.html"
            
            file_path = os.path.join(self.output_dir, filename)
            
            # Create complete HTML document
            full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
        }}
        h1 {{
            color: #034678;
            border-bottom: 2px solid #034678;
            padding-bottom: 10px;
        }}
        ul {{
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 8px;
        }}
        a {{
            color: #034678;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .header {{
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{title}</h1>
        <p><em>Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</em></p>
    </div>
    
    <div class="content">
        {body}
    </div>
    
    <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em;">
        <p>This file was generated automatically by the JIRA Release Notes tool.</p>
    </footer>
</body>
</html>"""
            
            # Ensure output directory exists
            os.makedirs(self.output_dir, exist_ok=True)
            
            # Write the file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_html)
            
            logger.info(f"Release notes saved locally: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"Failed to save release notes locally: {e}")
            raise

    def run_automated_workflow(self, jql: str = None, article_title: str = None, force_api: bool = False) -> str:
        """
        Run the complete automated workflow.
        
        Args:
            jql: Custom JQL query for JIRA issues
            article_title: Custom title for the Zendesk article
            force_api: Force use of JIRA API even if CSV files exist
            
        Returns:
            URL of the created Zendesk article or HTML content if Zendesk not configured
        """
        try:
            logger.info("Starting automated release notes workflow")
            
            issues = None
            
            # Step 1: Try to get issues from CSV first (unless force_api is True)
            if not force_api:
                latest_csv = self.find_latest_csv_file()
                if latest_csv:
                    logger.info(f"Using CSV file: {latest_csv}")
                    issues = self.read_csv_issues(latest_csv)
            
            # Step 2: Fallback to JIRA API if no CSV found or force_api is True
            if not issues:
                if self.jira_client is None:
                    raise Exception("No CSV files found and JIRA client not configured. Please add a CSV file to jira-exports/ or configure JIRA API credentials.")
                
                logger.info("No CSV file found, fetching from JIRA API")
                issues = self.fetch_jira_issues(jql)
            
            if not issues:
                logger.warning("No issues found from any source. Exiting workflow.")
                return None
            
            # Step 3: Generate release notes HTML
            release_notes_html = self.generate_release_notes_html(issues)
            
            # Step 4: Create Zendesk article or save locally
            if article_title is None:
                day_of_week, formatted_date = self.format_date()
                article_title = f"Product Release Notes - {formatted_date}"
            
            if self.zendesk_client:
                article_url = self.create_zendesk_article(article_title, release_notes_html)
                logger.info(f"Automated workflow completed successfully. Article URL: {article_url}")
                return article_url
            else:
                logger.info("Zendesk not configured, saving release notes locally")
                local_file_path = self.save_release_notes_locally(article_title, release_notes_html)
                logger.info(f"Automated workflow completed successfully. File saved: {local_file_path}")
                
                # Also print a preview
                print("\n" + "="*60)
                print("📄 RELEASE NOTES SAVED LOCALLY")
                print("="*60)
                print(f"File: {local_file_path}")
                print(f"Title: {article_title}")
                print("\nPreview:")
                print("-" * 40)
                # Print first few lines of the content for preview
                preview_lines = release_notes_html.split('\n')[:10]
                for line in preview_lines:
                    if line.strip():
                        print(line.strip()[:80] + ("..." if len(line.strip()) > 80 else ""))
                print("="*60)
                
                return local_file_path
            
        except Exception as e:
            logger.error(f"Automated workflow failed: {e}")
            raise




# Create a module-level instance for Vald8 evaluation
_generator_instance = None

def _get_generator():
    """Lazy initialization of generator instance."""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = AutomatedReleaseNotes()
    return _generator_instance

def create_release_note_for_story(title: str, description: str, labels: List[str]) -> str:
    """
    Module-level function for Vald8 evaluation.
    Delegates to the AutomatedReleaseNotes instance method.
    """
    generator = _get_generator()
    return generator.create_release_note_for_story(title, description, labels)

# Apply Vald8 decorator only if OpenAI API key is available
if os.getenv('OPENAI_API_KEY'):
    try:
        create_release_note_for_story = vald8(
            dataset="tests/data.jsonl",
            tests=["custom_judge"],
            judge_provider="openai",
            judge_model="gpt-4o-mini"
        )(create_release_note_for_story)
    except Exception as e:
        logger.warning(f"Failed to apply Vald8 decorator: {e}")
        # Function remains undecorated but still works
else:
    logger.info("OPENAI_API_KEY not found - Vald8 evaluation will be skipped")


def main():
    """Main function to run the automated release notes generator."""
    try:
        generator = AutomatedReleaseNotes()
        
        # You can customize the JQL query and article title here
        custom_jql = os.getenv('JIRA_JQL_QUERY')  # Optional: set in environment
        result = generator.run_automated_workflow(jql=custom_jql)
        
        if result:
            if result.startswith('http'):
                print(f"\n✅ Success! Zendesk article created: {result}")
            else:
                print(f"\n✅ Success! Release notes saved locally: {result}")
                print("\n💡 Tip: Open the HTML file in your browser to view the formatted release notes.")
        else:
            print("\n⚠️  No output created - no issues found.")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        logger.error(f"Main function failed: {e}")


if __name__ == "__main__":
    main()