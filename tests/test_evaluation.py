import os
import sys

# Add parent directory to path to import from automated_release_notes
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automated_release_notes import evaluate_release_note_generation


def test_release_note_quality():
    """
    Test release note generation quality using Vald8.
    This test runs the decorated function's evaluation suite.
    """
    print("\nStarting Vald8 evaluation...")
    
    # Run the evaluation using the decorated function from production code
    results = evaluate_release_note_generation.run_eval()
    
    # Print summary
    print(f"Passed: {results.get('passed', False)}")
    if 'summary' in results:
        print(f"Success Rate: {results['summary'].get('success_rate', 0):.1%}")
    elif 'error' in results:
        print(f"Error: {results['error']}")
    
    # Assert that the evaluation passed
    assert results.get('passed', False), "Vald8 evaluation failed"


if __name__ == "__main__":
    # Allow running directly for manual testing
    test_release_note_quality()
