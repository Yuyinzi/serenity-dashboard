# Serenity Signal Dashboard

本项目 Fork 自 [haskaomni/serenity](https://github.com/haskaomni/serenity)，在此之上增加了：

- **OpenAI 情感分析**：对每条 symbol 提及进行 LLM 情感分类（positive / negative / neutral / mixed），结果展示在 dashboard 图表和数据中

原项目提供 X 抓取、价格下载和 dashboard 可视化。本项目抓取 `x_curl/` 中的 X GraphQL curl，解析 `@aleabitoreddit` 的帖子、回复、订阅帖，抽取 `$SYMBOL`，写入本地 SQLite，并用 Yahoo chart 接口下载日线价格。

![Serenity dashboard screenshot](docs/assets/dashboard.png)

## 与原项目的区别

本 Fork 在原项目基础上增加了情感分析管线（`scripts/analyze_sentiment.py`）和 dashboard 中的情感可视化。如果你只需要基础的 X 抓取和价格展示，使用原项目即可。

> 本项目仅用于研究和可视化，不构成投资建议。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

.venv/bin/python scripts/ingest.py all --max-pages 10 --days 500 --min-mentions 3
.venv/bin/python scripts/server.py --port 8787
```

需要 Python 3.10+；本仓库中的类型标注使用了 `str | None` 语法。

打开 `http://127.0.0.1:8787`。

## 从 Chrome 复制 X curl

`scripts/ingest.py fetch-x` 会读取 `x_curl/` 目录中的浏览器请求。首次使用或登录态过期时，需要从 Chrome DevTools 重新复制。

1. 用 Chrome 登录 X，并打开 `https://x.com/aleabitoreddit`。
2. 打开 DevTools：`F12` 或 `Cmd/Ctrl + Shift + I`。
3. 切到 `Network` 面板，筛选 `Fetch/XHR`，也可以在过滤框输入 `UserTweets`。
4. 刷新页面，滚动几次，触发帖子、回复或订阅内容加载。
5. 找到以下 GraphQL 请求，右键选择 `Copy` -> `Copy as cURL`。
6. 分别保存为这些文件名：

```text
x_curl/UserTweets.curl
x_curl/UserTweetsAndReplies.curl
x_curl/UserSuperFollowTweets.curl
```

大致样例，真实内容会更长，并包含你的 cookie/token：

```bash
mkdir -p x_curl
cat > x_curl/UserTweets.curl <<'EOF_CURL'
curl 'https://x.com/i/api/graphql/.../UserTweets?variables=...&features=...' \
  -H 'authorization: Bearer ...' \
  -H 'cookie: auth_token=...; ct0=...' \
  -H 'x-csrf-token: ...' \
  -H 'x-twitter-active-user: yes'
EOF_CURL
```

注意：`x_curl/*.curl` 包含登录 cookie/token，已经被 `.gitignore` 忽略；不要提交或分享这些文件。

## 数据位置

- SQLite: `data/serenity.sqlite`
- 原始 X JSON: `data/raw/*.json`
- Dashboard: `dashboard/index.html`, `dashboard/styles.css`, `dashboard/app.js`

## 常用命令

```bash
.venv/bin/python scripts/ingest.py fetch-x --max-pages 20
.venv/bin/python scripts/ingest.py prices --days 700 --min-mentions 2
.venv/bin/python scripts/ingest.py stats
.venv/bin/python scripts/ingest.py diagnostics --min-mentions 2
```

情感分析（可选）：

```bash
cp .env.example .env   # 填写 OPENAI_API_KEY，DeepSeek 等兼容网关需设 OPENAI_BASE_URL
.venv/bin/python scripts/analyze_sentiment.py direct --limit 20        # 少量提及，直接模式
.venv/bin/python scripts/analyze_sentiment.py batch-create --limit 1000 # 大量回填，Batch API
.venv/bin/python scripts/analyze_sentiment.py batch-import --batch-results data/openai_batches/results.jsonl
```

配置说明：
- 默认模型 `gpt-5.4-mini`，通过 `.env` 的 `OPENAI_SENTIMENT_MODEL` 或 `--model` 覆盖
- `-f` / `--force` 重新分析已有情感的提及（切换模型、调整 prompt 后使用）
- `batch-create` 在 Batch API 不可用时自动回退到 direct 模式并直接写入数据库
- `direct` 模式每批最多 50 条提及一起发送，比逐条调用快得多

注意：`x_curl/*.curl` 内的登录态可能过期；若抓取返回空或报错，重新从浏览器复制 curl 后再运行。

Media handling stores image metadata and `pbs.twimg.com` URLs from X responses. It does not download or mirror image bytes locally.

---

# Serenity Signal Dashboard (English)

This project is a fork of [haskaomni/serenity](https://github.com/haskaomni/serenity) with additional features:

- **OpenAI sentiment analysis** — LLM-based sentiment classification (positive / negative / neutral / mixed) for each symbol mention, visualized in the dashboard

The original project provides X fetching, price downloads, and dashboard visualization. This fork reads X GraphQL curl commands from `x_curl/`, parses posts, replies, and premium posts from `@aleabitoreddit`, extracts `$SYMBOL` mentions, stores them in a local SQLite database, and downloads daily price bars from Yahoo's chart API.

![Serenity dashboard screenshot](docs/assets/dashboard.png)

## Hosted Version

The original project offers a hosted version. Subscribe to [@iamai_omni](https://x.com/iamai_omni/creator-subscriptions/subscribe), then visit [app.k2ai.dev](https://app.k2ai.dev) to use it directly. You can also scan this QR code to open the subscription page:

<img src="docs/assets/iamai-omni-subscribe-qr.png" alt="Subscribe to @iamai_omni QR code" width="220">

> This project is for research and visualization only. It is not financial advice.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

.venv/bin/python scripts/ingest.py all --max-pages 10 --days 500 --min-mentions 3
.venv/bin/python scripts/server.py --port 8787
```

Python 3.10+ is required; this repository uses `str | None` type annotations.

Open `http://127.0.0.1:8787`.

## Copy X Requests From Chrome

`scripts/ingest.py fetch-x` reads browser-copied requests from `x_curl/`. You need to refresh these files when setting up the project or when the X session expires.

1. Log in to X with Chrome and open `https://x.com/aleabitoreddit`.
2. Open DevTools with `F12` or `Cmd/Ctrl + Shift + I`.
3. Go to `Network`, select `Fetch/XHR`, and optionally filter by `UserTweets`.
4. Refresh the page and scroll a few times so X loads posts, replies, or premium content.
5. Find the GraphQL requests below, right-click each one, then choose `Copy` -> `Copy as cURL`.
6. Save them with these exact filenames:

```text
x_curl/UserTweets.curl
x_curl/UserTweetsAndReplies.curl
x_curl/UserSuperFollowTweets.curl
```

Approximate example; the real command is longer and includes your cookie/token values:

```bash
mkdir -p x_curl
cat > x_curl/UserTweets.curl <<'EOF_CURL'
curl 'https://x.com/i/api/graphql/.../UserTweets?variables=...&features=...' \
  -H 'authorization: Bearer ...' \
  -H 'cookie: auth_token=...; ct0=...' \
  -H 'x-csrf-token: ...' \
  -H 'x-twitter-active-user: yes'
EOF_CURL
```

Warning: `x_curl/*.curl` contains login cookies/tokens and is ignored by `.gitignore`. Do not commit or share these files.

## Data Files

- SQLite: `data/serenity.sqlite`
- Raw X JSON: `data/raw/*.json`
- Dashboard: `dashboard/index.html`, `dashboard/styles.css`, `dashboard/app.js`

## Common Commands

```bash
.venv/bin/python scripts/ingest.py fetch-x --max-pages 20
.venv/bin/python scripts/ingest.py prices --days 700 --min-mentions 2
.venv/bin/python scripts/ingest.py stats
.venv/bin/python scripts/ingest.py diagnostics --min-mentions 2
```

Sentiment analysis (optional):

```bash
cp .env.example .env   # set OPENAI_API_KEY; also set OPENAI_BASE_URL for DeepSeek etc.
.venv/bin/python scripts/analyze_sentiment.py direct --limit 20        # few mentions, direct mode
.venv/bin/python scripts/analyze_sentiment.py batch-create --limit 1000 # bulk backfill, Batch API
.venv/bin/python scripts/analyze_sentiment.py batch-import --batch-results data/openai_batches/results.jsonl
```

Configuration:
- Default model `gpt-5.4-mini`; override via `.env` `OPENAI_SENTIMENT_MODEL` or `--model`
- `-f` / `--force` re-analyzes mentions that already have sentiment rows
- `batch-create` auto-falls back to direct mode when Batch API is unavailable, writing results immediately
- `direct` sends up to 50 mentions per API call for speed

If X fetching returns empty or invalid responses, copy fresh curl commands from Chrome and run the ingestion again.
