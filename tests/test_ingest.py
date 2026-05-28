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
