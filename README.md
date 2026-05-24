# Serenity Signal Dashboard

本项目抓取 `x_curl/` 中的 X GraphQL curl，解析 `@aleabitoreddit` 的帖子、回复、订阅帖，抽取 `$SYMBOL`，写入本地 SQLite，并用 Yahoo chart 接口下载日线价格。

## 快速开始

```bash
python3 scripts/ingest.py all --max-pages 10 --days 500 --min-mentions 3
python3 scripts/server.py --port 8787
```

打开 `http://127.0.0.1:8787`。

## 数据位置

- SQLite: `data/serenity.sqlite`
- 原始 X JSON: `data/raw/*.json`
- Dashboard: `dashboard/index.html`, `dashboard/styles.css`, `dashboard/app.js`

## 常用命令

```bash
python3 scripts/ingest.py fetch-x --max-pages 20
python3 scripts/ingest.py prices --days 700 --min-mentions 2
python3 scripts/ingest.py stats
```

注意：`x_curl/*.curl` 内的登录态可能过期；若抓取返回空或报错，重新从浏览器复制 curl 后再运行。

## Python environment

For packages that are not available in the system Python environment, use the project virtualenv:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```
