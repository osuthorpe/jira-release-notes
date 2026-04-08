install:
	pip install -r requirements.txt

run:
	python automated_release_notes.py

eval:
	python -c "from automated_release_notes import create_release_note; results = create_release_note.run_eval(); print('Passed:', results['passed'])"

setup:
	cp -n .env.example .env
	@echo "Edit .env with your API keys, then run: make run"
