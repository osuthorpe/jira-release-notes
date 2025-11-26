import os

def pytest_ignore_collect(path, config):
    """
    Return True to prevent considering this path for collection.
    This hook is consulted for all files and directories prior to calling
    more specific collection hooks.
    """
    # Check if we are looking at the evaluation or unit test file
    if path.basename in ["test_evaluation.py", "test_unit.py"]:
        # If OPENAI_API_KEY is not set, ignore this file
        if not os.getenv("OPENAI_API_KEY"):
            return True
    return False
