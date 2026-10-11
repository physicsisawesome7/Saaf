# Developer entry points. CI runs the same targets.
.PHONY: setup sync-spec lint typecheck test test-py test-js build-js website brand extension bench docker clean

PY ?= uv run

setup:
	uv sync --all-packages
	npm install
	uv run pre-commit install

sync-spec:
	python scripts/sync_spec.py

lint:
	python scripts/sync_spec.py --check
	$(PY) ruff check .
	$(PY) ruff format --check .
	git ls-files '*.md' '*.html' '*.js' '*.ts' '*.py' | xargs python scripts/check_wording.py

typecheck:
	$(PY) mypy
	npm run typecheck --workspace packages/saaf-js

test: test-py test-js

test-py:
	cd packages/saaf-core && $(PY) pytest --cov=saaf --cov-report=term-missing
	cd packages/saaf-gateway && $(PY) pytest
	cd plugins/litellm && $(PY) pytest
	cd plugins/open-webui && $(PY) pytest tests
	cd plugins/langchain && $(PY) pytest
	cd plugins/mcp-server && $(PY) pytest
	cd plugins/claude-code-hook && $(PY) pytest test_saaf_hook.py
	cd bench && $(PY) pytest

test-js:
	npm test --workspace packages/saaf-js

build-js:
	npm run build --workspace packages/saaf-js

website: build-js
	node apps/website/build.mjs
	python -m http.server 8080 --directory apps/website

brand:
	python scripts/make_brand_assets.py

extension: build-js
	node plugins/browser-extension/build.mjs

bench:
	cd bench && $(PY) python -m indicpii_bench generate --n 420 --seed 7 -o corpus/v0/docs.jsonl
	cd bench && $(PY) python -m indicpii_bench run --corpus corpus/v0/docs.jsonl --systems saaf,regex-baseline,presidio

docker:
	docker build -f packages/saaf-gateway/Dockerfile -t saaf-gateway:dev .

clean:
	rm -rf **/__pycache__ .pytest_cache .mypy_cache .ruff_cache packages/saaf-js/dist packages/saaf-js/build-test apps/website/assets/saaf plugins/browser-extension/lib
