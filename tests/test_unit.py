import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automated_release_notes import AutomatedReleaseNotes


class TestAutomatedReleaseNotes:
    """Unit tests for AutomatedReleaseNotes class."""
    
    @pytest.fixture
    def generator(self):
        """Create a generator instance for testing."""
        return AutomatedReleaseNotes()
    
    def test_initialization(self, generator):
        """Test that the generator initializes correctly."""
        assert generator.output_dir.endswith("output")
        assert generator.jira_exports_dir.endswith("jira-exports")
        assert generator.openai_client is not None
    
    def test_format_date(self, generator):
        """Test date formatting."""
        day_of_week, formatted_date = generator.format_date()
        
        # Check that we get a day of the week
        assert day_of_week in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        # Check that the date is formatted correctly (e.g., "January 1, 2024")
        assert ',' in formatted_date
        assert len(formatted_date.split()) == 3  # Month Day, Year
    
    def test_get_latest_csv_file(self, generator, tmp_path):
        """Test finding the latest CSV file."""
        # Create temporary CSV files
        test_dir = tmp_path / "test_exports"
        test_dir.mkdir()
        
        # Create test files with different timestamps
        file1 = test_dir / "export1.csv"
        file2 = test_dir / "export2.csv"
        file1.write_text("test1")
        file2.write_text("test2")
        
        # Modify the generator to use the test directory
        generator.jira_exports_dir = str(test_dir)
        
        latest = generator.find_latest_csv_file()
        
        # Should return one of the files
        assert latest is not None
        assert latest.endswith('.csv')
    
    def test_get_latest_csv_file_no_files(self, generator, tmp_path):
        """Test behavior when no CSV files exist."""
        test_dir = tmp_path / "empty_exports"
        test_dir.mkdir()
        
        generator.jira_exports_dir = str(test_dir)
        
        latest = generator.find_latest_csv_file()
        assert latest is None
    
    @patch('automated_release_notes.pd.read_csv')
    def test_read_csv_file(self, mock_read_csv, generator):
        """Test CSV file reading."""
        # Mock pandas DataFrame
        mock_df = MagicMock()
        mock_df.iterrows.return_value = [
            (0, {
                'Issue key': 'TEST-1',
                'Summary': 'Test Issue',
                'Description': 'Test Description',
                'Labels': 'bug,urgent',
                'Issue Type': 'Bug',
                'Status': 'Done'
            })
        ]
        mock_read_csv.return_value = mock_df

        issues = generator.read_csv_issues('test.csv')

        assert len(issues) == 1
        assert issues[0]['summary'] == 'Test Issue'
        assert issues[0]['description'] == 'Test Description'
        assert 'bug' in issues[0]['labels']
    
    def test_save_release_notes_locally(self, generator, tmp_path):
        """Test saving release notes to a local file."""
        # Use temporary directory
        generator.output_dir = str(tmp_path)
        
        title = "Test Release Notes"
        body = "<p>Test content</p>"
        
        file_path = generator.save_release_notes_locally(title, body)
        
        # Check that file was created
        assert os.path.exists(file_path)
        assert file_path.endswith('.html')
        
        # Check file contents
        with open(file_path, 'r') as f:
            content = f.read()
            assert title in content
            assert body in content
            assert '<!DOCTYPE html>' in content
    
    @patch('automated_release_notes.AutomatedReleaseNotes._call_openai_for_release_note')
    def test_create_release_note_for_story(self, mock_openai, generator):
        """Test release note creation with mocked OpenAI."""
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "<strong>Test Feature-</strong> Added new functionality."
        mock_openai.return_value = mock_response
        
        result = generator.create_release_note_for_story(
            title="Test Feature",
            description="Added new functionality",
            labels=["feature"]
        )
        
        assert result == "<strong>Test Feature-</strong> Added new functionality."
        mock_openai.assert_called_once()
    
    @patch('automated_release_notes.AutomatedReleaseNotes._call_openai_for_release_note')
    def test_create_release_note_error_handling(self, mock_openai, generator):
        """Test error handling in release note creation."""
        # Mock OpenAI to raise an exception
        mock_openai.side_effect = Exception("API Error")
        
        result = generator.create_release_note_for_story(
            title="Test Issue",
            description="Test description",
            labels=[]
        )
        
        # Should return fallback message
        assert "Test Issue" in result
        assert "Issue resolved" in result
    
    def test_categorize_release_notes_empty(self, generator):
        """Test categorization with empty notes."""
        result = generator.categorize_release_notes("")
        
        # Should return some HTML structure even with empty input
        assert isinstance(result, str)
    
    @patch('automated_release_notes.AutomatedReleaseNotes._call_openai_for_categorization')
    def test_categorize_release_notes(self, mock_openai, generator):
        """Test release notes categorization."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "<h2>Bug Fixes</h2><ul><li>Fixed login issue</li></ul>"
        mock_openai.return_value = mock_response
        
        notes = "<li>Fixed login issue</li>"
        result = generator.categorize_release_notes(notes)
        
        assert "Bug Fixes" in result
        mock_openai.assert_called_once()


class TestModuleLevelFunctions:
    """Test module-level functions."""
    
    @patch('automated_release_notes.AutomatedReleaseNotes')
    def test_create_release_note_for_story_module_function(self, mock_class):
        """Test the module-level create_release_note_for_story function."""
        from automated_release_notes import create_release_note_for_story
        
        # Mock the instance and method
        mock_instance = MagicMock()
        mock_instance.create_release_note_for_story.return_value = "Test note"
        mock_class.return_value = mock_instance
        
        # Reset the global instance
        import automated_release_notes
        automated_release_notes._generator_instance = None
        
        result = create_release_note_for_story(
            title="Test",
            description="Test desc",
            labels=["test"]
        )
        
        assert result == "Test note"
        mock_instance.create_release_note_for_story.assert_called_once_with(
            "Test", "Test desc", ["test"]
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
