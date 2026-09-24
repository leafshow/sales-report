# 京东 POP 店铺销售日报

基于京东商智导出的商品明细数据，通过 **DuckDB + Vercel Serverless Function** 生成交互式销售日报。

---

## 架构

```
┌──────────────┐     fetch      ┌──────────────────┐     read     ┌────────────────┐
│ index.html   │ ──────────────→│ api/data.py      │─────────────→│ report.duckdb  │
│   45KB       │←──── JSON ─────│ (Serverless)     │←────────────│    ~5MB        │
└──────────────┘                └──────────────────┘              └────────────────┘
```

| 组件 | 大小 | 说明 |
|------|------|------|
| `index.html` | 45KB | 轻量 HTML，运行时 fetch `/api/data` 加载数据 |
| `api/data.py` | 6KB | Vercel Serverless Function，读 DuckDB 返回 JSON |
| `report.duckdb` | ~5MB | DuckDB 数据库（10 张表），构建时自动生成 |

---

## 目录结构

```
db-fetch-report/
├── templates/                     # ★ Vercel Root Directory
│   ├── index.html                 # 轻量 HTML（运行时 fetch /api/data）
│   ├── all_shop_template.html     # HTML 模板源码（.vercelignore 排除）
│   ├── server.py                  # 本地开发服务器（.vercelignore 排除）
│   ├── vercel.json                # Vercel 路由：/api/data → function，/* → index
│   ├── _redirects                 # SPA fallback
│   ├── .vercelignore              # Vercel 部署排除规则
│   ├── favicon.ico / .png
│   └── api/
│       ├── data.py                # Serverless Function
│       ├── requirements.txt       # duckdb>=1.0.0
│       └── data/
│           └── report.duckdb      # 主数据库（10 张表）
├── scripts/
│   ├── config.py                  # ⚙️ 配置中心
│   ├── build_all_shop_daily.py    # 构建脚本（Excel → DuckDB + HTML）
│   ├── start-server.sh            # 本地服务器启动
│   ├── open-report.command        # macOS 双击启动
│   └── view-report.command        # macOS 后台启动
├── docs/
│   ├── USAGE.md                   # 使用指南
│   ├── OPTIMIZATION.md            # 数据优化说明
│   └── VERCEL_DEPLOY.md           # 部署指南
└── README.md
```

---

## 快速开始

### 本地使用

```bash
# 1. 构建（Excel → DuckDB + HTML）
cd scripts
DATA_DIR=~/Desktop/JD-Date python3 build_all_shop_daily.py

# 2. 启动本地服务器（静态文件 + /api/data API）
./start-server.sh

# 3. 浏览器打开 http://127.0.0.1:8081/index.html
#    ⚠️ 不要直接双击 HTML 文件，必须通过 http:// 访问
```

### 部署到 Vercel

```bash
# 1. 本地构建
DATA_DIR=~/Desktop/JD-Date python3 scripts/build_all_shop_daily.py

# 2. 推送代码和数据库
git add templates/ scripts/ docs/ README.md .gitignore
git add templates/api/data/report.duckdb
git commit -m "report $(date +%Y-%m-%d)"
git push
```

**Vercel Dashboard 配置：**

| 配置项 | 值 |
|--------|-----|
| Root Directory | `db-fetch-report/templates` |
| Framework Preset | Other |
| Build Command | 留空 |
| Output Directory | 留空 |
| Python Runtime | 3.11+（自动） |

`.vercelignore` 自动排除 `server.py` 和 `all_shop_template.html`。

---

## 数据更新

```bash
# 1. 将新日期 Excel 放入数据源目录（或 DATA_DIR 指向的目录）
#    命名格式：{店铺名}_商品明细_{YYYY-MM-DD}_sku.xlsx

# 2. 重新构建
DATA_DIR=~/Desktop/JD-Date python3 scripts/build_all_shop_daily.py

# 3. 推送更新（只需提交 DuckDB 文件）
git add templates/api/data/report.duckdb
git commit -m "update $(date +%Y-%m-%d)"
git push
```

---

## 配置说明（`scripts/config.py`）

| 配置项 | 说明 |
|--------|------|
| `INPUT` | 数据源目录（默认 `data/`，可通过 `DATA_DIR` 环境变量覆盖） |
| `SHOPS` | 店铺列表（增减店铺只改这里） |
| `ALERT_RULES` | 四级预警规则阈值 |
| `OPP_MIN_VISITORS` / `OPP_CONV_RATIO` | 机会品识别条件 |
| `RECENT_DAYS` / `RESEARCH_DAYS` | 时间窗口大小 |
| `TOP_SKU_POOL` / `DAILY_SHIFT_LIMIT` | 展示数量上限 |
| `DB_PATH` | DuckDB 数据库路径 |
| `OUT` | 生成的 HTML 输出路径 |
| `TEMPLATE` | HTML 模板路径 |

---

## DuckDB 表结构

| 表名 | 行数 | 内容 |
|------|------|------|
| `meta` | 3 | 生成时间、店铺列表、日期列表 |
| `quality` | 18 | 数据质量检查结果 |
| `overall` | ~23 | 每日六店铺汇总（含 baseline/week） |
| `shop_daily` | ~138 | 每日每店铺明细 |
| `categories` | ~744 | 类目汇总（shop × 三级类目） |
| `top_skus` | ~2,228 | TOP SKU 列表 |
| `movers` | ~2,867 | 升降榜（risers + fallers） |
| `alerts` | ~288 | 预警记录 |
| `charts` | 14 | SVG 图表（ALL + 6店各2个） |
| `optimization` | ~58 | 7日优化研究扁平化数据 |

---

## 功能模块（14 个）

| # | 模块 | 说明 |
|---|------|------|
| 1 | 经营结论 | 自动 headline + 5条 insight |
| 2 | 核心 KPI | 10 项指标，日环比 / 前7日均值 / 上周同日 |
| 3 | GMV 归因 | 访客 × 转化率 × 客单价 乘法分解 |
| 4 | 7日优化研究 | 近7日 vs 前7日，店铺增长质量 + 机会品 + 集中度 |
| 5 | GMV 趋势 | SVG 柱状图，点击日期联动 |
| 6 | 转化率趋势 | SVG 折线图，与 GMV 同步选中 |
| 7 | 店铺表现 | 条形占比图 + 详细指标表 |
| 8 | 类目结构 | 一/二/三级类目 GMV 汇总 |
| 9 | TOP SKU | 按 GMV 排序，支持店铺筛选 |
| 10 | 升降榜 | 日环比增长/下滑 TOP10 |
| 11 | 预警系统 | 高危/关注/SKU/机会 四级预警 |
| 12 | 全周期总览 | 每日汇总大表 |
| 13 | 数据质量 | 7 项完整性检查 |
| 14 | 筛选器 | 日期下拉 + 店铺下拉，全局联动 |

---

## 预警规则

| 级别 | 类型 | 条件 |
|------|------|------|
| 🔴 高危 | GMV下滑 | 环比 ≥20% 且 ≥¥500 |
| 🟡 关注 | 流量下滑 | 环比 ≥30% 且 ≥100人 |
| 🟡 关注 | 转化走弱 | 低于前日 75% 且下降 ≥1pp |
| 🟡 关注 | 退款偏高 | 退款率 ≥5% 且 ≥¥300 |
| ⚪ SKU | SKU大幅下滑 | 减少 ≥¥500 且降幅 ≥50% |
| 🔵 机会 | 高流量低转化 | 访客 ≥100 且转化 < 整体 ×75% |
