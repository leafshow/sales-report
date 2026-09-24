# 数据优化说明

## 架构：DuckDB + Serverless Function

| 组件 | 大小 | 说明 |
|------|------|------|
| `index.html` | 45KB | 轻量 HTML，运行时从 `/api/data` 加载 |
| `api/data.py` | 6KB | Vercel Serverless Function |
| `report.duckdb` | ~5MB | DuckDB 数据库（10张表） |
| `requirements.txt` | 14B | Python 依赖声明 |

## 数据库表结构

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

## 数值精度优化

| 数据类型 | 优化前 | 优化后 | 示例 |
|----------|--------|--------|------|
| GMV/金额 | 11 位小数 | 2 位小数 | 35582.18 |
| 转化率 | 17 位小数 | 6 位小数 | 0.105443 |
| 客单价 | 11 位小数 | 2 位小数 | 97.99 |

移除 13 个辅助字段：pv, searchImpressions, searchClicks, productImpressions,
productImpressionUsers, orderAmount, orderCount, orderBuyers, unitPrice,
searchCtr, addCartRate, orderConversion, orderCompletion。

## 精度影响

- GMV 误差：< ¥0.01（可忽略）
- 转化率误差：< 0.000001（不影响可视化）
- 环比计算：精度足够（误差 < 0.01%）
