VENV = . venv/bin/activate &&

# Accept FIX_VERSION in either upper- or lowercase on the command line
FIX_VERSION ?= $(fix_version)

.DEFAULT_GOAL := help
.PHONY: help install run eval test setup

help:
	@echo "JIRA Release Notes Generator"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  setup     Create .env from .env.example (edit it with your API keys)"
	@echo "  install   Create the virtualenv and install dependencies"
	@echo "  run       Generate release notes (optionally set FIX_VERSION)"
	@echo "  test      Test JIRA/OpenAI/Zendesk connections"
	@echo "  eval      Run the release-note generation eval"
	@echo "  help      Show this help message"
	@echo ""
	@echo "FIX_VERSION:"
	@echo "  Single:    make run FIX_VERSION=\"06-01-26\""
	@echo "  Multiple:  make run FIX_VERSION=\"06-01-26, 05-25-26\""
	@echo "  Omitted:   defaults to today's date"

install:
	python3 -m venv venv
	$(VENV) pip install -r requirements.txt

run:
	$(VENV) FIX_VERSION="$(FIX_VERSION)" python automated_release_notes.py

eval:
	$(VENV) python -c "from automated_release_notes import create_release_note; results = create_release_note.run_eval(); print('Passed:', results['passed'])"

test:
	$(VENV) python automated_release_notes.py test

setup:
	cp -n .env.example .env
	@echo "Edit .env with your API keys, then run: make run"
