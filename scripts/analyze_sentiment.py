#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "serenity.sqlite"
PROMPT_VERSION = "sentiment-v1"
DEFAULT_MODEL = "gpt-5.4-mini"
SENTIMENTS = {"positive", "negative", "neutral", "mixed"}


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(
        """create table if not exists mention_analysis (
            mention_id integer primary key references mentions(id) on delete cascade,
            sentiment text not null check(sentiment in ('positive', 'negative', 'neutral', 'mixed')),
            score real not null,
            confidence real not null,
            rationale text not null,
            model text not null,
            prompt_version text not null,
            analyzed_at text not null,
            raw_json text not null
        )"""
    )
    return con


def load_config(args):
    env_path = ROOT / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)
    return {
        "api_key": args.openai_api_key or os.getenv("OPENAI_API_KEY"),
        "base_url": args.openai_base_url or os.getenv("OPENAI_BASE_URL"),
        "model": args.model or os.getenv("OPENAI_SENTIMENT_MODEL") or DEFAULT_MODEL,
    }


def pending_mentions(con, limit=200, symbol=None, force=False):
    params = []
    where = []
    if not force:
        where.append("a.mention_id is null")
    if symbol:
        where.append("m.symbol = ?")
        params.append(symbol.upper())
    params.append(limit)
    where_sql = " and ".join(where) if where else "1=1"
    return con.execute(
        f"""
        select m.id mention_id, m.symbol, m.tweet_id, m.mentioned_at, m.text, m.source
        from mentions m
        left join mention_analysis a on a.mention_id = m.id
        where {where_sql}
        order by m.mentioned_at desc
        limit ?
        """,
        params,
    ).fetchall()


ANALYSIS_SYSTEM_PROMPT = (
    "You classify the author's stance toward one stock symbol in one X post.\n"
    "Return sentiment positive, negative, neutral, or mixed.\n"
    "Use positive for constructive/bullish views, negative for bearish/concerned views,\n"
    "neutral for factual mentions, and mixed for both positive and negative signals.\n"
    "Score is -1.0 to 1.0, confidence is 0.0 to 1.0.\n"
    "This is research metadata, not financial advice.\n"
    "\n"
    "Respond with exactly this JSON structure:\n"
    '{"sentiment": "<positive|negative|neutral|mixed>", "score": <number -1..1>, '
    '"confidence": <number 0..1>, "rationale": "<one sentence>"}'
)

SENTIMENT_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral", "mixed"]},
        "score": {"type": "number"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["sentiment", "score", "confidence", "rationale"],
}


def build_messages(row):
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Symbol: {row['symbol']}\n"
                f"Mention time: {row['mentioned_at']}\n"
                f"Post text:\n{row['text']}"
            ),
        },
    ]


def validate_analysis(payload):
    if payload.get("sentiment") not in SENTIMENTS:
        raise ValueError("sentiment must be positive, negative, neutral, or mixed")
    score = payload.get("score")
    confidence = payload.get("confidence")
    if not isinstance(score, (int, float)) or not -1 <= score <= 1:
        raise ValueError("score must be a number from -1 to 1")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be a number from 0 to 1")
    if not payload.get("rationale"):
        raise ValueError("rationale is required")
    return payload


def save_analysis(con, mention_id, payload, model, raw_json):
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    con.execute(
        """insert or replace into mention_analysis
           (mention_id, sentiment, score, confidence, rationale, model, prompt_version, analyzed_at, raw_json)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            mention_id,
            payload["sentiment"],
            float(payload["score"]),
            float(payload["confidence"]),
            payload["rationale"],
            model,
            PROMPT_VERSION,
            now,
            raw_json,
        ),
    )


def _client(config):
    kwargs = {"api_key": config["api_key"]}
    if config["base_url"]:
        kwargs["base_url"] = config["base_url"]
    return OpenAI(**kwargs)


def analyze_direct(con, rows, config):
    client = _client(config)
    model = config["model"]
    for row in rows:
        messages = build_messages(row)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        payload = validate_analysis(json.loads(response.choices[0].message.content))
        save_analysis(con, row["mention_id"], payload, model, response.model_dump_json())
        con.commit()
        print(f"analyzed mention_id={row['mention_id']} symbol={row['symbol']} sentiment={payload['sentiment']}")


def write_batch_jsonl(rows, path, model=DEFAULT_MODEL):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps({
                "custom_id": f"mention:{row['mention_id']}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model,
                    "messages": build_messages(row),
                    "response_format": {"type": "json_object"},
                },
            }, ensure_ascii=False) + "\n")
    return path


def create_batch(con, rows, output_path, config):
    if not rows:
        raise SystemExit("no pending mentions to batch")
    client = _client(config)
    model = config["model"]
    jsonl_path = write_batch_jsonl(rows, output_path, model)
    try:
        uploaded = client.files.create(file=jsonl_path.open("rb"), purpose="batch")
        batch = client.batches.create(input_file_id=uploaded.id, endpoint="/v1/chat/completions", completion_window="24h")
        print(json.dumps({"batch_id": batch.id, "input_file_id": uploaded.id, "jsonl": str(jsonl_path)}, indent=2))
        return False
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status is not None and status != 401 and status != 403:
            print(f"Batch API unavailable (HTTP {status}), falling back to direct mode...", file=sys.stderr)
            analyze_direct(con, rows, config)
            return True
        detail = str(exc)
        body = getattr(exc, "body", None)
        if body:
            detail = f"{detail}\n{json.dumps(body, indent=2, ensure_ascii=False)}"
        raise SystemExit(f"OpenAI batch-create failed: {detail}") from exc


def import_batch_results(con, result_path, model=DEFAULT_MODEL):
    with Path(result_path).open("r", encoding="utf-8") as fh:
        for line in fh:
            item = json.loads(line)
            mention_id = int(item["custom_id"].split(":", 1)[1])
            if item.get("error"):
                print(f"batch_error mention_id={mention_id} error={item['error']}")
                continue
            body = item["response"]["body"]
            output_text = body["choices"][0]["message"]["content"]
            payload = validate_analysis(json.loads(output_text))
            save_analysis(con, mention_id, payload, body.get("model") or model, json.dumps(body, ensure_ascii=False))
    con.commit()


def main():
    parser = argparse.ArgumentParser(description="Analyze mention sentiment with OpenAI.")
    parser.add_argument("command", choices=["direct", "batch-create", "batch-import"])
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--symbol")
    parser.add_argument("--model")
    parser.add_argument("--openai-api-key")
    parser.add_argument("--openai-base-url")
    parser.add_argument("-f", "--force", action="store_true", help="Re-analyze mentions that already have sentiment rows.")
    parser.add_argument("--batch-jsonl", default="data/openai_batches/mention_sentiment.jsonl")
    parser.add_argument("--batch-results")
    args = parser.parse_args()
    config = load_config(args)
    if not config["api_key"] and args.command in {"direct", "batch-create"}:
        raise SystemExit("OPENAI_API_KEY is required via .env, environment, or --openai-api-key")

    con = connect()
    if args.command == "direct":
        analyze_direct(con, pending_mentions(con, args.limit, args.symbol, args.force), config)
    elif args.command == "batch-create":
        create_batch(con, pending_mentions(con, args.limit, args.symbol, args.force), Path(args.batch_jsonl), config)
    elif args.command == "batch-import":
        if not args.batch_results:
            raise SystemExit("--batch-results is required")
        import_batch_results(con, args.batch_results, config["model"])


if __name__ == "__main__":
    main()
