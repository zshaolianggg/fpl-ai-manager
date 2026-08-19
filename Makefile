.PHONY: install test dry-run snapshot
install:
	python -m pip install -e .
test:
	python -m unittest discover -s tests -p 'test_*.py'
dry-run:
	FORCE_REPORT=preview DRY_RUN=true python -m fpl_ai_manager.main
snapshot:
	FORCE_REPORT=preview python -m fpl_ai_manager.main --print-snapshot
