#!/usr/bin/env python3
import argparse
import datetime as dt
import html
import json
import logging
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "serenity.sqlite"
RAW_DIR = ROOT / "data" / "raw"
TARGET_USER_ID = "1940360837547565056"
X_CURL_DIR = ROOT / "x_curl"
CURL_FILES = {
    "posts": "UserTweets.curl",
    "replies": "UserTweetsAndReplies.curl",
    "premium": "UserSuperFollowTweets.curl",
}
CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9_])\$([A-Z][A-Z0-9.]{0,9})(?![A-Za-z0-9_])")
NOISE_SYMBOLS = {"AI", "I", "A", "USD", "US", "CEO", "ETF", "IPO"}
LOGGER = logging.getLogger("serenity.ingest")


def configure_logging(level="INFO", log_file=None):
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    LOGGER.handlers.clear()
    LOGGER.setLevel(numeric_level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        LOGGER.addHandler(file_handler)
    LOGGER.propagate = False
    return LOGGER


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        pragma journal_mode = wal;
        create table if not exists raw_pages (
            id integer primary key autoincrement,
            source text not null,
            cursor text,
            fetched_at text not null,
            body text not null,
            unique(source, cursor)
        );
        create table if not exists tweets (
            tweet_id text primary key,
            source text not null,
            author_id text,
            author_screen_name text,
            created_at text,
            text text not null,
            url text,
            favorite_count integer,
            reply_count integer,
            retweet_count integer,
            quote_count integer,
            raw_json text not null
        );
        create table if not exists mentions (
            id integer primary key autoincrement,
            symbol text not null,
            tweet_id text not null references tweets(tweet_id) on delete cascade,
            mentioned_at text not null,
            text text not null,
            source text not null,
            unique(symbol, tweet_id)
        );
        create table if not exists prices (
            symbol text not null,
            date text not null,
            close real not null,
            volume integer,
            primary key(symbol, date)
        );
        create index if not exists idx_mentions_symbol_time on mentions(symbol, mentioned_at);
        create index if not exists idx_prices_symbol_date on prices(symbol, date);
        """
    )
    return con


def parse_curl(path: Path):
    text = path.read_text()
    args = [arg for arg in shlex.split(text, posix=True) if arg.strip()]
    if not args or args[0] != "curl":
        raise ValueError(f"{path} is not a curl command")
    return args


def set_cursor(url: str, cursor: str | None) -> str:
    parts = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    variables = json.loads(qs.get("variables", ["{}"])[0])
    if cursor:
        variables["cursor"] = cursor
    else:
        variables.pop("cursor", None)
    qs["variables"] = [json.dumps(variables, separators=(",", ":"))]
    query = urllib.parse.urlencode(qs, doseq=True)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def curl_fetch(curl_file: Path, cursor: str | None):
    args = parse_curl(curl_file)
    args[1] = set_cursor(args[1], cursor)
    args.extend(["-sS", "--compressed"])
    out = subprocess.check_output(args, cwd=ROOT)
    body = out.decode("utf-8", "replace")
    data = json.loads(body)
    if "errors" in data and not data.get("data"):
        raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False)[:1000])
    return body, data


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for val in obj.values():
            yield from walk(val)
    elif isinstance(obj, list):
        for val in obj:
            yield from walk(val)


def find_bottom_cursor(data):
    for node in walk(data):
        if node.get("cursorType") == "Bottom" and node.get("value"):
            return node["value"]
    return None


def normalize_tweet(node):
    if node.get("__typename") != "Tweet" or "legacy" not in node:
        return None
    legacy = node.get("legacy", {})
    core_user = (((node.get("core") or {}).get("user_results") or {}).get("result") or {})
    author_id = core_user.get("rest_id") or legacy.get("user_id_str")
    if author_id != TARGET_USER_ID:
        return None
    tweet_id = legacy.get("id_str") or node.get("rest_id")
    if not tweet_id:
        return None
    note = (((node.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {})
    text = note.get("text") or legacy.get("full_text") or ""
    text = html.unescape(text)
    created_at = parse_x_date(legacy.get("created_at"))
    screen = (((core_user.get("core") or {}).get("screen_name")) or "aleabitoreddit")
    return {
        "tweet_id": tweet_id,
        "author_id": author_id,
        "author_screen_name": screen,
        "created_at": created_at,
        "text": text,
        "url": f"https://x.com/{screen}/status/{tweet_id}",
        "favorite_count": legacy.get("favorite_count") or 0,
        "reply_count": legacy.get("reply_count") or 0,
        "retweet_count": legacy.get("retweet_count") or 0,
        "quote_count": legacy.get("quote_count") or 0,
        "symbols": extract_symbols(text, legacy, note),
        "raw_json": json.dumps(node, ensure_ascii=False, separators=(",", ":")),
    }


def parse_x_date(value):
    if not value:
        return None
    parsed = dt.datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def extract_symbols(text, legacy, note):
    found = set()
    for m in CASHTAG_RE.finditer(text or ""):
        found.add(m.group(1).upper())
    entity_sets = [legacy.get("entities") or {}, note.get("entity_set") or {}]
    for entities in entity_sets:
        for item in entities.get("symbols") or []:
            symbol = item.get("text") or (((item.get("tag") or {}).get("info") or {}).get("info") or {}).get("ticker")
            if symbol:
                found.add(symbol.upper())
    cleaned = set()
    for s in found:
        s = s.upper().strip()
        if s.endswith(".") and s.count(".") == 1:
            s = s[:-1]
        cleaned.add(s)
    return sorted(s for s in cleaned if s not in NOISE_SYMBOLS and 1 < len(s) <= 10)


def ingest_page(con, source, body, data, cursor):
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    con.execute(
        "insert or ignore into raw_pages(source, cursor, fetched_at, body) values (?, ?, ?, ?)",
        (source, cursor or "", now, body),
    )
    tweets = {}
    for node in walk(data):
        t = normalize_tweet(node)
        if t:
            tweets[t["tweet_id"]] = t
    for t in tweets.values():
        con.execute(
            """insert into tweets(tweet_id, source, author_id, author_screen_name, created_at, text, url,
                   favorite_count, reply_count, retweet_count, quote_count, raw_json)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               on conflict(tweet_id) do update set
                   source=excluded.source, created_at=excluded.created_at, text=excluded.text, url=excluded.url,
                   favorite_count=excluded.favorite_count, reply_count=excluded.reply_count,
                   retweet_count=excluded.retweet_count, quote_count=excluded.quote_count, raw_json=excluded.raw_json""",
            (t["tweet_id"], source, t["author_id"], t["author_screen_name"], t["created_at"], t["text"], t["url"],
             t["favorite_count"], t["reply_count"], t["retweet_count"], t["quote_count"], t["raw_json"]),
        )
        for symbol in t["symbols"]:
            con.execute(
                "insert or ignore into mentions(symbol, tweet_id, mentioned_at, text, source) values (?, ?, ?, ?, ?)",
                (symbol, t["tweet_id"], t["created_at"], t["text"], source),
            )
    return len(tweets)


def fetch_x(max_pages=20, pause=1.5):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    total = 0
    for source, filename in CURL_FILES.items():
        cursor = None
        seen = set()
        for page in range(max_pages):
            if cursor in seen:
                break
            seen.add(cursor)
            LOGGER.info("fetch_x source=%s page=%s cursor=%s", source, page + 1, "initial" if not cursor else cursor[:18])
            try:
                body, data = curl_fetch(X_CURL_DIR / filename, cursor)
            except Exception as exc:
                LOGGER.warning("fetch_x stop source=%s error=%s", source, exc)
                break
            raw_path = RAW_DIR / f"{source}_{page + 1}.json"
            raw_path.write_text(body)
            n = ingest_page(con, source, body, data, cursor)
            con.commit()
            total += n
            next_cursor = find_bottom_cursor(data)
            if not next_cursor or next_cursor == cursor or n == 0:
                break
            cursor = next_cursor
            time.sleep(pause)
    LOGGER.info("fetch_x complete tweets=%s db=%s", total, DB_PATH)


def symbol_list(con, min_mentions=2):
    rows = con.execute("""
        select symbol from mentions
        group by symbol
        having count(*) >= ?
        order by count(*) desc, symbol
    """, (min_mentions,)).fetchall()
    return [r[0] for r in rows]


def database_diagnostics(con, min_mentions=2):
    stats = con.execute(
        """
        select (select count(*) from tweets) tweets,
               (select count(*) from mentions) mentions,
               (select count(distinct symbol) from mentions) symbols,
               (select max(mentioned_at) from mentions) latest_mention,
               (select count(distinct symbol) from prices) priced_symbols
        """
    ).fetchone()
    missing = con.execute(
        """
        select m.symbol, count(*) mentions
        from mentions m
        left join prices p on p.symbol = m.symbol
        group by m.symbol
        having count(*) >= ? and count(p.symbol) = 0
        order by mentions desc, m.symbol
        limit 25
        """,
        (min_mentions,),
    ).fetchall()
    return {
        "tweets": stats[0],
        "mentions": stats[1],
        "symbols": stats[2],
        "latest_mention": stats[3],
        "priced_symbols": stats[4],
        "missing_price_symbols": [{"symbol": row[0], "mentions": row[1]} for row in missing],
    }


def curl_diagnostics(curl_dir=X_CURL_DIR):
    rows = []
    for source, filename in CURL_FILES.items():
        path = curl_dir / filename
        rows.append({
            "source": source,
            "path": str(path),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
        })
    return rows


def print_diagnostics(min_mentions=2):
    con = connect()
    info = database_diagnostics(con, min_mentions=min_mentions)
    print("database", DB_PATH)
    print("tweets", info["tweets"])
    print("mentions", info["mentions"])
    print("symbols", info["symbols"])
    print("priced_symbols", info["priced_symbols"])
    print("latest_mention", info["latest_mention"] or "-")
    print("curl_files")
    for row in curl_diagnostics():
        status = "ok" if row["exists"] else "missing"
        print(f"  {row['source']}: {status} {row['bytes']} bytes {row['path']}")
    print("missing_price_symbols")
    if not info["missing_price_symbols"]:
        print("  none")
    for row in info["missing_price_symbols"]:
        print(f"  {row['symbol']} mentions={row['mentions']}")
    symbols = [row[0] for row in con.execute("select distinct symbol from mentions order by symbol")]
    suggestions = symbol_alias_suggestions(symbols)
    print("alias_suggestions")
    if not suggestions:
        print("  none")
    for row in suggestions[:25]:
        print(f"  {row['symbol']} -> {row['suggestion']} ({row['reason']})")


def yahoo_chart(symbol, start, end):
    period1 = int(start.timestamp())
    period2 = int(end.timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?period1={period1}&period2={period2}&interval=1d&events=history"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def last_price_date(con, symbol):
    row = con.execute("select max(date) from prices where symbol=?", (symbol,)).fetchone()
    if not row or not row[0]:
        return None
    return dt.date.fromisoformat(row[0])


def should_fetch_prices(last_date, today, refresh_days=1):
    if last_date is None:
        return True
    return (today - last_date).days > refresh_days


def price_start_datetime(last_date, today, days_back=420):
    if last_date is None:
        return today - dt.timedelta(days=days_back)
    return dt.datetime.combine(last_date, dt.time.min, tzinfo=dt.timezone.utc)


def filter_symbols(symbols, selected):
    wanted = {s.upper() for s in selected if s.strip()}
    if not wanted:
        return symbols
    return [symbol for symbol in symbols if symbol.upper() in wanted]


def backoff_seconds(failures, base=2.0, maximum=60.0):
    if failures <= 0:
        return 0.0
    return min(maximum, base * (2 ** (failures - 1)))


def is_rate_limit_error(exc):
    text = str(exc).lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


COMMON_SYMBOL_TYPOS = {
    "APPL": "AAPL",
}


def symbol_alias_suggestions(symbols):
    present = {s.upper() for s in symbols}
    suggestions = []
    for symbol in sorted(present):
        typo_target = COMMON_SYMBOL_TYPOS.get(symbol)
        if typo_target and typo_target in present:
            suggestions.append({"symbol": symbol, "suggestion": typo_target, "reason": "common typo"})
        f_variant = f"{symbol}F"
        if f_variant in present:
            suggestions.append({"symbol": symbol, "suggestion": f_variant, "reason": "existing F-suffix variant"})
        dotted = sorted(s for s in present if s.startswith(f"{symbol}."))
        if dotted:
            suggestions.append({"symbol": symbol, "suggestion": dotted[0], "reason": "existing dotted exchange variant"})
    return suggestions


def fetch_prices(days_back=420, min_mentions=2, refresh_days=1, only_symbols=None, price_pause=1.0):
    con = connect()
    symbols = symbol_list(con, min_mentions)
    symbols = filter_symbols(symbols, only_symbols or [])
    if not symbols:
        LOGGER.info("prices skipped reason=no_symbols")
        return
    today = dt.datetime.now(dt.timezone.utc)
    today_date = today.date()
    start = today - dt.timedelta(days=days_back)
    for symbol in symbols:
        last_date = last_price_date(con, symbol)
        if not should_fetch_prices(last_date, today_date, refresh_days):
            LOGGER.info("price skip symbol=%s latest_date=%s", symbol, last_date)
            continue
        try:
            LOGGER.info("price fetch symbol=%s", symbol)
            fetch_start = price_start_datetime(last_date, today, days_back)
            data = yahoo_chart(symbol, fetch_start, today + dt.timedelta(days=2))
            result = (data.get("chart") or {}).get("result") or []
            if not result:
                LOGGER.warning("price no_result symbol=%s", symbol)
                continue
            res = result[0]
            timestamps = res.get("timestamp") or []
            quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
            closes = quote.get("close") or []
            volumes = quote.get("volume") or []
            inserted = 0
            for ts, close, vol in zip(timestamps, closes, volumes):
                if close is None:
                    continue
                date = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()
                con.execute(
                    "insert or replace into prices(symbol, date, close, volume) values (?, ?, ?, ?)",
                    (symbol, date, float(close), int(vol or 0)),
                )
                inserted += 1
            con.commit()
            LOGGER.info("price saved symbol=%s bars=%s", symbol, inserted)
            time.sleep(price_pause)
        except Exception as exc:
            LOGGER.warning("price failed symbol=%s error=%s", symbol, exc)
            if is_rate_limit_error(exc):
                wait = backoff_seconds(1, base=max(price_pause, 2.0), maximum=60.0)
                LOGGER.warning("rate limited; stopping price fetch after waiting %.1fs", wait)
                time.sleep(wait)
                break


def main():
    ap = argparse.ArgumentParser(description="Ingest Serenity X posts, symbols and Yahoo prices into SQLite.")
    ap.add_argument("command", choices=["fetch-x", "prices", "all", "stats", "diagnostics"])
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--days", type=int, default=420)
    ap.add_argument("--min-mentions", type=int, default=2)
    ap.add_argument("--refresh-days", type=int, default=1, help="Skip price symbols with a latest bar within this many days.")
    ap.add_argument("--symbol", action="append", default=[], help="Fetch prices only for this symbol. Can be repeated.")
    ap.add_argument("--x-pause", type=float, default=1.5, help="Seconds to wait between X GraphQL page requests.")
    ap.add_argument("--price-pause", type=float, default=1.0, help="Seconds to wait between Yahoo chart requests.")
    ap.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--log-file", help="Optional local log file path, e.g. logs/ingest.log")
    args = ap.parse_args()
    configure_logging(args.log_level, args.log_file)
    if args.command in {"fetch-x", "all"}:
        fetch_x(args.max_pages, args.x_pause)
    if args.command in {"prices", "all"}:
        fetch_prices(args.days, args.min_mentions, args.refresh_days, args.symbol, args.price_pause)
    if args.command == "diagnostics":
        print_diagnostics(args.min_mentions)
    if args.command == "stats":
        con = connect()
        print("tweets", con.execute("select count(*) from tweets").fetchone()[0])
        print("mentions", con.execute("select count(*) from mentions").fetchone()[0])
        print("prices", con.execute("select count(*) from prices").fetchone()[0])
        for row in con.execute("select symbol, count(*) c, min(mentioned_at), max(mentioned_at) from mentions group by symbol order by c desc, symbol"):
            print(dict(row))


if __name__ == "__main__":
    main()
