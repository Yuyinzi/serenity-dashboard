# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See also `AGENTS.md` for detailed architecture and data model docs.

## Commands

```bash
# Quick start (first time setup)
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# Ingest everything: fetch X posts, extract symbols, download prices
.venv/bin/python scripts/ingest.py all --max-pages 10 --days 500 --min-mentions 3

# Run the dashboard server
.venv/bin/python scripts/server.py --port 8787

# Fetch only X data (no price update)
.venv/bin/python scripts/ingest.py fetch-x --max-pages 20

# Fetch only prices for symbols with >= N mentions
.venv/bin/python scripts/ingest.py prices --days 700 --min-mentions 2

# Show database stats
.venv/bin/python scripts/ingest.py stats

# Show diagnostics: DB counts, curl file status, missing price symbols
.venv/bin/python scripts/ingest.py diagnostics --min-mentions 2

# Analyze mention sentiment with OpenAI (direct mode for small batches)
OPENAI_API_KEY=... .venv/bin/python scripts/analyze_sentiment.py direct --limit 20

# Create OpenAI Batch for cost-efficient backfill
OPENAI_API_KEY=... .venv/bin/python scripts/analyze_sentiment.py batch-create --limit 1000

# Import completed batch results
.venv/bin/python scripts/analyze_sentiment.py batch-import --batch-results data/openai_batches/results.jsonl

# Backfill prices from TradingView (for symbols Yahoo lacks, like OTC tickers)
.venv/bin/python scripts/fetch_tv_price.py --exchange OTC --tv-symbol SIVEF --db-symbol SIVE

# Run tests
.venv/bin/python -m pytest
.venv/bin/python -m py_compile scripts/ingest.py scripts/server.py
```

Open `http://127.0.0.1:8787` after starting the server.

## Architecture

**Pipeline:** Browser-copied X GraphQL curl commands (`x_curl/*.curl`) → `scripts/ingest.py fetch-x` → raw JSON in `data/raw/` + SQLite `data/serenity.sqlite` → `scripts/server.py` serves a vanilla HTML/CSS/JS dashboard from `dashboard/`.

**Key scripts:**
- `scripts/ingest.py` — the main pipeline: fetches X GraphQL timelines via subprocess curl, normalizes tweets from the target user (hardcoded `TARGET_USER_ID`), extracts `$SYMBOL` cashtags from text + entities, fetches Yahoo chart daily bars. No framework dependencies; uses only stdlib.
- `scripts/server.py` — lightweight API server. Extends `SimpleHTTPRequestHandler` with `/api/summary`, `/api/feed`, and `/api/symbol/<symbol>` endpoints. Serves static files from `dashboard/`. Uses `ThreadingHTTPServer`.
- `scripts/fetch_tv_price.py` — TradingView backfill helper for symbols unavailable via Yahoo (e.g., OTC tickers). Uses the `tradingview-scraper` package (the only non-stdlib dependency). Writes into the same `prices` table.

**Data model (SQLite):**
- `raw_pages` — raw X API response pages, keyed by (source, cursor)
- `tweets` — normalized tweets from the target author (PK: `tweet_id`)
- `mentions` — extracted symbol + tweet reference + timestamp, unique per (symbol, tweet_id)
- `prices` — daily close/volume, PK: (symbol, date)

**Dashboard:** Vanilla JS with Chart.js 4.x for price charts. Symbols panel on the left, price chart with mention markers (orange dots) in the center, opinion feed at the bottom. Clicking a mention dot opens the original X post. The price line is green, mention markers orange, with a warm paper/ledger aesthetic.

## Constraints

- **Local-first.** Do not introduce cloud services, databases, or hosting dependencies without explicit request.
- **Preserve existing data.** Never delete `data/serenity.sqlite` or `data/raw/` unless explicitly asked.
- **`x_curl/*.curl` contains session cookies.** These expire; if X fetch returns empty or errors, tell the user to refresh them from Chrome DevTools (see README.md). Never commit these files.
- **Symbol filtering uses `NOISE_SYMBOLS`** in `ingest.py` to exclude generic tickers like "AI", "A", "USD".
- **The `$SYMBOL` extraction** uses regex `CASHTAG_RE`, X entities.symbols, and note tweet entities, with noise filtering and length bounds (2-10 chars).
- **Dashboard aesthetic:** editorial market-ledger feel — warm paper background, bold display typography (Bebas Neue, IBM Plex Serif), green/orange color scheme. Avoid generic white-card SaaS styling.
- **No test suite exists.** Validate changes by running the server and checking the dashboard manually, or with `python3 -m py_compile`.

Price ingestion is idempotent, incremental, and freshness-aware. Existing `(symbol, date)` rows are replaced, not duplicated. Symbols with a latest price bar within `--refresh-days` are skipped, and stale symbols fetch from their latest saved bar instead of refetching the full range. Use `--symbol NVDA --symbol TSM` to retry only selected symbols after a network/provider failure.

Politeness defaults: X page requests pause for `--x-pause 1.5` seconds by default, Yahoo price requests pause for `--price-pause 1.0` seconds by default, and Yahoo rate-limit responses stop the current price run. Keep `--max-pages` modest, prefer incremental price runs, and use `--symbol` to retry only failures.

The X fetch path uses browser-copied authenticated GraphQL requests. Treat it as personal local archival tooling, keep request volume low, and refresh curl files only from an account/session you control.

Ingestion uses Python logging for operational progress and failures. Use `--log-level DEBUG` for more detail and `--log-file logs/ingest.log` to keep a local run history. `stats` and `diagnostics` intentionally print human-readable command output.
