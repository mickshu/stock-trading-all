import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Collapse, InputNumber, Modal, Space, Spin, Table, Tag, Typography, message,
} from 'antd';
import KlineChart from './KlineChart';
import { fetchLivermore, type LivermoreQuery } from '../api/analysis';
import { setStockHolding } from '../api/stocks';
import type { LivermoreResponse, StockInfo } from '../types';

const DEFAULT_QUERY: LivermoreQuery = {
  high_n: 60,
  box_n: 20,
  stop_pct: 5,
  first_pct: 30,
  add_step_pct: 3,
  add_pct: 20,
  levels: 3,
};

const STATE_COLORS: Record<LivermoreResponse['state'], string> = {
  confirmed: 'red',
  intraday: 'orange',
  approaching: 'gold',
  watching: 'default',
};

const PARAM_FIELDS: { key: keyof LivermoreQuery; label: string; min: number; max: number }[] = [
  { key: 'high_n', label: '关键点回看(日)', min: 20, max: 250 },
  { key: 'box_n', label: '箱体(日)', min: 5, max: 120 },
  { key: 'stop_pct', label: '止损(%)', min: 1, max: 20 },
  { key: 'first_pct', label: '首仓(%)', min: 5, max: 100 },
  { key: 'add_step_pct', label: '加仓级差(%)', min: 0.5, max: 20 },
  { key: 'add_pct', label: '每级加仓(%)', min: 5, max: 50 },
  { key: 'levels', label: '加仓级数', min: 1, max: 5 },
];

function extractError(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || '请求失败，请稍后重试';
}

function PriceCard({ label, value, tone }: { label: string; value: number | null; tone?: 'danger' }) {
  return (
    <div
      style={{
        flex: 1, minWidth: 110, background: '#fafafa', borderRadius: 8,
        padding: '8px 12px', textAlign: 'center',
      }}
    >
      <div style={{ fontSize: 12, color: '#999' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: tone === 'danger' ? '#cf1322' : undefined }}>
        {value != null ? value.toFixed(2) : '—'}
      </div>
    </div>
  );
}

export default function LivermoreModal({
  stock,
  open,
  onClose,
}: {
  stock: StockInfo | null;
  open: boolean;
  onClose: () => void;
}) {
  const [data, setData] = useState<LivermoreResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useState<LivermoreQuery>(DEFAULT_QUERY);
  const [holdingDraft, setHoldingDraft] = useState<{
    cost: number | null;
    shares: number | null;
    planned_capital: number | null;
  }>({ cost: null, shares: null, planned_capital: null });
  const [savingHolding, setSavingHolding] = useState(false);

  const load = useCallback(
    async (query: LivermoreQuery) => {
      if (!stock) return;
      setLoading(true);
      setError(null);
      try {
        setData(await fetchLivermore(stock.code, query));
      } catch (e) {
        setError(extractError(e));
      } finally {
        setLoading(false);
      }
    },
    [stock],
  );

  useEffect(() => {
    if (!open || !stock) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 弹层打开/切换股票时重置草稿，prop 同步的合法场景
    setHoldingDraft({
      cost: stock.cost ?? null,
      shares: stock.shares ?? null,
      planned_capital: stock.planned_capital ?? null,
    });
    setParams(DEFAULT_QUERY);
    void load(DEFAULT_QUERY);
  }, [open, stock, load]);

  const handleSaveHolding = async () => {
    if (stock?.id == null) return;
    setSavingHolding(true);
    try {
      await setStockHolding(stock.id, holdingDraft);
      message.success('持仓信息已保存');
      await load(params);
    } catch {
      message.error('保存失败，请重试');
    } finally {
      setSavingHolding(false);
    }
  };

  const markLines = useMemo(
    () =>
      data
        ? [
            { price: data.pivot, name: '关键点', color: '#cf1322' },
            { price: data.stop_loss, name: '止损', color: '#3f8600' },
          ]
        : [],
    [data],
  );

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnClose
      title={`利弗莫尔买入法 · ${stock?.name ?? ''} ${stock?.code ?? ''}`}
    >
      <Spin spinning={loading}>
        {error ? (
          <Alert
            type="error"
            message="计算失败"
            description={error}
            action={<Button size="small" onClick={() => void load(params)}>重试</Button>}
          />
        ) : data ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div
              style={{
                background: '#fafafa', borderRadius: 8, padding: '10px 12px',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                flexWrap: 'wrap', gap: 8,
              }}
            >
              <Space size={6}>
                <Typography.Text type="secondary">现价</Typography.Text>
                <Typography.Text strong style={{ fontSize: 18 }}>
                  {data.current_price != null ? data.current_price.toFixed(2) : '—'}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {data.last_date}
                </Typography.Text>
              </Space>
              <Space size={6}>
                <Tag color={STATE_COLORS[data.state]}>{data.state_label}</Tag>
                {data.distance_pct != null && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    距关键点 {data.distance_pct > 0 ? '+' : ''}
                    {data.distance_pct.toFixed(2)}%
                  </Typography.Text>
                )}
              </Space>
            </div>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <PriceCard label="主关键点" value={data.pivot} />
              <PriceCard label="平台位" value={data.box_top} />
              <PriceCard label="止损位" value={data.stop_loss} tone="danger" />
            </div>

            <Alert
              type={data.stop_breached ? 'error' : data.state === 'confirmed' ? 'success' : 'info'}
              message={data.advice}
              showIcon
            />

            <Typography.Text strong>金字塔加仓</Typography.Text>
            <Table
              size="small"
              pagination={false}
              rowKey="level"
              dataSource={data.ladder}
              columns={[
                { title: '档位', dataIndex: 'label' },
                { title: '累计仓位', dataIndex: 'cum_pct', align: 'right', render: (v: number) => `${v}%` },
                { title: '加仓价格', dataIndex: 'price', align: 'right', render: (v: number | null) => (v != null ? v.toFixed(2) : '—') },
                { title: '建议金额', dataIndex: 'amount', align: 'right', render: (v: number | null) => (v != null ? `¥${v.toLocaleString()}` : '—') },
              ]}
            />

            <div style={{ background: '#fafafa', borderRadius: 8, padding: '10px 12px' }}>
              <Space wrap>
                <Typography.Text strong>持仓</Typography.Text>
                <InputNumber
                  size="small" placeholder="成本" precision={3} min={0} controls={false}
                  style={{ width: 100 }} value={holdingDraft.cost}
                  onChange={(v) => setHoldingDraft((d) => ({ ...d, cost: v == null ? null : Number(v) }))}
                />
                <InputNumber
                  size="small" placeholder="股数" precision={0} min={0} controls={false}
                  style={{ width: 100 }} value={holdingDraft.shares}
                  onChange={(v) => setHoldingDraft((d) => ({ ...d, shares: v == null ? null : Number(v) }))}
                />
                <InputNumber
                  size="small" placeholder="计划资金" precision={2} min={0} controls={false}
                  style={{ width: 120 }} value={holdingDraft.planned_capital}
                  onChange={(v) => setHoldingDraft((d) => ({ ...d, planned_capital: v == null ? null : Number(v) }))}
                />
                <Button size="small" type="primary" loading={savingHolding} disabled={stock?.id == null} onClick={handleSaveHolding}>
                  保存
                </Button>
              </Space>
              {data.holding.position_pct != null && (
                <div style={{ marginTop: 6 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    当前仓位 {data.holding.position_pct.toFixed(1)}%
                    （已投入 ¥{(data.holding.invested ?? 0).toLocaleString()}）
                  </Typography.Text>
                </div>
              )}
            </div>

            <Collapse
              ghost
              size="small"
              items={[
                {
                  key: 'params',
                  label: '参数设置',
                  children: (
                    <Space wrap>
                      {PARAM_FIELDS.map((f) => (
                        <Space key={f.key} size={4}>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{f.label}</Typography.Text>
                          <InputNumber
                            size="small" min={f.min} max={f.max}
                            value={params[f.key] as number}
                            onChange={(v) => v != null && setParams((p) => ({ ...p, [f.key]: Number(v) }))}
                            style={{ width: 80 }}
                          />
                        </Space>
                      ))}
                      <Button size="small" type="primary" onClick={() => void load(params)}>
                        重新计算
                      </Button>
                    </Space>
                  ),
                },
              ]}
            />

            {data.kline.length > 0 && (
              <KlineChart
                klineData={data.kline}
                height={220}
                showMA={false}
                showSignals={false}
                markLines={markLines}
              />
            )}

            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              风险提示：突破关键点买入、跌破止损位离场、让利润奔跑。计算结果仅供策略参考，不构成投资建议。
            </Typography.Text>
          </div>
        ) : null}
      </Spin>
    </Modal>
  );
}
