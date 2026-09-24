# Vercel 部署指南

## 架构

| 文件 | 大小 | 作用 |
|------|------|------|
| `index.html` | 45KB | 前端页面，fetch `/api/data` 加载数据 |
| `api/data.py` | 6KB | Serverless Function，读 DuckDB 返回 JSON |
| `api/data/report.duckdb` | ~5MB | DuckDB 数据库（10 张表） |

## 部署步骤

```bash
# 1. 本地构建（Excel → DuckDB + HTML）
cd scripts
DATA_DIR=~/Desktop/JD-Date python3 build_all_shop_daily.py
cd ..

# 2. 推送到 GitHub（首次需携带数据库）
git add templates/ scripts/ docs/ README.md .gitignore
git add templates/api/data/report.duckdb
git commit -m "report $(date +%Y-%m-%d)"
git push
```

## Vercel 配置

| 配置项 | 值 |
|--------|-----|
| Root Directory | `db-fetch-report/templates` |
| Framework Preset | Other |
| Build Command | 留空 |
| Output Directory | 留空 |
| Python Runtime | 3.11+（自动） |

## 路由

| 路径 | 处理 |
|------|------|
| `/api/data` | `api/data.py` Serverless Function |
| `/*` | `index.html` SPA fallback |

## 排除文件（.vercelignore）

以下文件不会部署到 Vercel：
- `server.py` — 本地开发服务器
- `all_shop_template.html` — 构建模板源码

## 数据更新

```bash
# 1. 放入新 Excel → 重新构建
DATA_DIR=~/Desktop/JD-Date python3 scripts/build_all_shop_daily.py

# 2. 推送新数据库
git add templates/api/data/report.duckdb
git commit -m "update $(date +%Y-%m-%d)"
git push
```
