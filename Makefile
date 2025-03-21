SRC_FUNCTIONS_REGEX := '^[a-z].*'
# all dirs not starting with underscore

venv:
	uv sync --all-groups --all-extras --locked

test:
	uv run pytest . -v -n 4 --dist loadgroup

initdb:
	uv run python tests/tools/init_testing_db.py

lint:
	uv run ruff format src tests
	uv run ruff check src tests --select I --fix

lint-check:
	uv run ruff format src tests --check --diff
	uv run ruff check src tests --select I --diff

mypy:
	uv run mypy

requirements:
	for d in $$(ls -1 src | grep -E ${SRC_FUNCTIONS_REGEX}); do \
		uv export --extra $$d --no-hashes > src/$$d/requirements.txt; \
	done

ci-test:
	docker compose run --build --rm bot make initdb
	docker compose run --rm bot make test

dependencies:
	echo "Copy common code to deploy Google Cloud Functions"
	echo "Don't run locally"

	for d in $$(ls -1 src | grep -E ${SRC_FUNCTIONS_REGEX}); do \
		cp src/_dependencies src/$$d/ -r ; \
	done

type-annotate:
	uv run python tests/tools/annotate_types.py

sqlalchemy-models:
	uv run sqlacodegen \
		postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB} \
		--outfile=tests/factories/db_models.py
	# then fix "_old_search_event_stages"

mypy-short:
	# check simple errors like missing imports
	uv run mypy src  2> build/mypy.log \
	 || grep "is not defined" build/mypy.log \
	  || grep "datetime" build/mypy.log