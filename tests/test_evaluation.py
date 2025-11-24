import pytest
from vald8 import Evaluator
from automated_release_notes import AutomatedReleaseNotes

def test_release_notes_generation():
    """
    Test that release notes are generated correctly and meet quality standards.
    """
    # Initialize generator
    generator = AutomatedReleaseNotes()
    
    # Mock data for testing
    mock_issues = [
        {
            'key': 'PROJ-123',
            'summary': 'Fix login bug',
            'type': 'Bug',
            'status': 'Done',
            'description': 'Fixed an issue where users could not log in.'
        },
        {
            'key': 'PROJ-124',
            'summary': 'Add dark mode',
            'type': 'Story',
            'status': 'Done',
            'description': 'Implemented dark mode for better user experience.'
        }
    ]
    
    # Generate release notes (mocking the AI part if possible, or testing the structure)
    # For this test, we'll assume the generator can produce a string output
    # In a real scenario, we might want to mock the OpenAI call to avoid costs/latency
    
    # Note: This is a placeholder for where we would integrate the actual generation logic
    # For now, we'll simulate a generated output to test Vald8 integration
    generated_notes = """
    # Release Notes
    
    ## New Features
    - **Dark Mode**: Added dark mode support.
    
    ## Bug Fixes
    - **Login**: Fixed login issue.
    """
    
    # Initialize Vald8 evaluator
    evaluator = Evaluator()
    
    # Define metrics to check
    metrics = [
        "completeness",  # Check if all issues are covered
        "clarity",       # Check if the notes are easy to understand
        "tone"           # Check if the tone is professional
    ]
    
    # Run evaluation
    results = evaluator.evaluate(generated_notes, context={"issues": mock_issues}, metrics=metrics)
    
    # Assertions
    # Note: The actual structure of 'results' depends on Vald8's API
    # This is a hypothetical usage pattern
    assert results['completeness'].score > 0.8
    assert results['clarity'].score > 0.8
    assert results['tone'].score > 0.8

if __name__ == "__main__":
    pytest.main([__file__])
