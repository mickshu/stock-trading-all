# 主站新增「投研站」入口设计

日期：2026-08-14
状态：已确认

## 背景

`/home/admin/.stock-invest-master/`（外部分析报告目录）已通过 `backend/main.py` 挂载为 `/stock-invest-master/` 路由（含目录列表页，代码已写好但未提交），公网 `http://121.43.159.62:8000/stock-invest-master/` 实测可访问（200 OK）。

用户需求：让该目录作为网站站点可被访问。经澄清，**维持现状形态**（目录列表 + 原始 md 文本），只需在主站前端加入口导航，方便访问。

## 非目标（明确不做）

- 不做 md → HTML 渲染
- 不做独立端口 / 独立站点
- 不做鉴权、上传、编辑

## 方案决策

在 3 个候选（侧边栏菜单项 / 行情页卡片 / Header 链接）中选定 **A. 侧边栏菜单项「投研站」**：与现有导航一致、桌面 + 移动端都有入口、最显眼。

## 改动点

### 1. `frontend/src/components/AppLayout.tsx`

- `menuItems` 在「AI 分析」之后加一项：
  `{ key: '/stock-invest-master/', icon: <FolderOpenOutlined />, label: '投研站', external: true }`
- 桌面 `Menu` 的 `onClick` 分支：`external` 项 → `window.open(key, '_blank')` 并 return；其余照旧 `navigate(key)`
- 移动端底部导航同样分支处理（`onClick` 与键盘 Enter/Space 两个入口）
- 外部项不会被选中：`selectedKeys={[location.pathname]}` 永远不会等于该 key，无额外处理

### 2. `frontend/vite.config.ts`

- 代理增加 `'/stock-invest-master': { target: 'http://localhost:8000', changeOrigin: true }`
- 原因：开发模式新窗口打开的是 `http://localhost:5173/stock-invest-master/`，不加代理会被 Vite SPA fallback 劫持返回 React 页面；生产模式（FastAPI 同源 8000）不需要

### 3. 版本水印

- `AppLayout.tsx` 水印 `v.26.07.31_10` → `v.26.08.14_1`（项目强制约定）

### 4. 提交 `backend/main.py` 挂载代码

- `/stock-invest-master/` 路由 + 目录列表页代码是本次入口功能的依赖，一并提交
- **只提交 `backend/main.py`**，不提交 `backend.log` / `frontend.log` / `dingtalk_note.md`（后者含明文密钥，需单独脱敏处理，不在本次范围）

## 验证

1. `cd frontend && npm run lint` 通过
2. `npm run build` 通过（生产构建）
3. 手工验证：
   - 生产 8000：点「投研站」→ 新窗口打开目录列表页（200）
   - 开发 5173：同上（验证代理生效）
   - 桌面侧栏 + 移动端底部导航均不误触发 SPA 路由、不选中高亮
4. 水印显示 `v.26.08.14_1`
