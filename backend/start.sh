#!/bin/sh
# Migrate then serve. A separate script file rather than an inline shell
# one-liner in a platform's "start command" field, because those fields
# (Render's Docker Command included) do not reliably parse `&&` and quotes
# the way an actual shell does -- the whole string ends up treated as one
# literal, nonexistent command. A script file sidesteps that entirely.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
