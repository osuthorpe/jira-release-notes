VENV = . venv/bin/activate &&
PYTHON ?= python3

# Accept FIX_VERSION in either upper- or lowercase on the command line
FIX_VERSION ?= $(fix_version)

.DEFAULT_GOAL := help
.PHONY: help setup install test run dry-run unit eval lint clean

help:
	@echo "JIRA Release Notes Generator"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  setup     Create .env from .env.example (then fill in your keys)"
	@echo "  install   Create the virtualenv and install dependencies"
	@echo "  test      Check JIRA, OpenAI, Zendesk and Slack access"
	@echo "  run       Generate release notes, create the Zendesk draft, post to Slack"
	@echo "  dry-run   Generate release notes only (no Zendesk, no Slack)"
	@echo "  unit      Run the unit tests (no network needed)"
	@echo "  eval      Run the LLM quality evaluation (uses OpenAI credits)"
	@echo "  lint      Check the code with ruff"
	@echo "  clean     Remove the virtualenv"
	@echo ""
	@echo "FIX_VERSION:"
	@echo "  Single:    make run FIX_VERSION=\"06-12-2026\""
	@echo "  Multiple:  make run FIX_VERSION=\"06-12-2026, 06-05-2026\""
	@echo "  Omitted:   today's date"

setup:
	@test -f .env || cp .env.example .env
	@echo "Edit .env with your API keys, then run: make test"

install:
	test -d venv || $(PYTHON) -m venv venv
	$(VENV) pip install --upgrade pip
	$(VENV) pip install -r requirements.txt -r requirements-dev.txt

test:
	$(VENV) python automated_release_notes.py test

run:
	$(VENV) FIX_VERSION="$(FIX_VERSION)" python automated_release_notes.py

dry-run:
	$(VENV) FIX_VERSION="$(FIX_VERSION)" python automated_release_notes.py --dry-run

unit:
	$(VENV) pytest tests/test_unit.py

eval:
	$(VENV) RUN_LLM_EVALS=1 pytest tests/test_evaluation.py -s

lint:
	$(VENV) ruff check .

clean:
	rm -rf venv
