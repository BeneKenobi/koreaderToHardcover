#!/bin/sh
# Runs a real KOReader ingest inside the image as the unprivileged app user.
# Usage: docker/smoke-test.sh <image>
set -eu

IMAGE="$1"

docker run --rm --network none "$IMAGE" sh -c '
set -eu
test "$(id -u)" = "1000" || { echo "expected uid 1000, got $(id -u)"; exit 1; }
python - <<PY
import sqlite3

conn = sqlite3.connect("/data/statistics.sqlite3")
conn.execute(
    "CREATE TABLE book (id INTEGER PRIMARY KEY, title TEXT, authors TEXT, notes INTEGER, "
    "last_open INTEGER, highlights INTEGER, pages INTEGER, series TEXT, language TEXT, "
    "md5 TEXT, total_read_time INTEGER, total_read_pages INTEGER)"
)
conn.execute(
    "CREATE TABLE page_stat_data (id_book INTEGER, page INTEGER, start_time INTEGER, "
    "duration INTEGER, total_pages INTEGER)"
)
conn.execute(
    "INSERT INTO book (id, title, authors, last_open, pages, md5, total_read_pages) "
    "VALUES (1, '"'"'Smoke'"'"', '"'"'Test'"'"', 1700000000, 100, '"'"'abc'"'"', 10)"
)
conn.execute("INSERT INTO page_stat_data VALUES (1, 1, 1700000000, 30, 100)")
conn.commit()
PY
koreadertohardcover sync /data/statistics.sqlite3 --ingest-only --db-path /data/smoke.duckdb
'
echo "Smoke test passed"
