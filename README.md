# KOReader to Hardcover

A CLI tool that synchronizes reading progress and book status from KOReader devices to the [Hardcover.app](https://hardcover.app) tracking service.

## Features

- **Sync Progress**: Automatically updates reading percentage and status (Reading/Finished) on Hardcover.
- **WebDAV Support**: Fetches your KOReader database directly from a WebDAV server (e.g., Nextcloud).
- **Interactive Mapping**: Manually map local books to Hardcover editions with a rich terminal interface.
- **Smart Matching**: Fuzzy search and fallback mechanisms to find books even with slight title variations.
- **Offline Mode**: Can work with a local copy of `statistics.sqlite3`.

## Installation

This project uses `uv` for dependency management.

```bash
# Install dependencies
uv sync

# Create .env file
cp .env.example .env
# Edit .env with your Hardcover API token and WebDAV credentials
```

## Usage

### Sync Recently Read Books

Sync the last 2 opened books:

```bash
uv run koreadertohardcover sync --past 2
```

### Manual Mapping

Launch the interactive book browser to fix incorrect mappings or map new books:

```bash
uv run koreadertohardcover map
```

Search for a specific book to map:

```bash
uv run koreadertohardcover map "Dune"
```

## Configuration

Set the following environment variables in `.env`:

- `HARDCOVER_BEARER_TOKEN`: Your API token from Hardcover.
- `WEBDAV_URL`: URL to your KOReader `statistics.sqlite3` file.
- `WEBDAV_USERNAME`: (Optional) WebDAV username.
- `WEBDAV_PASSWORD`: (Optional) WebDAV password.
