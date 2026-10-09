"""京东店铺商智日报 - 配置中心

所有可调参数集中于此，修改后重新运行构建脚本即可生效。
"""
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────────
# 各平台数据源目录（Excel 文件存放位置）
#   - 也可通过环境变量覆盖：DATA_DIR_JD / DATA_DIR_VIP
import os
PLATFORM_DIRS = {
    'jd':  Path(os.environ.get('DATA_DIR_JD',  Path.home() / 'Desktop' / 'Platform-Date' / 'JD')),
    'vip': Path(os.environ.get('DATA_DIR_VIP', Path.home() / 'Desktop' / 'Platform-Date' / 'VIP')),
    'pdd': Path(os.environ.get('DATA_DIR_PDD', Path.home() / 'Desktop' / 'Platform-Date' / 'PDD')),
    'jd_self': Path(os.environ.get('DATA_DIR_JD_SELF', Path.home() / 'Desktop' / 'Platform-Date' / 'JD_SELF')),
    'tmall': Path(os.environ.get('DATA_DIR_TMALL', Path.home() / 'Desktop' / 'Platform-Date' / 'TMALL')),
    'vip_jitx': Path(os.environ.get('DATA_DIR_VIP_JITX', Path.home() / 'Desktop' / 'Platform-Date' / 'VIP_JITX')),
}
# 兼容旧变量：DATA_DIR 覆盖京东目录
if os.environ.get('DATA_DIR', ''):
    PLATFORM_DIRS['jd'] = Path(os.environ['DATA_DIR'])
INPUT = PLATFORM_DIRS['jd']  # 兼容旧引用
# OUT：生成的报表 HTML（自动定位到 templates/index.html）
OUT = Path(__file__).parent.parent / 'templates' / 'index.html'
# TEMPLATE：HTML 模板源码（含 __DATA__ 占位符，用于离线内嵌版）
TEMPLATE = Path(__file__).parent.parent / 'templates' / 'all_shop_template.html'
# API_DATA_DIR：构建脚本输出的 JSON 数据目录（供 Vercel serverless function 读取）
API_DATA_DIR = Path(__file__).parent.parent / 'templates' / 'api' / 'data'
# DB_PATH：DuckDB 数据库文件路径（构建时写入，Vercel 运行时读取）
DB_PATH = API_DATA_DIR / 'report.duckdb'

# ── 文件匹配 ──────────────────────────────────────────────────────────────────
# 京东：{店铺名}_商品明细_{日期}_sku.xlsx；唯品会：{店铺名}_商品明细_{日期}.xlsx
FILE_PATTERN = r'^(.+)_商品明细_(\d{4}-\d{2}-\d{2})(?:_sku)?\.xlsx$'
# 拼多多：{店铺名}_商品数据_{统计日期}.csv（单日商品维度快照，60 列含访客/浏览/收藏/同行均值）
FILE_PATTERN_PDD = r'^(.+)_商品数据_(\d{4}-\d{2}-\d{2})\.csv$'
# 京东自营：{供应商名}_自营商品明细_{日期}.xlsx（供应商视角库存/出库明细，店铺维度取表内「店铺名称」列）
FILE_PATTERN_JD_SELF = r'^(.+)_自营商品明细_(\d{4}-\d{2}-\d{2})\.xlsx$'
# 京东自营横版库存导出：默认横版-YYYYMMDD-…-离线-<hash>.xlsx（含 ~90 城市现货库存列，供城市库存预警）
FILE_PATTERN_JD_SELF_CITY = r'^默认横版-(\d{8})-.*\.xlsx$'
# ── 模块级店铺黑白名单（前端各模块独立生效）────────────────────────────────
# key = 模块名；值 = {"black": [...], "white": [...]}
#   black：隐藏的店铺（key=平台|店铺名），仅该模块不展示
#   white：仅展示的店铺；为空列表 = 不启用白名单（展示全部未被全局隐藏/黑名单排除的店铺）
# 可用模块：
#   shop_daily        店铺当日表现（含日报表明细的店铺行）
#   self_kpi          自营双口径 KPI
#   stock_health      自营库存健康
#   city_alert        头部商品城市库存预警
#   categories        类目结构
#   sku_daily         当日 SKU 表现
#   movers            GMV 增长/下滑 SKU
#   alerts            异常与机会预警
#   optimization      店铺增长质量（含集中度）
#   attribution       GMV 变化归因
MODULE_SHOPS_FILTER = {
    # 头部商品城市库存预警：仅维维、西麦相关店铺
    'city_alert': {'black': [], 'white': [
        'jd_self|西麦京东自营旗舰店',
        'jd_self|维维豆奶京东自营旗舰店',
        'jd_self|西麦SEAMILD冲饮京东自营旗舰店',
        'jd_self|西麦五谷粉粉京东自营旗舰店',
    ]},
}
# 京东自营城市库存数据源（可替换）：
#   city_source: "vertical" = 纵版 RDC 列（推荐，根目录 怡佳永盛供应商_自营商品明细_*.xlsx）
#                "horizontal" = 横版宽表（默认横版-YYYYMMDD-*.xlsx，每城市一列，已废弃但保留适配）
JD_CITY_SOURCE = os.environ.get('JD_CITY_SOURCE', 'vertical')
# 主要 RDC 城市列表（城市库存预警范围）
MAIN_CITIES = ['北京', '上海', '广州', '成都', '武汉', '沈阳', '西安']
# 京东自营流量表（经营状况）：{供应商名}_经营状况商品明细_{日期}.xlsx（商智标准字段）
FILE_PATTERN_JD_SELF_TRAFFIC = r'^(.+)_经营状况商品明细_(\d{4}-\d{2}-\d{2})\.xlsx$'
# 天猫：{店铺名}_商品报表_{日期}.xls（生意参谋商品报表，表头位于第 5 行，含支付金额/支付买家数/商品访客数等 38 列）
FILE_PATTERN_TMALL = r'^(.+)_商品报表_(\d{4}-\d{2}-\d{2})\.xls$'
# 唯品会 JITX：{店铺名}JITX销售*销售数据.xlsx（单文件多日累积，含「日期」列，构建时按日拆分；店铺名含 JITX 后缀）
FILE_PATTERN_VIP_JITX = r'^((?:\S+?)JITX)销售\S*销售数据\.xlsx$'

# ── 店铺列表 ──────────────────────────────────────────────────────────────────
# 格式：{(平台, 文件名店铺名)} : (显示名, 简称, 排序序号)
# 用 (平台, 店铺名) 复合键：不同平台可能存在同名店铺（如京东与拼多多均有「飞鹤成人奶粉旗舰店」）
SHOPS = {
    # 京东 POP
    ('jd', '飞鹤成人奶粉旗舰店'):   ('飞鹤成人奶粉旗舰店', '飞鹤(JD)', 10),
    ('jd', '完达山成人奶粉旗'):     ('完达山成人奶粉旗舰店', '完达山(JD)', 20),
    ('jd', '维维豆奶粉旗舰店'):     ('维维豆奶粉旗舰店', '维维(JD)', 30),
    ('jd', '怡佳悦选旗舰店'):       ('怡佳悦选旗舰店', '怡佳悦选', 40),
    ('jd', '北纬 47°旗舰店'):       ('北纬47°旗舰店', '北纬47°', 50),
    ('jd', '西麦食品饮料旗舰店'):   ('西麦食品饮料旗舰店', '西麦(JD)', 60),
    ('jd', '认养一头牛冲饮奶粉旗舰店'): ('认养一头牛冲饮奶粉旗舰店', '认养一头牛(JD)', 65),
    # 唯品会
    ('vip', '维维食品特卖旗舰店'):   ('维维食品特卖旗舰店', '维维(VIP)', 70),
    ('vip_jitx', '维维JITX'):        ('维维旗舰店', '维维', 75),
    ('vip', '西麦食品特卖旗舰店'):   ('西麦食品特卖旗舰店', '西麦(VIP)', 80),
    # 拼多多
    ('pdd', '飞鹤成人奶粉旗舰店'):   ('飞鹤成人奶粉旗舰店', '飞鹤(PDD)', 90),
    ('pdd', '完达山怡佳永盛专卖店'): ('完达山怡佳永盛专卖店', '完达山(PDD)', 100),
    ('pdd', '维维怡佳永盛专卖店'):   ('维维怡佳永盛专卖店', '维维(PDD)', 110),
    ('pdd', '怡佳悦选食品旗舰店'):   ('怡佳悦选食品旗舰店', '怡佳悦选(PDD)', 118),
    # 天猫（生意参谋商品报表）
    ('tmall', '完达山怡佳永盛专卖店'): ('完达山怡佳永盛专卖店', '完达山(TMALL)', 125),
    ('tmall', '怡通永盛食品专营店'):   ('怡通永盛食品专营店', '怡通永盛(TMALL)', 126),
    ('tmall', '飞鹤牧场旗舰店'):       ('飞鹤牧场旗舰店', '飞鹤牧场(TMALL)', 127),
    # 京东自营（供应商视角，店铺维度来自表内「店铺名称」列）
    ('jd_self', '西麦京东自营旗舰店'):         ('西麦京东自营旗舰店', '西麦(自营)', 130),
    ('jd_self', '维维豆奶京东自营旗舰店'):     ('维维豆奶京东自营旗舰店', '维维(自营)', 140),
    ('jd_self', '飞鹤成人奶粉京东自营旗舰店'): ('飞鹤成人奶粉京东自营旗舰店', '飞鹤(自营)', 150),
    ('jd_self', '西麦SEAMILD冲饮京东自营旗舰店'): ('西麦冲饮京东自营旗舰店', '西麦冲饮(自营)', 160),
    ('jd_self', '西麦五谷粉粉京东自营旗舰店'): ('西麦五谷粉粉京东自营旗舰店', '西麦五谷(自营)', 170),
    ('jd_self', '飞鹤爱本京东自营旗舰店'):     ('飞鹤爱本京东自营旗舰店', '飞鹤爱本(自营)', 180),
    ('jd_self', 'Jim Barry葡萄酒京东自营旗舰店'): ('JimBarry葡萄酒京东自营旗舰店', 'JimBarry(自营)', 190),
    ('jd_self', '睿思（Ravensburger） 京东自营旗舰店'): ('睿思京东自营旗舰店', '睿思(自营)', 200),
    ('jd_self', '北纬妈咪京东自营旗舰店'):     ('北纬妈咪京东自营旗舰店', '北纬妈咪(自营)', 210),
    ('jd_self', '新主良京东自营旗舰店'):       ('新主良京东自营旗舰店', '新主良(自营)', 220),
    ('jd_self', '1号会员店'):                 ('1号会员店', '1号店(自营)', 230),
    ('jd_self', '未分配'):                    ('未分配（无店铺）', '未分配(自营)', 240),
}

# 平台显示名（前端平台切换器用）
PLATFORMS = {'jd_self': '京东自营', 'jd': '京东POP', 'tmall': '天猫', 'vip': '唯品会', 'vip_jitx': '唯品会JITX', 'pdd': '拼多多'}

# ── 店铺显示/隐藏配置 ────────────────────────────────────────────────────────
# 独立 JSON 配置文件：scripts/shops_visibility.json
#   {"hidden": ["jd_self|未分配", ...], "hiddenPlatforms": []}
#   - hidden：隐藏的店铺（内部 key = 平台|店铺名），不参与聚合、图表与前端展示
#   - hiddenPlatforms：隐藏整个平台（如临时下线 vip）
# 环境变量 SHOP_VISIBILITY_FILE 可覆盖配置文件路径
import json as _json
VISIBILITY_FILE = Path(os.environ.get(
    'SHOP_VISIBILITY_FILE',
    Path(__file__).parent / 'shops_visibility.json'))
def _load_visibility():
    try:
        cfg = _json.loads(VISIBILITY_FILE.read_text(encoding='utf-8'))
        return set(cfg.get('hidden', [])), set(cfg.get('hiddenPlatforms', []))
    except FileNotFoundError:
        return set(), set()
    except Exception as e:
        print(f"⚠️  店铺可见性配置解析失败（忽略）: {VISIBILITY_FILE}: {e}")
        return set(), set()
HIDDEN_SHOPS, HIDDEN_PLATFORMS = _load_visibility()

# 生效店铺列表 = SHOPS - 隐藏店铺 - 隐藏平台店铺（保持注册顺序）
SHOPS_VISIBLE = {
    k: v for k, v in SHOPS.items()
    if f"{k[0]}|{k[1]}" not in HIDDEN_SHOPS and k[0] not in HIDDEN_PLATFORMS
}

# ── 数据字段 ──────────────────────────────────────────────────────────────────
# 参与计算和对比的数值字段
FIELDS = [
    'gmv','units','orders','buyers','visitors','pv',
    'searchImpressions','searchClicks','productImpressions',
    'productImpressionUsers','addCartUsers','orderAmount',
    'orderCount','orderBuyers','refundAmount',
]

# 自营新增字段（仅 jd_self 平台店铺有效）
SELF_FIELDS = [
    'gmvOutbound',      # 出库金额（采购价 × 昨日出库件数）
    'unitsOutbound',    # 出库件数（昨日出库件数）
    'stockValue',       # 可用库存额（现货库存 × 采购价）
    'out30dValue',      # 近30日出库额（近30日出库件数 × 采购价）
]
# 自营额外字段也参与部分聚合（如平台总和）
ALL_FIELDS = FIELDS + SELF_FIELDS

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
