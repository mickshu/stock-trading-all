import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Spin,
  Alert,
  Typography,
  Segmented,
  Button,
  Space,
  Card,
  Grid,
  Tabs,
  Empty,
  Drawer,
  Checkbox,
  FloatButton,
} from 'antd';
import {
  ReloadOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
  ArrowLeftOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import KlineChart from '../components/KlineChart';
import SignalPanel from '../components/SignalPanel';
import SignalConfluence from '../components/SignalConfluence';
import FundamentalsCard from '../components/FundamentalsCard';
import FinancialHistoryTable from '../components/FinancialHistoryTable';
import TradingAgentsPanel from '../components/TradingAgentsPanel';
import { useAnalysisStore } from '../store/analysisStore';
import { fetchQuote } from '../api/market';
import type { Period } from '../types';

const { useBreakpoint } = Grid;

const periodOptions: { label: string; value: Period }[] = [
  { label: '日线', value: 'daily' },
  { label: '周线', value: 'weekly' },
  { label: '月线', value: 'monthly' },
];

type AnalysisTabKey = 'signal' | 'ai';

export default function StockDetail() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [stockName, setStockName] = useState('');
  const [price, setPrice] = useState<number | null>(null);
  const [changePct, setChangePct] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<AnalysisTabKey>('signal');
  const [signalDrawerOpen, setSignalDrawerOpen] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);

  const handleSignalClick = (pos: number) => {
    setHighlightPosition(pos);
    if (isMobile && chartRef.current) {
      chartRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  useEffect(() => {
    const prev = document.title;
    if (code) {
      document.title = stockName ? `${code} ${stockName} · 股票分析` : `${code} · 股票分析`;
    }
    return () => {
      document.title = prev;
    };
  }, [code, stockName]);
  const {
    klineData,
    signals,
    period,
    loading,
    error,
    showMA,
    showMACD,
    showKDJ,
    showRSI,
    showSignals,
    highlightPosition,
    setPeriod,
    setShowMA,
    setShowMACD,
    setShowKDJ,
    setShowRSI,
    setShowSignals,
    setHighlightPosition,
    loadAnalysis,
  } = useAnalysisStore();

  useEffect(() => {
    if (code) loadAnalysis(code);
  }, [code, period, loadAnalysis]);

  useEffect(() => {
    if (!code) return;
    fetchQuote(code)
      .then((q) => {
        setStockName(q.name || '');
        setPrice(typeof q.price === 'number' ? q.price : null);
        setChangePct(typeof q.change_pct === 'number' ? q.change_pct : null);
      })
      .catch(() => {
        setStockName('');
        setPrice(null);
        setChangePct(null);
      });
  }, [code]);

  if (!code) return <Alert type="error" message="未提供股票代码" />;

  const chartHeight = isMobile
    ? 350 + ([showMACD, showKDJ, showRSI].filter(Boolean).length * 80)
    : 450 + ([showMACD, showKDJ, showRSI].filter(Boolean).length * 110);

  const title = stockName ? `${code} ${stockName}` : code;

  const changeColor =
    changePct == null ? undefined : changePct > 0 ? '#cf1322' : changePct < 0 ? '#3f8600' : '#666';
  const changeSign = changePct != null && changePct > 0 ? '+' : '';

  const headerBar = (
    <div
      style={
        isMobile
          ? {
              position: 'sticky',
              top: 48,
              zIndex: 9,
              background: '#f5f5f5',
              padding: '8px 0',
              marginLeft: -12,
              marginRight: -12,
              paddingLeft: 12,
              paddingRight: 12,
              marginBottom: 8,
              borderBottom: '1px solid #eee',
            }
          : { marginBottom: 16 }
      }
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          flexWrap: 'wrap',
          justifyContent: 'space-between',
        }}
      >
        <Space wrap size={8} style={{ flex: 1, minWidth: 0 }}>
          {isMobile && (
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate(-1)}
              aria-label="返回"
              style={{ marginLeft: -4 }}
            />
          )}
          <Typography.Title level={isMobile ? 5 : 4} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
          {price != null && (
            <Space size={4} align="baseline">
              <Typography.Text strong style={{ fontSize: isMobile ? 16 : 18, color: changeColor }}>
                {price.toFixed(2)}
              </Typography.Text>
              {changePct != null && (
                <Typography.Text strong style={{ fontSize: isMobile ? 12 : 13, color: changeColor }}>
                  {changeSign}
                  {changePct.toFixed(2)}%
                </Typography.Text>
              )}
            </Space>
          )}
        </Space>
        <Space size={8} wrap>
          <Segmented
            options={periodOptions}
            value={period}
            onChange={(val) => setPeriod(val as Period)}
            size={isMobile ? 'small' : 'middle'}
          />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => loadAnalysis(code, true)}
            disabled={loading}
            size={isMobile ? 'small' : 'middle'}
            aria-label="刷新"
          >
            {isMobile ? '' : '刷新'}
          </Button>
        </Space>
      </div>
    </div>
  );

  return (
    <div>
      {headerBar}

      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}

      <FundamentalsCard code={code} />

      <FinancialHistoryTable code={code} />

      <Card
        size="small"
        style={{ marginTop: 16, marginBottom: 16 }}
        styles={{ body: { padding: isMobile ? 8 : 12 } }}
      >
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as AnalysisTabKey)}
          size={isMobile ? 'small' : 'middle'}
          items={[
            {
              key: 'signal',
              label: (
                <Space size={6}>
                  <ThunderboltOutlined />
                  <span>信号分析</span>
                </Space>
              ),
              children: signals.length > 0 ? (
                <SignalConfluence
                  signals={signals}
                  showMA={showMA}
                  showMACD={showMACD}
                  showKDJ={showKDJ}
                  showRSI={showRSI}
                  onSignalClick={handleSignalClick}
                />
              ) : (
                <Empty
                  description="暂无信号数据"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  style={{ padding: '12px 0' }}
                />
              ),
            },
            {
              key: 'ai',
              label: (
                <Space size={6}>
                  <ExperimentOutlined />
                  <span>AI 分析</span>
                </Space>
              ),
              children: (
                <TradingAgentsPanel code={code} stockName={stockName} />
              ),
            },
          ]}
        />
      </Card>

      <div ref={chartRef} style={{ scrollMarginTop: isMobile ? 132 : 0 }}>
      <Card
        size="small"
        title="K线图"
        styles={{ body: { padding: isMobile ? 8 : 12 } }}
        style={{ marginBottom: isMobile ? 8 : 0 }}
      >
        <div style={{ marginBottom: 8, display: 'flex', flexWrap: 'wrap', gap: isMobile ? '4px 12px' : '0 12px' }}>
          <Checkbox checked={showMA} onChange={(e) => setShowMA(e.target.checked)}>MA</Checkbox>
          <Checkbox checked={showMACD} onChange={(e) => setShowMACD(e.target.checked)}>MACD</Checkbox>
          <Checkbox checked={showKDJ} onChange={(e) => setShowKDJ(e.target.checked)}>KDJ</Checkbox>
          <Checkbox checked={showRSI} onChange={(e) => setShowRSI(e.target.checked)}>RSI</Checkbox>
          <Checkbox checked={showSignals} onChange={(e) => setShowSignals(e.target.checked)}>信号标注</Checkbox>
        </div>
        <Spin spinning={loading}>
          <KlineChart
            klineData={klineData}
            height={chartHeight}
            showMA={showMA}
            showMACD={showMACD}
            showKDJ={showKDJ}
            showRSI={showRSI}
            signals={signals}
            showSignals={showSignals}
            highlightPosition={highlightPosition}
          />
        </Spin>
      </Card>
      </div>

      {/* Desktop: signal panel below chart */}
      {!isMobile && (
        <Card size="small" title="信号列表" style={{ marginTop: 16 }}>
          <div style={{ maxHeight: 520, overflowY: 'auto' }}>
            <SignalPanel
              signals={signals}
              onSignalClick={handleSignalClick}
              showMA={showMA}
              showMACD={showMACD}
              showKDJ={showKDJ}
              showRSI={showRSI}
            />
          </div>
        </Card>
      )}

      {/* Mobile: floating action button + bottom drawer for signal panel */}
      {isMobile && (
        <>
          <FloatButton
            icon={<UnorderedListOutlined />}
            description="信号"
            shape="square"
            type="primary"
            onClick={() => setSignalDrawerOpen(true)}
            style={{ right: 16, bottom: 72 }}
            aria-label="打开信号列表"
            badge={signals.length > 0 ? { count: signals.length, overflowCount: 99 } : undefined}
          />
          <Drawer
            title="信号列表"
            placement="bottom"
            height="80vh"
            open={signalDrawerOpen}
            onClose={() => setSignalDrawerOpen(false)}
            styles={{ body: { padding: 12 } }}
          >
            <SignalPanel
              signals={signals}
              onSignalClick={(pos) => {
                setSignalDrawerOpen(false);
                handleSignalClick(pos);
              }}
              showMA={showMA}
              showMACD={showMACD}
              showKDJ={showKDJ}
              showRSI={showRSI}
            />
          </Drawer>
        </>
      )}
    </div>
  );
}
