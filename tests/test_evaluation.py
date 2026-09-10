"""LLM quality evaluation. It spends OpenAI credits, so it only runs when RUN_LLM_EVALS=1."""

import os

import pytest

import automated_release_notes as rn

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_EVALS"), reason="set RUN_LLM_EVALS=1 to run the LLM evaluation"
)


def test_release_note_quality():
    results = rn.create_release_note.run_eval()

    summary = results.get("summary", {})
    print(f"\nRun directory: {results.get('run_dir')}")
    print(
        f"Passed {summary.get('passed_tests', 0)}/{summary.get('total_tests', 0)} "
        f"({summary.get('success_rate', 0):.0%})"
    )
    for test in results.get("tests", []):
        if not test.get("passed"):
            print(f"  FAILED {test.get('id')}: {test.get('reason') or test.get('error')}")
    if results.get("error"):
        print(f"Error: {results['error']}")

    assert results.get("passed"), "llm-expect evaluation failed"
