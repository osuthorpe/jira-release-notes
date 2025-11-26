import os
import sys
import json

# Add parent directory to path to import from automated_release_notes
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automated_release_notes import AutomatedReleaseNotes


def test_release_note_quality():
    """
    Test release note generation quality using Vald8.
    This test runs the decorated function's evaluation suite.
    """
    import os

    # Skip test if no OpenAI API key is available
    if not os.getenv('OPENAI_API_KEY'):
        import pytest
        pytest.skip("OPENAI_API_KEY not available - skipping evaluation test")

    # Instantiate the generator
    generator = AutomatedReleaseNotes()

    # Check if the function has the run_eval method (i.e., is decorated)
    if not hasattr(generator.create_release_note_for_story, 'run_eval'):
        import pytest
        pytest.skip("Function not decorated with Vald8 - evaluation test skipped")

    print("\nStarting Vald8 evaluation...")

    # Run the evaluation using the decorated instance method
    results = generator.create_release_note_for_story.run_eval()
    
    # Print detailed results
    print(f"\nPassed: {results.get('passed', False)}")
    print(f"Run directory: {results.get('run_dir', 'N/A')}")
    
    if 'summary' in results:
        summary = results['summary']
        print(f"\nSummary:")
        print(f"  Total: {summary.get('total_tests', 0)}")
        print(f"  Passed: {summary.get('passed_tests', 0)}")
        print(f"  Failed: {summary.get('failed_tests', 0)}")
        print(f"  Success Rate: {summary.get('success_rate', 0):.1%}")
    
    if 'tests' in results:
        print(f"\nTest Results:")
        for test in results['tests']:
            print(f"  {test.get('id', 'unknown')}: {test.get('passed', False)}")
            if not test.get('passed', False):
                print(f"    ❌ FAILED: {test.get('id', 'unknown')}")
                if 'error' in test:
                    print(f"    Error: {test['error']}")
                if 'reason' in test:
                    print(f"    Reason: {test['reason']}")
    
    if 'error' in results:
        print(f"\nError: {results['error']}")
    
    # Assert that the evaluation passed
    assert results.get('passed', False), "Vald8 evaluation failed"


if __name__ == "__main__":
    # Allow running directly for manual testing
    test_release_note_quality()
