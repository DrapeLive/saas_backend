#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "Applying database migrations..."
    python manage.py migrate --noinput
fi

if [ "${COLLECT_STATIC:-1}" = "1" ]; then
    echo "Collecting static files..."
    python manage.py collectstatic --noinput
fi

exec "$@"
