# ETF 支持设计文档

**日期**: 2026-07-31
**状态**: 待实施
**范围**: A 股 ETF 全功能支持，对标个股

---

## 概述

在现有个股分析系统中新增 ETF 支持，通过 `security_type` 字段区分股票和 ETF，数据源/API/前端根据类型自动适配展示。

---

## 一、数据模型

### 1.1 watchlist 表变更

```sql
ALTER TABLE watchlist ADD COLUMN security_type VARCHAR(10) DEFAULT 'stock';
-- 可选值: 'stock' | 'etf'
```

`market` 字段不变，A 股 ETF 也使用 `"A"`。`(code, market)` 唯一约束保持不变——同一代码不能重复加入自选。

### 1.2 SQLAlchemy 模型

`backend/models/models.py` — `Watchlist` 类新增字段：

```python
security_type = Column(String(10), default="stock")
```

### 1.3 数据库迁移

`backend/database.py` 的 `_migrate()` 函数中新增 ALTER TABLE 逻辑，自动兼容已有数据库。

---

## 二、数据源层

### 2.1 前缀函数修复（关键）

三个静态方法需要识别 ETF 代码的交易所归属：

| 函数 | 当前逻辑 | 修复后 |
|------|---------|--------|
| `_exchange_prefix` | 60/68→sh, 其他→sz | 5/6/68→sh; 0/3/15/16/18→sz |
| `_em_secid` | 60/68/11/13→1, 其他→0 | 5/6/68/11/13→1; 0/3/15/16/18→0 |
| `_tencent_symbol` | 60/68→sh, 其他→sz | 5/6/68→sh; 0/3/15/16/18→sz |

ETF 代码规则：
- 上海 ETF: 51xxxx, 56xxxx, 58xxxx（均以 5 开头）
- 深圳 ETF: 159xxx, 16xxxx, 18xxxx

### 2.2 search_stocks

- 股票索引：保持现有 `stock_info_a_code_name()` 缓存
- ETF 索引：新增 `fund_etf_spot_em()` 全量 ETF 列表缓存（24h TTL），提取代码和名称
- 搜索结果合并，每条结果带 `security_type` 标记
- 拼音搜索对 ETF 名称同样生效

### 2.3 get_kline

```python
def get_kline(self, code, period, start_date, end_date):
    if self._is_etf(code):
        # 日/周/月线
        return self._get_etf_kline(code, period, start_date, end_date)
    else:
        # 现有股票逻辑
        ...
```

ETF K 线通过 `fund_etf_hist_em(symbol, period, start_date, end_date, adjust="qfq")` 获取，列重命名映射与股票一致。日内周期使用 `fund_etf_hist_min_em()`。

### 2.4 get_realtime_quote / get_quotes_batch

前缀修复后，EastMoney push2 ulist.np 批量接口已自然支持 ETF（ETF spot 和股票 spot 共用字段 `f2/f3/f5/f6/f62/f184`）。仅需确保 `_em_secid` 返回正确市场 ID。

### 2.5 get_fundamentals

根据 `security_type` 返回不同结构：

**个股（现有字段不变）：**
```
code, name, price, change_pct, pe, pe_ttm, pb, ps_ttm, dv_ttm,
total_market_cap, float_market_cap, total_shares, float_shares,
industry, listing_date, as_of
```

**ETF（新增字段）：**
```
code, name, price, change_pct,
iopv（实时净值估算）, discount_rate（折溢价率%）,
total_size（最新份额，亿份）, total_market_cap（总规模=份额×净值）,
tracking_index（跟踪指数名称）, management_fee（管理费率%）,
listing_date, as_of
```

数据来源：
- `fund_etf_spot_em()` — IOPV、折价率、最新份额
- `fund_etf_fund_info_em()` — 历史净值
- `fund_etf_scale_sse()` / `fund_etf_scale_szse()` — 上市日期、管理费率

### 2.6 screen_stocks（条件选股批量行情）

- 全市场模式：股票用 `m:0+t:6,m:0+t:80,...` FS，ETF 用 `b:MK0021,b:MK0022,b:MK0023,b:MK0024` FS
- 自选股模式：按 codes 逐个查询，类型无关
- ETF 结果中 PE/PB 字段为 null，保留 price/change_pct/volume/amount/amplitude/turnover 等交易指标

### 2.7 _is_etf 辅助方法

```python
@staticmethod
def _is_etf(code: str) -> bool:
    return code.startswith(("51", "56", "58", "159", "16", "18"))
```

---

## 三、API 层

### 3.1 现有 API 改动

| 端点 | 改动 |
|------|------|
| `GET /api/v1/stocks/search` | 返回结果中每条增加 `security_type` 字段 |
| `POST /api/v1/stocks` | 新增可选参数 `security_type`（默认 "stock"） |
| `GET /api/v1/stocks` | 返回结果增加 `security_type` 字段 |
| `GET /api/v1/market/fundamentals` | ETF 代码返回 ETF 专用字段 |
| `GET /api/v1/screener/condition` | 新增 ETF 条件参数：`discount_rate_min/max`, `size_min/max`；scope 支持 `all_etf` |

### 3.2 新增 API

| 端点 | 说明 |
|------|------|
| `GET /api/v1/market/etf-list` | ETF 全量列表，支持排序/分页/分类筛选 |

### 3.3 向后兼容

- 所有现有 API 不传 `security_type` 时默认行为不变
- 已有前端调用无需修改即可继续工作

---

## 四、前端改动

### 4.1 类型定义 (`types/index.ts`)

```typescript
type SecurityType = 'stock' | 'etf';

interface StockInfo {
  // ... 现有字段
  security_type?: SecurityType;  // 新增
}

// 新增 ETF 基本面类型
interface EtfFundamentals {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  iopv: number | null;            // 实时净值
  discount_rate: number | null;   // 折溢价率
  total_size: number | null;      // 最新份额（亿份）
  total_market_cap: number | null;
  tracking_index: string;         // 跟踪指数
  management_fee: number | null;  // 管理费率
  listing_date: string;
  as_of: string | null;
}
```

### 4.2 自选股页面 (`Watchlist.tsx`)

- 搜索下拉结果：ETF 项标记 `[ETF]` 标签
- 列表表格：ETF 行显示 "ETF" 小标签（类似现有持仓/关注标签）
- 添加弹窗：无需改动，搜索即可返回 ETF
- 其他（分组、标签、目标价、提醒）：完全复用

### 4.3 详情页 (`StockDetail.tsx`)

- **ETF 时隐藏**：「财务指标」Tab（ETF 无财报）
- **ETF 基本面卡片** (`FundamentalsCard.tsx`)：根据 `security_type` 切换展示字段
  - 个股：PE、PB、PS、股息率、总市值、流通市值、总股本、流通股
  - ETF：IOPV、折溢价率、最新份额、跟踪指数、管理费率
- **K线图 + 技术指标 + 信号**：完全复用，无改动
- **AI 分析面板**：分析维度预设按 ETF 调整（如"技术面"、"资金面"、"折溢价分析"）

### 4.4 筛选器 (`Screener.tsx`)

- 顶部新增「类型」切换：全部 A 股 | ETF
- 股票模式：保持现有 PE/PB/市值/涨跌幅/换手率/量比/振幅/成交额
- ETF 模式：**隐藏** PE/PB/市值；**新增** 折溢价率范围、规模范围；**保留** 涨跌幅/换手率/量比/振幅/成交额
- 结果列表：ETF 模式下 PE/PB 列显示 "—"

### 4.5 Dashboard

- 首版不动，后续可加 ETF 资金流向卡片

### 4.6 杂项

- `eastMoneyUrl()` 函数：ETF 代码前缀逻辑与股票一致（上海→sh，深圳→sz），无需改动
- 版本号：更新 AppLayout 水印

---

## 五、不做（首版范围外）

- ETF 的 TradingAgents 多智能体分析（K线+指标+信号已覆盖分析需求）
- ETF 申赎 / 一级市场数据
- 跨境 ETF / 港股 ETF / 美股 ETF
- ETF 定投计算器
- ETF 持仓穿透（查看 ETF 底层股票）

---

## 六、实施顺序

1. **数据源层**：前缀修复 → ETF K线 → ETF 行情 → ETF 搜索 → ETF 基本面
2. **数据模型**：Watchlist 加字段 + 数据库迁移
3. **API 层**：现有 API 适配 + 新增 ETF 列表端点
4. **前端**：类型定义 → 搜索&自选股 → 详情页 → 筛选器 → 水印版本号
5. **测试验证**：端到端验证 ETF 搜索/添加/详情/筛选全流程
