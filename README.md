# 多平台店铺销售日报

基于京东商智、唯品会导出的商品明细数据，通过 **DuckDB + Vercel Serverless Function（Flask）** 生成交互式销售日报。支持多平台、多店铺整合展示与平台切换。

**线上地址**：https://sales-report-self.vercel.app

---

## 架构

```
┌──────────────┐     fetch      ┌──────────────────┐     read     ┌────────────────┐
│ index.html   │ ──────────────→│ api/data.py      │─────────────→│ report.duckdb  │
│   ~48KB      │←──── JSON ─────│ (Flask Function) │←──read_only──│   ~5.5MB       │
└──────────────┘                └──────────────────┘              └────────────────┘
      数据源: ~/Desktop/Platform-Date/{JD,VIP}/Import/*.xlsx
             └── scripts/build_all_shop_daily.py 构建入库 ──┘
```

| 组件 | 大小 | 说明 |
|------|------|------|
| `index.html` | ~48KB | 轻量 HTML，运行时 fetch `/api/data` 加载数据 |
| `api/data.py` | ~7KB | Flask 入口（`app`），读 DuckDB（read_only）返回 JSON |
| `api/report.duckdb` | ~5.5MB | 函数打包读取的数据库副本（构建后自动同步） |
| `api/data/report.duckdb` | ~5.5MB | 构建主输出（10 张表） |

> ⚠️ Vercel 文件系统只读，duckdb 必须 `connect(path, read_only=True)`；
> ⚠️ 新版 Python runtime 只支持 Flask/ASGI `app` 入口，不再支持裸 `handler`。

---

## 数据平台与店铺

| 平台 | 店铺 | 指标口径 |
|------|------|----------|
| 京东 POP（6 店） | 飞鹤成人 / 完达山 / 维维豆奶粉 / 怡佳悦选 / 北纬47° / 西麦食品饮料 | 商智官方合计行；含转化率、客单价、UV价值、退款、加购、搜索 |
| 唯品会（2 店） | 维维食品特卖 / 西麦食品特卖 | 明细求和；仅销售额/销售量/客户数/商详UV，类目记为「未分类」，退款等缺失指标置 0 |

- 两平台同名品牌（维维/西麦）为**不同店铺主体**，独立展示不合并。
- 前端顶部「平台」切换器：全部平台 / 京东 / 唯品会，联动店铺列表、KPI 与图表。

---

## 目录结构

```
sales-report/
├── templates/                     # ★ Vercel Root Directory
│   ├── index.html                 # 轻量 HTML（运行时 fetch /api/data）
│   ├── all_shop_template.html     # HTML 模板源码（.vercelignore 排除）
│   ├── server.py                  # 本地开发服务器（.vercelignore 排除）
│   ├── vercel.json                # builds + routes（Flask function + static）
│   ├── _redirects                 # SPA fallback
│   ├── .vercelignore              # 部署排除规则
│   ├── favicon.ico / .png
│   └── api/
│       ├── data.py                # Flask Function（app + /api/data 路由）
│       ├── requirements.txt       # flask + duckdb
│       ├── report.duckdb          # ★ 函数打包读取的库（构建后自动同步）
│       └── data/report.duckdb     # 构建主输出
├── scripts/
│   ├── config.py                  # ⚙️ 配置中心（平台目录/店铺/阈值/窗口）
│   ├── build_all_shop_daily.py    # 构建脚本（多平台 Excel → DuckDB + HTML）
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

### 日常更新（标准流程）

```bash
cd ~/Documents/GitHub/sales-report

# 1. 构建（自动读取两个平台目录，自动同步 db 到 api/）
python3 scripts/build_all_shop_daily.py

# 2. 提交推送（push 即自动触发 Vercel 部署）
git add -A && git add -f templates/api/report.duckdb templates/api/data/report.duckdb
git commit -m "report $(date +%m-%d)" && git push
```

### 本地预览

```bash
cd templates && python3 server.py
# 浏览器打开 http://127.0.0.1:8081（强刷 Cmd+Shift+R）
# ⚠️ 不要直接双击 HTML，必须通过 http:// 访问
```

### 数据源目录

默认（`scripts/config.py`）：

| 平台 | 目录 | 环境变量覆盖 |
|------|------|--------------|
| 京东 | `~/Desktop/Platform-Date/JD/Import` | `DATA_DIR_JD`（兼容旧 `DATA_DIR`） |
| 唯品会 | `~/Desktop/Platform-Date/VIP/Import` | `DATA_DIR_VIP` |

文件命名：`{店铺名}_商品明细_{YYYY-MM-DD}[_sku].xlsx`（`_sku` 后缀京东有、唯品会无）。

---

## Vercel 配置

| 配置项 | 值 |
|--------|-----|
| Root Directory | `templates` |
| Framework Preset | Other |
| Build Command | 留空 |

`.vercelignore` 自动排除 `server.py`、`all_shop_template.html`。

---

## 配置说明（`scripts/config.py`）

| 配置项 | 说明 |
|--------|------|
| `PLATFORM_DIRS` | 各平台数据源目录 |
| `SHOPS` | 店铺列表 `(显示名, 简称, 排序, 平台)`——增删店铺只改这里，前端文案自动跟随店铺数 |
| `PLATFORMS` | 平台显示名（前端平台切换器） |
| `ALERT_RULES` | 预警规则阈值 |
| `OPP_MIN_VISITORS` / `OPP_CONV_RATIO` | 机会品识别条件 |
| `RECENT_DAYS` / `RESEARCH_DAYS` | 时间窗口大小 |
| `DB_PATH` | DuckDB 数据库路径 |

---

## 报表模块

| # | 模块 | 说明 |
|---|------|------|
| 1 | 核心指标 | GMV/件数/单量/客户数/访客/转化/客单价/UV价值，环比+前7日均值+上周同日 |
| 2 | GMV 归因 | 访客×转化×客单价乘法归因 |
| 3 | 7日优化研究 | 增长质量、反复流量浪费、头部依赖 |
| 4 | GMV/转化趋势 | 平台与店铺切换联动 |
| 5 | 店铺当日表现 | 贡献率、环比、访客、转化 |
| 6 | 类目结构 | 一/二/三级类目汇总（唯品会记「未分类」） |
| 7 | TOP SKU | 按 GMV 排序，支持店铺筛选 |
| 8 | 升降榜 | 日环比增长/下滑 |
| 9 | 预警系统 | 高危/关注/SKU/机会四级 |
| 10 | 全周期总览 | 每日汇总 |
| 11 | 数据质量 | 完整性/新鲜度检查；数据不全时顶部黄色警告条列出缺失日期、缺失店铺与空文件（0 行导出） |
| 12 | 筛选器 | 平台 + 日期 + 店铺三级联动 |

---

## 预警规则

| 级别 | 类型 | 条件 |
|------|------|------|
| 🔴 高危 | GMV下滑 | 环比 ≥20% 且 ≥¥500 |
| 🟡 关注 | 流量下滑 | 环比 ≥30% 且 ≥100人 |
| 🟡 关注 | 转化走弱 | 低于前日 75% 且下降 ≥1pp |
| 🟡 关注 | 退款偏高 | 退款率 ≥5% 且 ≥¥300（唯品会无退款数据，不触发） |
| ⚪ SKU | SKU大幅下滑 | 减少 ≥¥500 且降幅 ≥50% |
| 🔵 机会 | 高流量低转化 | 访客 ≥100 且转化 < 整体 ×75% |
