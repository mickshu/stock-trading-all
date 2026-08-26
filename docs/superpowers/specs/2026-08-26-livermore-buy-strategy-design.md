# 利弗莫尔买入法策略（自选股持仓列表）设计文档

日期：2026-08-26
状态：已获用户批准（方案 A：后端实时计算 + 新 API 端点）

## 背景与目标

在自选股（Watchlist）的「持仓」列表中新增「利弗莫尔买入法」策略。用户点击每行的「利弗莫尔」按钮，弹出居中 Modal 浮层，展示基于该股 K 线自动计算的关键点（pivotal point）、突破状态、止损位与金字塔加仓建议；支持录入持仓成本/股数/计划资金以获得个性化建议；策略参数可在浮层内调整并重算。

用户已确认的决策：

- 自动计算版（后端从 K 线计算，不做静态规则清单）
- 入口：持仓列表每行按钮（仅「持仓」标签 tab 下显示）
- 浮层形式：居中 Modal（AntD，宽 720px）
- 支持录入持仓成本（成本、股数、计划资金），保存后建议个性化
- 关键点口径：综合关键点（近 60 日新高 + 近 20 日箱体上沿，双级展示）
- 方案 A：后端新增 livermore 服务 + API 端点

## 策略计算口径

**关键点（双级展示）**

- 主关键点 = 近 60 个交易日（不含当日）最高价 —— 中期阻力位
- 平台位 = 近 20 个交易日（不含当日）箱体上沿（区间最高价）
- 突破判定四级：
  - 收盘价 > 主关键点 → 「突破确认 · 买入」
  - 现价盘中 > 主关键点、收盘未确认 → 「盘中突破」
  - 现价站上平台位但未到主关键点 → 「接近关键点」
  - 其余 → 「观望」
- 现价 < 止损位 → 附加「跌破止损 · 离场」警告

**止损位** = 主关键点 × (1 − stop_pct%)，默认 5%。

**金字塔加仓（默认参数，可调）**

- 首仓 30%；之后每上涨 3% 加 20%，最多 3 级 → 30% / 50% / 70% / 90% 封顶（留 10% 机动）
- 已录入持仓成本 + 计划资金：当前仓位% = 成本×股数 ÷ 计划资金，给出个性化建议（「触发后以 30% 计划资金建仓」/「距下一加仓点 X%」/「已满仓不加」）
- 未录计划资金：只展示各档价位与通用比例

**参数默认值**：`high_n=60`、`box_n=20`、`stop_pct=5`、`first_pct=30`、`add_step_pct=3`、`add_pct=20`、`levels=3`，全部可在浮层内调整后重算。

## 后端设计

### 数据模型

`backend/models/models.py` 的 `Watchlist` 新增 3 列（`backend/database.py` 走现有轻量 ALTER TABLE 迁移模式）：

- `cost` Float — 持仓成本
- `shares` Float — 股数
- `planned_capital` Float — 计划投入资金（可选）

更新走现有 `PATCH /api/stocks/{stock_id}`（`backend/api/stocks.py`），按 `target_price` 同款校验模式新增 3 个字段。

### 计算服务

`backend/services/livermore.py`：

- 纯函数 `compute_livermore(df, params, holding) -> dict`
- 入参：日 K DataFrame（复用 `backend/api/analysis.py::_load_kline_df` 链路）+ 参数 + 持仓信息
- 输出：关键点、平台位、止损位、突破状态、距关键点%、加仓档位表、个性化建议、近 90 日 OHLC（供迷你 K 线）
- 不依赖数据库，方便单测

### API

挂载在现有 `backend/api/analysis.py` 路由下：

- `GET /api/analysis/livermore?code=...&high_n=60&box_n=20&stop_pct=5&first_pct=30&add_step_pct=3&add_pct=20&levels=3`
- 逻辑：查 Watchlist 拿持仓字段 → 拉 K 线 → 计算 → 返回 JSON（一次往返，含迷你 K 线数据）
- 参数校验：`high_n∈[20,250]`、`box_n∈[5,120]` 且 `box_n<high_n`、`stop_pct∈[1,20]`、`first_pct∈[5,100]`、`add_step_pct∈[0.5,20]`、`add_pct∈[5,50]`、`levels∈[1,5]`，非法返回 422
- 模块级内存缓存，key = (code, 参数 tuple)，TTL 300 秒

### 测试

`backend/test_services.py` 追加 `test_livermore_*`，沿用现有 `_synthetic_df` 合成 K 线验证：

- 关键点/箱体上沿计算
- 四种突破状态（突破确认 / 盘中突破 / 接近关键点 / 观望）
- 止损位计算
- 加仓档位与个性化建议
- 参数校验报错

## 前端设计

### 入口

`frontend/src/pages/Watchlist.tsx`，仅在「持仓」标签 tab（`holding` 过滤）下显示：

- 桌面表格「操作」列加「利弗莫尔」按钮（分析 / 利弗莫尔 / 删除）
- 移动端卡片操作区加同款按钮
- 点击 → `setModalStock(record)` 弹出 Modal

### 浮层组件

新组件 `frontend/src/components/LivermoreModal.tsx`（AntD Modal，宽 720px，内容可滚动）：

1. 标题：「利弗莫尔买入法 · {名称} {代码}」
2. 状态区：当前价 + 状态 Tag（突破确认/盘中突破/接近关键点/观望，红色高亮）+ 距关键点 %
3. 关键价位卡片：主关键点 / 平台位 / 止损位 / 距止损跌幅
4. 金字塔加仓表：各档（首仓 30%、+3%、+6%、+9%）价位与建议金额
5. 持仓录入行：成本 / 股数 / 计划资金（InputNumber，保存后本地更新并重算建议）
6. 参数设置（折叠面板）：6 个参数 InputNumber → 改完重取计算
7. 迷你 K 线：复用 `KlineChart` 组件，标注关键点/止损线（markLine）
8. 风险提示：利弗莫尔规则提醒（突破买入、跌破止损离场、让利润奔跑），灰色小字

### API 客户端

`frontend/src/api/analysis.ts` 新增 `fetchLivermore(code, params)`；`frontend/src/api/stocks.ts` 的更新接口支持 cost/shares/planned_capital 字段。

### 错误处理

- K 线不足 30 根 → 友好提示「数据不足，无法计算关键点」
- 数据源异常 → 错误文案 + 重试按钮
- 停牌 → 显示最近收盘价并标注日期
- 持仓保存失败 → `message.error`
- Modal 内 loading 态

### 合规项

- `frontend/src/components/AppLayout.tsx` 版本水印 bump 到 `v.26.08.26_1`
- `npm run lint` + `npm run build` 通过

## 数据流

1. 用户在持仓 tab 点击某行「利弗莫尔」→ `setModalStock(record)`
2. Modal 挂载 → `GET /api/analysis/livermore?code=...`（含该股持仓信息）→ 渲染
3. 调整参数 → 带参重取（缓存命中秒回）
4. 录入持仓 → `PATCH /api/stocks/{id}` → 成功后更新本地状态并重算建议
5. 关闭 → 卸载

## 部署

实现 + 测试通过后：提交并推送 main，触发 `POST /api/updatereload`（git pull + 后端 reload + 前端 build）。
