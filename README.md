# 多平台店铺销售日报

基于京东商智、唯品会、拼多多导出的商品数据，通过 **DuckDB + Vercel Serverless Function（Flask）** 生成交互式销售日报。支持多平台、多店铺整合展示与平台切换。

**线上地址**：https://sales-report-self.vercel.app

---

## 架构

```
┌──────────────┐     fetch      ┌──────────────────┐     read     ┌────────────────┐
│ index.html   │ ──────────────→│ api/data.py      │─────────────→│ report.duckdb  │
│   ~51KB      │←──── JSON ─────│ (Flask Function) │←──read_only──│   ~5.3MB       │
└──────────────┘                └──────────────────┘              └────────────────┘
      数据源: ~/Desktop/Platform-Date/{JD,VIP}/Import/*.xlsx
             └── scripts/build_all_shop_daily.py 构建入库 ──┘
```

| 组件 | 大小 | 说明 |
|------|------|------|
| `index.html` | ~51KB | 轻量 HTML，运行时 fetch `/api/data` 加载数据 |
| `api/data.py` | ~7KB | Flask 入口（`app`），读 DuckDB（read_only）返回 JSON |
| `api/report.duckdb` | ~5.3MB | 函数打包读取的数据库副本（构建后自动同步） |
| `api/data/report.duckdb` | ~5.3MB | 构建主输出（10 张表） |

> ⚠️ Vercel 文件系统只读，duckdb 必须 `connect(path, read_only=True)`；
> ⚠️ 新版 Python runtime 只支持 Flask/ASGI `app` 入口，不再支持裸 `handler`。

---

## 数据平台与店铺

| 平台 | 店铺 | 指标口径 |
|------|------|----------|
| 京东 POP（6 店） | 飞鹤成人 / 完达山 / 维维豆奶粉 / 怡佳悦选 / 北纬47° / 西麦食品饮料 | 商智官方合计行；含转化率、客单价、UV价值、退款、加购、搜索 |
| 唯品会（2 店） | 维维食品特卖 / 西麦食品特卖 | 明细求和；仅销售额/销售量/客户数/商详UV，类目记为「未分类」，退款等缺失指标置 0 |
| 拼多多（4 店） | 飞鹤成人奶粉旗舰店 / 完达山怡佳永盛专卖店 / 维维怡佳永盛专卖店 / 怡佳永盛食品专营店 | 商智「商品数据」单日快照（67 列）；含访客/浏览/收藏/成交买家数/三级类目；无搜索与曝光（列全 0），无日粒度退款 |
| 京东自营（12 注册 / 8 展示） | 西麦京东自营 / 维维豆奶京东自营 / 飞鹤成人奶粉京东自营 / 西麦SEAMILD冲饮 / 西麦五谷粉粉 / 飞鹤爱本 / JimBarry葡萄酒 / 1号会员店（隐藏：睿思 / 北纬妈咪 / 新主良 / 未分配） | **双口径**：零售成交（经营状况表）+ 供货出库（供应链库存表），见下方「京东自营双口径」 |

- 两平台同名品牌（维维/西麦）为**不同店铺主体**，独立展示不合并。
- 前端顶部「平台」切换器：全部平台 / 京东 / 唯品会 / 拼多多 / 京东自营，联动店铺列表、KPI 与图表。
- 数据目录已扁平化：`~/Desktop/Platform-Date/{JD,VIP,PDD,JD_SELF}/`（无 Import 子目录）。

### 京东自营双口径

京东自营有两类源文件，按 `(日期, 店铺)` 合并为唯一一行：

| 源表 | 文件 | 口径 | 字段 |
|---|---|---|---|
| 经营状况商品明细 | `{店铺}_经营状况商品明细_YYYY-MM-DD.xlsx` | 零售成交 | 成交金额/件数/单量/人数、访客、PV、加购 |
| 供应链库存-商品明细 | `{供应商}_自营商品明细_YYYY-MM-DD.xlsx` | 供货出库 | 出库金额（采购价×昨日出库件数）、出库件数、可用库存额、近30日出库额 |

- **窗口累计文件自动跳过**：经营状况表「时间」列含「至」（如 `2026-09-01至2026-09-25`）为区间累计而非单日快照，跳过并记录到 `quality.windowFiles`。
- **派生指标**：零售/出库比、库存周转率（近30日出库额÷可用库存额）、库存周转天数。
- **前端展示**：所有平台基础版式一致（GMV=成交金额）；选择京东自营时，核心 KPI、店铺表现、类目结构、当日 SKU、7日优化研究、GMV 归因各表末尾追加「出库金额」（及 KPI/归因的「出库件数」）列/卡；另有「自营双口径 KPI」「自营库存健康」两个专属 section。
- **缺失数据源显示 —**：如某店铺只有库存表无经营状况记录（如飞鹤成人），零售列显示 `—`，数据源状态列标注「仅库存」。

### 拼多多指标映射

| 框架字段 | 源列 |
|---|---|
| `gmv` / `orderAmount` | 成交金额 |
| `units` | 成交件数 |
| `orders` / `orderCount` | 成交订单数 / 确认订单数 |
| `buyers` / `orderBuyers` | 成交买家数 / 下单用户数 |
| `visitors` / `pv` | 商品访客数 / 商品浏览量 |
| `addCartUsers` | 商品收藏用户数（拼多多无加购口径，收藏等同加购） |
| `sku` / `name` / `category1~3` | 商品ID / 商品名称 / 一~三级类目 |

**已知缺失**（源表无对应数据，按 0 处理）：

| 字段 | 原因 | 影响 |
|---|---|---|
| `searchImpressions` / `searchClicks` | 无搜索维度 | 搜索曝光/点击/CTR 恒 0 |
| `productImpressions` / `productImpressionUsers` | `曝光用户数` 列存在但全 0 | 曝光漏斗失效 |
| `refundAmount` | 仅 `近30日` 滚动累计，与日粒度 GMV 不同口径 | 退款率恒 0，退款偏高预警不触发 |

> `近30日成功退款金额` ÷ 当日 `成交金额` ≈ 1043%，不可直接作为日退款；同行均值、推广策略、各类环比等 35 列按「不新增字段」原则过滤。

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
| 拼多多 | `~/Desktop/Platform-Date/PDD/Import` | `DATA_DIR_PDD` |

文件命名：

| 平台 | 格式 |
|------|------|
| 京东 | `{店铺名}_商品明细_{YYYY-MM-DD}_sku.xlsx` |
| 唯品会 | `{店铺名}_商品明细_{YYYY-MM-DD}.xlsx` |
| 拼多多 | `{店铺名}_商品数据_{YYYY-MM-DD}.csv` |

> 各平台日期取**并集**，店铺按 `(shop, date)` 独立聚合，某店某日缺文件自动跳过。

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
| `shops_visibility.json` | **店铺显示/隐藏配置**：`{"hidden": ["平台|店铺名", ...], "hiddenPlatforms": ["vip", ...]}`；隐藏店铺不参与聚合与展示。缺失/解析失败时全部显示。可用环境变量 `SHOP_VISIBILITY_FILE` 覆盖路径 |

---

## 报表模块

| # | 模块 | 说明 |
|---|------|------|
| 1 | 核心指标 | GMV/件数/单量/客户数/访客/转化/客单价/UV价值，环比+前7日均值+上周同日 |
| 2 | GMV 归因 | 访客×转化×客单价乘法归因 |
| 3 | 7日优化研究 | 增长质量、反复流量浪费、头部依赖 |
| 4 | GMV/转化趋势 | 平台与店铺切换联动；>1250px 双列等宽并排，≤1250px 单列堆叠 |
| 5 | 店铺当日表现 | 贡献率、环比、访客、转化 |
| 6 | 类目结构 | 一/二/三级类目汇总（唯品会记「未分类」） |
| 7 | TOP SKU | 按 GMV 排序，支持店铺筛选 |
| 8 | 升降榜 | 日环比增长/下滑 |
| 9 | 预警系统 | 高危/关注/SKU/机会四级 |
| 10 | 全周期总览 | 每日汇总 |
| 11 | 数据质量 | 完整性/新鲜度检查；数据不全时顶部黄色警告条列出缺失日期、缺失店铺与空文件（0 行导出） |
| 12 | 筛选器 | 平台 + 日期 + 店铺三级联动 |

---

## 优化历程

| 日期 | Commit | 阶段 | 内容 |
|------|--------|------|------|
| 2026-09-24 | `e06797e` | **项目立项** | 京东 POP 6 店销售日报从零搭建：DuckDB + Vercel Serverless（Flask）架构；`build_all_shop_daily.py` 构建入库（10 张表：meta/quality/overall/shop_daily/categories 等）；前端 12 个模块（KPI、GMV 归因、7日优化研究、趋势、店铺表现、类目、TOP SKU、升降榜、预警、总览、数据质量、三级筛选）；配套 docs（OPTIMIZATION/USAGE/VERCEL_DEPLOY）、启动脚本、favicon |
| 2026-09-24 | `cb26833` `3201a0d` | **首次部署** | 提交 5MB `report.duckdb` 完成首次 Git 部署；调整 `rootDirectory=templates` 触发线上生效 |
| 2026-09-24 | `df63318` | **部署修复** | Vercel 新版 Python runtime 不再支持裸 `handler`，改为 Flask `app` 入口；duckdb 连接改 `read_only=True` 适配只读文件系统；`vercel.json` 补 `builds` + `routes`；API 200 OK |
| 2026-09-26 | `c5033ac` | **数据链路修复** | 修复 `api_json` NameError；构建后自动把 db 同步到 `api/` 供函数打包读取，避免手工拷贝遗漏 |
| 2026-09-26 | `ffb9ca0` | **易用性** | `INPUT` 默认目录改为 `~/Desktop/Platform-Date/Import`（此前为 `JD-Date`），构建无需每次传参 |
| 2026-09-28 | `a968651` | **多平台接入** | 集成唯品会平台，店铺 6 → 8；新增顶部平台切换器（全部/京东/唯品会），联动店铺列表、KPI、图表；唯品会按明细求和、类目记「未分类」、缺失指标（退款等）置 0；同名品牌跨平台独立不合并 |
| 2026-09-30 | `c7346fb` | **排版优化** | ① 集中度表「最高GMV SKU」列：表头与内容统一左对齐，去除 560px 宽度限制，商品名一行完整展示（截断 + hover tooltip）<br>② 店铺当日表现条形图行：店铺名强制单行 `white-space:nowrap`，列宽由内容自适应（移除固定 `92px`/`145px` 硬编码）<br>③ GMV/转化趋势图表：>1250px 改为同行左右均分双列等宽布局，≤1250px 单列堆叠 |
| 2026-10-01 | — | **优化历程补全 + 拼多多数据源升级** | **① 优化历程记录**：README 补齐 09-24 ~ 09-28 全部阶段（项目立项 / 首次部署 / 部署修复 / 数据链路修复 / 易用性 / 多平台接入），新增 Commit 列可定位改动<br>**② 拼多多数据源切换**：由「订单 CSV」（07-01~09-29 单文件全周期）改为商智「商品数据」单日快照 CSV（67 列），店铺 8 → 12<br>**③ 补齐缺失指标**：`visitors` / `buyers` / `pv` / `addCartUsers`（映射商品收藏用户数）/ 三级类目；原口径下这些字段恒为 0，导致 GMV 归因、转化趋势、机会品识别对拼多多全部失效<br>**④ 过滤冗余**：35 列丢弃（同行均值 / 推广策略 / 各类环比 / 活动信息）；`近30日` 退款因口径不匹配（日粒度 vs 30 日滚动累计，比值 1043%）不采用，`refundAmount` 保持 0，与唯品会同等<br>**⑤ 连带修复**：日期区间由「平台交集」改为「并集」（旧交集逻辑为 PDD 超长历史设计，会把京东/唯品会 29 天裁到 1 天）；`svg_conversion_chart` 单日数据除零崩溃<br>**⑥ 结果**：拼多多 4 店 × 30 天（09-01~09-30）无缺日，12 个模块全部生效，转化率趋势 / baseline / week / GMV 归因 / 集中度 / 机会品均可正常计算 |

---

## 预警规则

| 级别 | 类型 | 条件 |
|------|------|------|
| 🔴 高危 | GMV下滑 | 环比 ≥20% 且 ≥¥500 |
| 🟡 关注 | 流量下滑 | 环比 ≥30% 且 ≥100人 |
| 🟡 关注 | 转化走弱 | 低于前日 75% 且下降 ≥1pp |
| 🟡 关注 | 退款偏高 | 退款率 ≥5% 且 ≥¥300（唯品会、拼多多无日粒度退款数据，不触发） |
| ⚪ SKU | SKU大幅下滑 | 减少 ≥¥500 且降幅 ≥50% |
| 🔵 机会 | 高流量低转化 | 访客 ≥100 且转化 < 整体 ×75% |
