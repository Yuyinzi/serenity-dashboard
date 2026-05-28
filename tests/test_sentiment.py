import json
import sqlite3

import scripts.analyze_sentiment as sentiment


def test_build_messages_focuses_on_symbol():
    messages = sentiment.build_messages({
        "mention_id": 7,
        "symbol": "NVDA",
        "text": "Bullish on $NVDA, but worried about $NOK execution.",
        "mentioned_at": "2026-05-28T04:04:48Z",
    })

    assert "NVDA" in messages[1]["content"]
    assert "Bullish on $NVDA" in messages[1]["content"]


def test_validate_analysis_accepts_expected_schema():
    payload = {
        "sentiment": "positive",
        "score": 0.72,
        "confidence": 0.81,
        "rationale": "The author expresses a constructive view on the named symbol.",
    }

    assert sentiment.validate_analysis(payload) == payload


def test_validate_analysis_rejects_bad_sentiment():
    payload = {
        "sentiment": "bullish",
        "score": 0.72,
        "confidence": 0.81,
        "rationale": "Invalid enum.",
    }

    try:
        sentiment.validate_analysis(payload)
    except ValueError as exc:
        assert "sentiment" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_pending_mentions_excludes_existing_analysis():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        create table mentions(id integer primary key, symbol text, tweet_id text, mentioned_at text, text text, source text);
        create table mention_analysis(mention_id integer primary key, sentiment text, score real, confidence real, rationale text, model text, prompt_version text, analyzed_at text, raw_json text);
        """
    )
    con.execute("insert into mentions values (1, 'NVDA', 't1', '2026-05-28T04:04:48Z', 'Bullish $NVDA', 'posts')")
    con.execute("insert into mentions values (2, 'NOK', 't1', '2026-05-28T04:04:48Z', 'Worried $NOK', 'posts')")
    con.execute("insert into mention_analysis values (1, 'positive', 0.8, 0.9, 'ok', 'gpt-5.4-mini', 'v1', '2026-05-28T05:00:00Z', '{}')")

    rows = sentiment.pending_mentions(con, limit=10)

    assert [row["mention_id"] for row in rows] == [2]


def test_pending_mentions_force_includes_existing_analysis():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        create table mentions(id integer primary key, symbol text, tweet_id text, mentioned_at text, text text, source text);
        create table mention_analysis(mention_id integer primary key, sentiment text, score real, confidence real, rationale text, model text, prompt_version text, analyzed_at text, raw_json text);
        """
    )
    con.execute("insert into mentions values (1, 'NVDA', 't1', '2026-05-28T04:04:48Z', 'Bullish $NVDA', 'posts')")
    con.execute("insert into mention_analysis values (1, 'positive', 0.8, 0.9, 'ok', 'gpt-5.4-mini', 'v1', '2026-05-28T05:00:00Z', '{}')")

    rows = sentiment.pending_mentions(con, limit=10, force=True)

    assert [row["mention_id"] for row in rows] == [1]
