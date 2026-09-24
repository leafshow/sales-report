"""京东店铺商智日报 - 配置中心

所有可调参数集中于此，修改后重新运行构建脚本即可生效。
"""
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────────
# INPUT：数据源目录（Excel 文件存放位置）
#   - 默认：项目根目录下 data/ 目录（首次使用前请将 Excel 文件放入）
#   - 也可通过环境变量 DATA_DIR 覆盖，例如：
#     DATA_DIR=/path/to/jd-export python3 scripts/build_all_shop_daily.py
import os
_INPUT_OVERRIDE = os.environ.get('DATA_DIR', '')
if _INPUT_OVERRIDE:
    INPUT = Path(_INPUT_OVERRIDE)
else:
    INPUT = Path(__file__).parent.parent / 'data'
# OUT：生成的报表 HTML（自动定位到 templates/index.html）
OUT = Path(__file__).parent.parent / 'templates' / 'index.html'
# TEMPLATE：HTML 模板源码（含 __DATA__ 占位符，用于离线内嵌版）
TEMPLATE = Path(__file__).parent.parent / 'templates' / 'all_shop_template.html'
# API_DATA_DIR：构建脚本输出的 JSON 数据目录（供 Vercel serverless function 读取）
API_DATA_DIR = Path(__file__).parent.parent / 'templates' / 'api' / 'data'
# DB_PATH：DuckDB 数据库文件路径（构建时写入，Vercel 运行时读取）
DB_PATH = API_DATA_DIR / 'report.duckdb'

# ── 文件匹配 ──────────────────────────────────────────────────────────────────
# 商品明细文件命名规则：{店铺名}_商品明细_{日期}_sku.xlsx
FILE_PATTERN = r'^(.+)_商品明细_(\d{4}-\d{2}-\d{2})_sku\.xlsx$'

# ── 店铺列表 ──────────────────────────────────────────────────────────────────
# 格式：{Excel文件名中的店铺名} : (显示名, 简称, 排序序号)
# 增减店铺只需在此增删行，排序序号决定下拉框顺序
SHOPS = {
    '飞鹤成人奶粉旗舰店': ('飞鹤成人奶粉旗舰店', '飞鹤', 10),
    '完达山成人奶粉旗':   ('完达山成人奶粉旗舰店', '完达山', 20),
    '维维豆奶粉旗舰店':   ('维维豆奶粉旗舰店', '维维', 30),
    '怡佳悦选旗舰店':     ('怡佳悦选旗舰店', '怡佳悦选', 40),
    '北纬 47°旗舰店':     ('北纬47°旗舰店', '北纬47°', 50),
    '西麦食品饮料旗舰店':  ('西麦食品饮料旗舰店', '西麦', 60),
}

# ── 数据字段 ──────────────────────────────────────────────────────────────────
# 参与计算和对比的数值字段
FIELDS = [
    'gmv','units','orders','buyers','visitors','pv',
    'searchImpressions','searchClicks','productImpressions',
    'productImpressionUsers','addCartUsers','orderAmount',
    'orderCount','orderBuyers','refundAmount',
]

# Excel 表头列名（商智导出的列顺序）
COLUMNS = [
    '时间','SKU','SKU名称','一级类目','二级类目','三级类目',
    '成交金额','成交商品件数','成交单量','成交客户数','商品访客数',
    '商品浏览量','搜索曝光次数','搜索点击次数','商品曝光次数',
    '商品曝光人数','加购客户数','下单金额','下单单量','下单客户数',
    '取消及售后退款金额',
]

# ── 预警阈值 ──────────────────────────────────────────────────────────────────
# 每一项格式：(比例条件, 金额/人数条件, 告警级别, 类型中文名, 描述文案)
# 当两个条件同时满足时触发告警
ALERT_RULES = [
    # 店铺级
    {
        'level': 'high', 'type': 'GMV下滑',
        'ratio_cond': lambda c, p: p['gmv'] and c['gmv']/p['gmv'] - 1 <= -0.20,
        'abs_cond':   lambda c, p: p['gmv'] - c['gmv'] >= 500,
        'detail': '店铺GMV环比下降超20%且减少金额超500元',
    },
    {
        'level': 'medium', 'type': '流量下滑',
        'ratio_cond': lambda c, p: p['visitors'] and c['visitors']/p['visitors'] - 1 <= -0.30,
        'abs_cond':   lambda c, p: p['visitors'] - c['visitors'] >= 100,
        'detail': '店铺访客数环比下降超30%且减少超100人',
    },
    {
        'level': 'medium', 'type': '转化走弱',
        'ratio_cond': lambda c, p: c['conversion'] is not None and p['conversion'] is not None and c['conversion'] < p['conversion'] * 0.75,
        'abs_cond':   lambda c, p: p['conversion'] is not None and c['conversion'] is not None and p['conversion'] - c['conversion'] >= 0.01,
        'detail': '店铺成交转化率低于前日75%且下降超1个百分点',
    },
    {
        'level': 'medium', 'type': '退款偏高',
        'ratio_cond': lambda c, p: c['refundRate'] is not None and c['refundRate'] >= 0.05,
        'abs_cond':   lambda c, p: c['refundAmount'] is not None and c['refundAmount'] >= 300,
        'detail': '店铺退款金额率达5%以上且金额超300元',
    },
    # SKU 级（delta 为负值表示下滑）
    {
        'level': 'sku', 'type': 'SKU大幅下滑',
        'ratio_cond': lambda x: x['delta'] <= -500 and x['previousGmv'] and x['gmv']/x['previousGmv'] <= 0.5,
        'abs_cond':   lambda x: False,  # SKU 只用 ratio_cond
        'detail': 'SKU GMV环比减少超过500元且降幅超过50%',
    },
]

# 高流量低转化机会品条件
OPP_MIN_VISITORS = 100          # 访客数下限
OPP_CONV_RATIO   = 0.75         # 转化率低于整体比例
OPP_PER_ALERT    = 5            # 每个日期最多展示的机会品告警数
ALERT_PER_DATE   = 60           # 每个日期最多告警总数

# ── 展示数量限制 ──────────────────────────────────────────────────────────────
TOP_SKU_POOL       = 35         # TOP SKU 候选池大小（用于去重合并）
TOP_PER_SHOP_POOL  = 15         # 每个店铺额外补充的 SKU 数
DAILY_SHIFT_LIMIT  = 25         # 每日升降榜每类最多条目
DAILY_PER_SHOP     = 10         # 每个店铺额外补充的升降条目数
OPP_PER_DAY        = 15         # 每日机会品候选数
OPPORTUNITIES_MAX  = 12         # 7日优化研究中反复出现的 SKU 机会品上限

# ── 时间窗口 ──────────────────────────────────────────────────────────────────
RECENT_DAYS   = 7   # 优化研究：近 N 日
PRIOR_DAYS    = 7   # 优化研究：前 N 日（与 RECENT_DAYS 相同）
RESEARCH_DAYS = 14  # 反复低转化 SKU 追踪窗口
BASELINE_WIN  = 7   # 基线计算：取前 N 日平均
WEEK_AGO_WIN  = 7   # 上周同日：偏移 N 天
