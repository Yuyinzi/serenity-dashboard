import datetime as dt
import sqlite3

import scripts.ingest as ingest


def test_extract_symbols_from_text_entities_and_note_entities():
    legacy = {
        "entities": {
            "symbols": [
                {"text": "NVDA"},
                {"text": "AI"},
            ]
        }
    }
    note = {
        "entity_set": {
            "symbols": [
                {"tag": {"info": {"info": {"ticker": "TSM"}}}},
                {"text": "SIVE."},
            ]
        }
    }

    symbols = ingest.extract_symbols("Watching $AAOI and $LITE. Ignore $USD", legacy, note)

    assert symbols == ["AAOI", "LITE", "NVDA", "SIVE", "TSM"]


def test_extract_symbols_ignores_noise_and_single_letter_tickers():
    symbols = ingest.extract_symbols("$AI $A $USD $CEO $ETF $IPO $I $US $MU", {}, {})

    assert symbols == ["MU"]


def test_parse_x_date_returns_utc_iso_z():
    parsed = ingest.parse_x_date("Thu May 28 12:04:48 +0800 2026")

    assert parsed == "2026-05-28T04:04:48Z"


def test_symbol_list_respects_min_mentions():
    con = sqlite3.connect(":memory:")
    con.execute("create table mentions(symbol text)")
    con.executemany(
        "insert into mentions(symbol) values (?)",
        [("NVDA",), ("NVDA",), ("TSM",), ("SIVE",), ("SIVE",), ("SIVE",)],
    )

    assert ingest.symbol_list(con, min_mentions=2) == ["SIVE", "NVDA"]


def test_database_diagnostics_counts_missing_price_symbols():
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        create table tweets(tweet_id text, created_at text);
        create table mentions(symbol text, tweet_id text, mentioned_at text, text text, source text);
        create table prices(symbol text, date text, close real, volume integer);
        """
    )
    con.executemany(
        "insert into mentions(symbol, tweet_id, mentioned_at, text, source) values (?, ?, ?, ?, ?)",
        [
            ("NVDA", "1", "2026-05-28T04:04:48Z", "Watching $NVDA", "posts"),
            ("SIVE", "2", "2026-05-28T03:13:44Z", "Watching $SIVE", "premium"),
        ],
    )
    con.execute("insert into tweets(tweet_id, created_at) values (?, ?)", ("1", "2026-05-28T04:04:48Z"))
    con.execute("insert into prices(symbol, date, close, volume) values (?, ?, ?, ?)", ("NVDA", "2026-05-28", 123.45, 1000))

    info = ingest.database_diagnostics(con, min_mentions=1)

    assert info["tweets"] == 1
    assert info["mentions"] == 2
    assert info["symbols"] == 2
    assert info["priced_symbols"] == 1
    assert info["latest_mention"] == "2026-05-28T04:04:48Z"
    assert info["missing_price_symbols"] == [{"symbol": "SIVE", "mentions": 1}]


def test_curl_diagnostics_reports_expected_files(tmp_path):
    (tmp_path / "UserTweets.curl").write_text("curl 'https://example.com'")

    rows = ingest.curl_diagnostics(tmp_path)

    by_source = {row["source"]: row for row in rows}
    assert by_source["posts"]["exists"] is True
    assert by_source["posts"]["bytes"] > 0
    assert by_source["replies"]["exists"] is False
    assert by_source["premium"]["exists"] is False
