VENV = . venv/bin/activate &&

install:
	python3 -m venv venv
	$(VENV) pip install -r requirements.txt

run:
	$(VENV) python automated_release_notes.py

eval:
	$(VENV) python -c "from automated_release_notes import create_release_note; results = create_release_note.run_eval(); print('Passed:', results['passed'])"

setup:
	cp -n .env.example .env
	@echo "Edit .env with your API keys, then run: make run"
