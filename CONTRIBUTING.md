# Contributing

Use Python 3.12. From backend, install requirements-dev.txt, then run:

```sh
ruff format --check app tests migrations
ruff check app tests migrations
pytest -q
alembic upgrade head
alembic check
```

Add tests when changing execution costs, position accounting, model timing, ownership, replay, or validation. Update ENGINE_VERSION and methodology documents when calculation semantics change. No secrets, database files, caches, or real customer candles belong in the repository. Pin direct dependencies in requirements.txt and refresh the complete requirements.lock.txt with uv pip compile.
