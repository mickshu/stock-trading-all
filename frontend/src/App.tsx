import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, Spin } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { Suspense, lazy } from 'react';
import AppLayout from './components/AppLayout';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Watchlist = lazy(() => import('./pages/Watchlist'));
const StockDetail = lazy(() => import('./pages/StockDetail'));
const Screener = lazy(() => import('./pages/Screener'));
const Settings = lazy(() => import('./pages/Settings'));
const TradingAgentsPage = lazy(() => import('./pages/TradingAgents'));

const fallback = (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 240 }}>
    <Spin />
  </div>
);

const lazyRoute = (Component: React.LazyExoticComponent<React.ComponentType>) => (
  <Suspense fallback={fallback}>
    <Component />
  </Suspense>
);

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route index element={lazyRoute(Dashboard)} />
            <Route path="stocks" element={lazyRoute(Watchlist)} />
            <Route path="stock/:code" element={lazyRoute(StockDetail)} />
            <Route path="screener" element={lazyRoute(Screener)} />
            <Route path="ai" element={<Navigate to="/trading-agents" replace />} />
            <Route path="trading-agents" element={lazyRoute(TradingAgentsPage)} />
            <Route path="settings" element={lazyRoute(Settings)} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
