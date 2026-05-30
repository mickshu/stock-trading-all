import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
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
} from 'antd';
import { ReloadOutlined, ThunderboltOutlined, ExperimentOutlined } from '@ant-design/icons';
import KlineChart from '../components/KlineChart';
import SignalPanel from '../components/SignalPanel';
import SignalConfluence from '../components/SignalConfluence';
import FundamentalsCard from '../components/FundamentalsCard';
import AIAgentCard from '../components/AIAgentCard';
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
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [stockName, setStockName] = useState('');
  const [activeTab, setActiveTab] = useState<AnalysisTabKey>('signal');
  const [signalDrawerOpen, setSignalDrawerOpen] = useState(false);
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
    if (code) {
      fetchQuote(code).then((q) => setStockName(q.name || '')).catch(() => setStockName(''));
    }
  }, [code]);

  if (!code) return <Alert type="error" title="未提供股票代码" />;

  const chartHeight = isMobile
    ? 350 + ([showMACD, showKDJ, showRSI].filter(Boolean).length * 80)
    : 450 + ([showMACD, showKDJ, showRSI].filter(Boolean).length * 110);

  const title = stockName ? `${code} ${stockName}` : code;

  return (
    <div>
      <Space style={{ marginBottom: isMobile ? 12 : 16 }} wrap orientation={isMobile ? 'vertical' : 'horizontal'} size={8}>
        <Space wrap size={8}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
          <Segmented
            options={periodOptions}
            value={period}
            onChange={(val) => setPeriod(val as Period)}
            size={isMobile ? 'small' : 'middle'}
          />
        </Space>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => loadAnalysis(code, true)}
          disabled={loading}
          size={isMobile ? 'small' : 'middle'}
        >
          刷新
        </Button>
      </Space>

      {error && <Alert type="error" title={error} style={{ marginBottom: 12 }} />}

      <FundamentalsCard code={code} />

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
                  onSignalClick={(pos) => setHighlightPosition(pos)}
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
              children: <AIAgentCard code={code} stockName={stockName} />,
            },
          ]}
        />
      </Card>

      <Card
        size="small"
        title="K线图"
        extra={
          isMobile ? (
            <Button size="small" type="link" onClick={() => setSignalDrawerOpen(true)}>
              信号面板
            </Button>
          ) : null
        }
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

      {/* Desktop: signal panel below chart */}
      {!isMobile && (
        <Card size="small" title="信号列表" style={{ marginTop: 16 }}>
          <div style={{ maxHeight: 520, overflowY: 'auto' }}>
            <SignalPanel
              signals={signals}
              onSignalClick={(pos) => setHighlightPosition(pos)}
              showMA={showMA}
              showMACD={showMACD}
              showKDJ={showKDJ}
              showRSI={showRSI}
            />
          </div>
        </Card>
      )}

      {/* Mobile: signal panel as bottom drawer */}
      {isMobile && (
        <Drawer
          title="信号列表"
          placement="bottom"
          size="large"
          open={signalDrawerOpen}
          onClose={() => setSignalDrawerOpen(false)}
        >
          <SignalPanel
            signals={signals}
            onSignalClick={(pos) => {
              setHighlightPosition(pos);
              setSignalDrawerOpen(false);
            }}
            showMA={showMA}
            showMACD={showMACD}
            showKDJ={showKDJ}
            showRSI={showRSI}
          />
        </Drawer>
      )}
    </div>
  );
}
