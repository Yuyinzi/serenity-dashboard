import scripts.ingest as ingest
import scripts.server as server


def make_db(path):
    original = ingest.DB_PATH
    ingest.DB_PATH = path
    try:
        con = ingest.connect()
    finally:
        ingest.DB_PATH = original
    return con


def seed(con):
    con.execute(
        """insert into tweets(tweet_id, source, author_id, author_screen_name, created_at, text, url,
           favorite_count, reply_count, retweet_count, quote_count, raw_json)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "1",
            "posts",
            "1940360837547565056",
            "aleabitoreddit",
            "2026-05-28T04:04:48Z",
            "Watching $NVDA",
            "https://x.com/aleabitoreddit/status/1",
            10,
            2,
            1,
            0,
            "{}",
        ),
    )
    con.execute(
        "insert into mentions(symbol, tweet_id, mentioned_at, text, source) values (?, ?, ?, ?, ?)",
        ("NVDA", "1", "2026-05-28T04:04:48Z", "Watching $NVDA", "posts"),
    )
    con.execute(
        "insert into prices(symbol, date, close, volume) values (?, ?, ?, ?)",
        ("NVDA", "2026-05-28", 123.45, 1000),
    )
    con.commit()


def test_summary_payload_contains_stats_and_symbols(tmp_path, monkeypatch):
    db_path = tmp_path / "serenity.sqlite"
    con = make_db(db_path)
    seed(con)
    monkeypatch.setattr(server, "DB_PATH", db_path)

    payload = server.summary(con)

    assert payload["stats"]["tweets"] == 1
    assert payload["stats"]["mentions"] == 1
    assert payload["stats"]["symbols"] == 1
    assert payload["symbols"][0]["symbol"] == "NVDA"
    assert payload["symbols"][0]["has_prices"] is True
    assert payload["symbols"][0]["last_close"] == 123.45


def test_symbol_payload_contains_prices_mentions_and_neighbors(tmp_path):
    con = make_db(tmp_path / "serenity.sqlite")
    seed(con)

    payload = server.symbol_payload(con, "NVDA")

    assert payload["symbol"] == "NVDA"
    assert payload["prices"] == [{"date": "2026-05-28", "close": 123.45, "volume": 1000}]
    assert payload["mentions"][0]["text"] == "Watching $NVDA"
    assert payload["neighbors"] == []


def test_clamp_limit_bounds_values():
    assert server.clamp_limit({"limit": ["1"]}, default=80, maximum=200) == 1
    assert server.clamp_limit({"limit": ["9999"]}, default=80, maximum=200) == 200
    assert server.clamp_limit({"limit": ["not-a-number"]}, default=80, maximum=200) == 80
    assert server.clamp_limit({}, default=80, maximum=200) == 80
