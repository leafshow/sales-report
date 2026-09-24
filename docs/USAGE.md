# 使用指南

## 日常更新流程

### 1. 导出新数据
从京东商智导出最新日期的商品明细数据，命名为：
```
{店铺名}_商品明细_{YYYY-MM-DD}_sku.xlsx
```

### 2. 放入数据目录
将导出的文件放入：
```

```

### 3. 重新构建报表
```bash
cd db-fetch-report/scripts
python3 build_all_shop_daily.py
```

### 4. 启动报表
```bash
./start-server.sh
# 或
./open-report.command
```

## 常见问题

### Q: 浏览器显示"加载数据失败"
A: 确保通过HTTP服务器访问，不能直接打开HTML文件
```bash
# 错误方式
open index.html

# 正确方式
python3 -m http.server 8081
# 然后访问 http://127.0.0.1:8081/index.html
```

### Q: 数据不更新
A: 检查以下几点：
1. 数据文件是否正确放入Import目录
2. 文件名是否符合命名规范
3. 重新运行build脚本

### Q: 如何查看数据质量？
A: 报表底部有"数据质量与口径"模块，显示7项检查项的通过状态

## 文件说明

### build_all_shop_daily.py
核心构建脚本，执行以下步骤：
1. 扫描Import目录下的XLSX文件
2. 解析并验证数据结构
3. 计算各维度指标（店铺、类目、SKU）
4. 生成趋势图和预警分析
5. 输出 HTML 报表（数据内嵌，无需单独加载 JSON）

### index.html
报表 HTML 文件（~33KB），数据已内嵌，包含：
- 完整的 CSS 样式
- 前端渲染逻辑
- 交互式图表和表格

> 注：原 `jd_sales_data.json` 数据已合并至 HTML 内部，无需单独维护。

## 性能优化

- HTML仅33KB，数据已内嵌无需额外请求，加载速度极快
- 所有计算在构建时完成，前端只需渲染
- 支持离线使用（下载HTML后本地打开）
