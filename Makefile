.PHONY: test test-unit test-integration test-e2e frontend-build ci-local

test:
	python -m pytest backend/tests/ -q -m "not integration_live and not slow" --tb=short

test-unit:
	python -m pytest backend/tests/ -q -m "not integration and not integration_live and not slow" --tb=short

test-integration:
	python -m pytest backend/tests/ -q -m "integration and not integration_live" --tb=short

test-e2e:
	cd frontend && npx playwright test

frontend-build:
	cd frontend && npm ci && npx tsc --noEmit && npm run build

ci-local: test test-integration frontend-build
	@echo "CI local passed"
