#!/bin/sh
set -eu
# Single-instance local deployment. Run migrations separately when scaling a hosted service.
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
