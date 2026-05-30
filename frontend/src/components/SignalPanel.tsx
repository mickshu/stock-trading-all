import { useMemo } from 'react';
import { Collapse, Empty, List, Popover, Space, Tag, Typography, Grid } from 'antd';
import { InfoCircleOutlined, WarningOutlined } from '@ant-design/icons';
import type { Signal, SignalCategory, SignalLevel } from '../types';

const { useBreakpoint } = Grid;

interface Props {
  signals: Signal[];
  onSignalClick?: (position: number) => void;
  showMA?: boolean;
  showMACD?: boolean;
  showKDJ?: boolean;
  showRSI?: boolean;
}

const CATEGORY_META: Record<SignalCategory, { label: string; color: string; desc: string }> = {
  trend: { label: '趋势', color: 'geekblue', desc: '反映中长期方向（MACD/MA 金叉死叉、价格突破均线等）' },
  momentum: { label: '动量', color: 'purple', desc: '反映短期动能强弱（KDJ 金叉死叉等）' },
  reversal: { label: '反转', color: 'magenta', desc: '反映超买超卖与潜在反转（RSI/KDJ 超买超卖）' },
  volume: { label: '量能', color: 'gold', desc: '成交量异常（放量、缩量）' },
};

const LEVEL_COLOR: Record<SignalLevel, string> = {
  bullish: '#ef5350',
  bearish: '#26a69a',
  neutral: '#faad14',
};

const CATEGORY_ORDER: SignalCategory[] = ['trend', 'momentum', 'reversal', 'volume'];

function inferCategory(s: Signal): SignalCategory {
  if (s.category) return s.category;
  if (s.type === 'golden_cross' || s.type === 'death_cross') return 'trend';
  if (s.type === 'overbought' || s.type === 'oversold') return 'reversal';
  return 'trend';
}

function inferLevel(s: Signal): SignalLevel {
  if (s.level) return s.level;
  if (
    s.type.includes('golden') ||
    s.type.includes('oversold') ||
    s.type.includes('breakout') ||
    s.type.includes('bull')
  ) {
    return 'bullish';
  }
  if (
    s.type.includes('death') ||
    s.type.includes('overbought') ||
    s.type.includes('breakdown') ||
    s.type.includes('bear')
  ) {
    return 'bearish';
  }
  return 'neutral';
}

function indicatorEnabled(
  s: Signal,
  showMA: boolean,
  showMACD: boolean,
  showKDJ: boolean,
  showRSI: boolean,
): boolean {
  const ind = s.indicator;
  if (ind === 'MA' || ind === 'PRICE') return showMA;
  if (ind === 'MACD') return showMACD;
  if (ind === 'KDJ') return showKDJ;
  if (ind === 'RSI') return showRSI;
  if (ind === 'VOL') return true;
  return true;
}

function SignalDetail({ signal }: { signal: Signal }) {
  return (
    <div style={{ maxWidth: 280 }}>
      <Typography.Paragraph style={{ marginBottom: 8, fontSize: 12 }}>
        <InfoCircleOutlined style={{ color: '#1677ff', marginRight: 6 }} />
        <Typography.Text strong>解释：</Typography.Text>
        {signal.explanation || '—'}
      </Typography.Paragraph>
      <Typography.Paragraph style={{ marginBottom: 0, fontSize: 12 }}>
        <WarningOutlined style={{ color: '#faad14', marginRight: 6 }} />
        <Typography.Text strong>误导：</Typography.Text>
        {signal.caveat || '—'}
      </Typography.Paragraph>
    </div>
  );
}

export default function SignalPanel({
  signals,
  onSignalClick,
  showMA = true,
  showMACD = true,
  showKDJ = true,
  showRSI = true,
}: Props) {
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const grouped = useMemo(() => {
    const map = new Map<SignalCategory, Signal[]>();
    const filtered = signals.filter((s) => indicatorEnabled(s, showMA, showMACD, showKDJ, showRSI));
    const sorted = [...filtered].sort((a, b) => (b.position ?? 0) - (a.position ?? 0));
    for (const s of sorted) {
      const cat = inferCategory(s);
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(s);
    }
    return map;
  }, [signals, showMA, showMACD, showKDJ, showRSI]);

  const totalShown = Array.from(grouped.values()).reduce((sum, list) => sum + list.length, 0);

  if (signals.length === 0) {
    return <Empty description="暂无信号" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }
  if (totalShown === 0) {
    return (
      <Empty
        description="勾选指标后显示对应信号"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }

  const items = CATEGORY_ORDER.filter((c) => grouped.has(c)).map((cat) => {
    const list = grouped.get(cat)!;
    const meta = CATEGORY_META[cat];
    const bull = list.filter((s) => inferLevel(s) === 'bullish').length;
    const bear = list.filter((s) => inferLevel(s) === 'bearish').length;
    return {
      key: cat,
      label: (
        <Space size={6} wrap>
          <Tag color={meta.color} style={{ marginRight: 0 }}>{meta.label}</Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {list.length}
          </Typography.Text>
          {bull > 0 && <Typography.Text style={{ fontSize: 12, color: LEVEL_COLOR.bullish }}>↑{bull}</Typography.Text>}
          {bear > 0 && <Typography.Text style={{ fontSize: 12, color: LEVEL_COLOR.bearish }}>↓{bear}</Typography.Text>}
        </Space>
      ),
      children: (
        <List
          size="small"
          dataSource={list}
          renderItem={(s) => {
            const lvl = inferLevel(s);
            const color = LEVEL_COLOR[lvl];
            return (
              <List.Item
                style={{ cursor: onSignalClick ? 'pointer' : 'default', padding: isMobile ? '4px 0' : '6px 0' }}
                onClick={() => onSignalClick?.(s.position ?? 0)}
              >
                <div style={{ width: '100%' }}>
                  <Space size={4} align="center" wrap>
                    <span
                      style={{
                        display: 'inline-block',
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        backgroundColor: color,
                      }}
                    />
                    <Typography.Text style={{ fontSize: 11, color: '#888' }}>
                      {s.date}
                    </Typography.Text>
                    <Typography.Text strong style={{ color, fontSize: 13 }}>
                      {s.name || s.type}
                    </Typography.Text>
                    <Popover
                      content={<SignalDetail signal={s} />}
                      title={s.name || s.type}
                      trigger="click"
                    >
                      <InfoCircleOutlined
                        style={{ color: '#1677ff', cursor: 'pointer', fontSize: 12 }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popover>
                  </Space>
                </div>
              </List.Item>
            );
          }}
        />
      ),
    };
  });

  return (
    <Collapse
      size="small"
      ghost
      defaultActiveKey={CATEGORY_ORDER.filter((c) => grouped.has(c))}
      items={items}
    />
  );
}
