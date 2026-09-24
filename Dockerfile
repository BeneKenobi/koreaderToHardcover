# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Then, install the project itself
ADD . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Keep all state in the /data volume; /app is not writable for the app user
ENV DB_PATH=/data/reading_stats.duckdb \
    LOG_PATH=/data/app.log

# Preinstall DuckDB's sqlite extension (needed to read KOReader's database), so the
# unprivileged app user never has to download or write extensions at runtime
ENV DUCKDB_EXTENSION_DIRECTORY=/app/duckdb_extensions
RUN python -c "import duckdb; duckdb.connect(config={'extension_directory': '$DUCKDB_EXTENSION_DIRECTORY'}).install_extension('sqlite')"

# Fix /data ownership, then run the app as an unprivileged user
ENTRYPOINT ["/app/docker/entrypoint.sh"]

# Any HTTP answer (401 without credentials) means the server is up
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import http.client, sys; c = http.client.HTTPConnection('127.0.0.1', 8000, timeout=5); c.request('GET', '/'); sys.exit(0 if c.getresponse().status < 500 else 1)"]

# Run the FastAPI application by default
CMD ["uvicorn", "koreadertohardcover.web:app", "--host", "0.0.0.0", "--port", "8000"]
