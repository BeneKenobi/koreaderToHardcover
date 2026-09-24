# KOReader to Hardcover

A self-hosted tool that synchronizes reading progress from [KOReader](https://koreader.rocks/) devices to [Hardcover.app](https://hardcover.app). It includes a Dockerized **Web Dashboard** for automated background syncing and easy book mapping, as well as a **CLI** for manual operations.

## Features

- **Automated Sync**: Regularly fetches `statistics.sqlite3` from WebDAV and updates Hardcover status/progress.
- **Web Dashboard**:
  - **Status Monitor**: View your currently reading books and their sync status.
  - **Interactive Mapping**: Search Hardcover's database to fix incorrect or missing book matches.
  - **Live Logs**: Watch the sync process in real-time.
- **Smart Matching**: Fuzzy search and fallback mechanisms to identify books by title and author.
- **WebDAV Support**: Compatible with Nextcloud and standard WebDAV servers.
- **Offline Capable**: Stores mapping data locally in a lightweight DuckDB database.

## Quick Start (Docker)

The easiest way to run the application is using Docker Compose.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/BeneKenobi/koreaderToHardcover.git
   cd koreaderToHardcover
   ```

2. **Configure Environment**:
   Create a `.env` file based on the example:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your credentials (see Configuration below).

3. **Run**:
   ```bash
   docker compose up -d --build
   ```

4. **Access**:
   Open [http://localhost:8000](http://localhost:8000) in your browser.
   Login with the credentials defined in `APP_USERNAME` / `APP_PASSWORD`.

## Manual Installation (CLI & Dev)

This project uses `uv` for dependency management.

### Prerequisites
- Python 3.11+
- `uv` package manager

### Setup

```bash
# Install dependencies
uv sync

# Setup environment
cp .env.example .env
```

### CLI Usage

**Sync recently read books:**
```bash
uv run koreadertohardcover sync --past 5
```

**Launch interactive terminal mapper:**
```bash
uv run koreadertohardcover map
```

## Configuration

Set the following variables in your `.env` file:

| Variable | Description | Required | Default |
|----------|-------------|:--------:|:-------:|
| `HARDCOVER_BEARER_TOKEN` | Your API token from Hardcover.app | **Yes** | - |
| `WEBDAV_URL` | Base WebDAV URL, e.g. `https://cloud.example.com/remote.php/dav/files/user/` | **Yes** | - |
| `WEBDAV_USERNAME` | WebDAV username | **Yes** | - |
| `WEBDAV_PASSWORD` | WebDAV password | **Yes** | - |
| `WEBDAV_PATH` | Folder containing the database, relative to `WEBDAV_URL` | No | - |
| `KOREADER_DB_PATH` | Database file name inside `WEBDAV_PATH` | No | `statistics.sqlite3` |
| `SYNC_INTERVAL_MINUTES` | Frequency of automated syncs (Docker only) | No | `60` |
| `APP_USERNAME` | Dashboard Login Username | No | `admin` |
| `APP_PASSWORD` | Dashboard Login Password | No | `admin` |
| `SECRET_KEY` | Session cookie key; generated and stored next to the database if unset | No | - |

## Sync Behavior

- A book counts as **finished** once at least 98% is read, or when at most 15 pages are left and at least 90% is read (unread back matter).
- Books already marked *Finished* on Hardcover are not changed again unless you run `sync --force`.
- The last state sent to Hardcover is stored locally. Books with unchanged local progress are skipped without an API call, so changes made directly on Hardcover (for example removing a book from your shelf) are not noticed until local progress changes. Use `sync --force` to push the current state again.
- The Docker image runs the app as UID/GID 1000 (override with `APP_UID`/`APP_GID`) and takes ownership of `/data` on start.
