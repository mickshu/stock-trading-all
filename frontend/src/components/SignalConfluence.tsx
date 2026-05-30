import { useMemo } from 'react';
import { Card, Space, Tag, Tooltip, Typography, Grid } from 'antd';
import { InfoCircleOutlined, ThunderboltFilled } from '@ant-design/icons';
import type { Signal, SignalLevel } from '../types';

const { useBreakpoint } = Grid;

interface Props {
  signals: Signal[];
  showMA?: boolean;
  showMACD?: boolean;
  showKDJ?: boolean;
  showRSI?: boolean;
  onSignalClick?: (position: number) => void;
  minCount?: number;
  topN?: number;
}

interface ConfluenceEvent {
  date: string;
  position: number;
  level: Exclude<SignalLevel, 'neutral'>;
  signals: Signal[];
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

export default function SignalConfluence({
  signals,
  showMA = true,
  showMACD = true,
  showKDJ = true,
  showRSI = true,
  onSignalClick,
  minCount = 2,
  topN = 6,
}: Props) {
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const events = useMemo<ConfluenceEvent[]>(() => {
    const groups = new Map<string, ConfluenceEvent>();
    for (const s of signals) {
      if (s.position == null) continue;
      if (!indicatorEnabled(s, showMA, showMACD, showKDJ, showRSI)) continue;
      const lvl = inferLevel(s);
      if (lvl === 'neutral') continue;
      const key = `${s.position}-${lvl}`;
      const existing = groups.get(key);
      if (existing) {
        existing.signals.push(s);
      } else {
        groups.set(key, { date: s.date, position: s.position, level: lvl, signals: [s] });
      }
    }
    return Array.from(groups.values())
      .filter((e) => e.signals.length >= minCount)
      .sort((a, b) => b.position - a.position)
      .slice(0, topN);
  }, [signals, showMA, showMACD, showKDJ, showRSI, minCount, topN]);

  if (events.length === 0) return null;

  const titleNode = (
    <Space size={6}>
      <ThunderboltFilled style={{ color: '#fa8c16' }} />
      <Typography.Text strong>信号共振</Typography.Text>
      {!isMobile && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          同日多个同向信号
        </Typography.Text>
      )}
      <Tooltip title="同一交易日出现多个独立指标方向一致的信号，可信度通常更高；但仍需结合趋势位置与量能确认，不构成投资建议。">
        <InfoCircleOutlined style={{ color: '#999' }} />
      </Tooltip>
      <Tag color="default" style={{ marginLeft: 4 }}>{events.length}</Tag>
    </Space>
  );

  return (
    <Card size="small" title={titleNode} styles={{ body: { padding: isMobile ? 8 : 12 } }} style={{ marginBottom: isMobile ? 8 : 16 }}>
      <div style={{ display: 'flex', gap: isMobile ? 8 : 12, flexWrap: 'wrap' }}>
        {events.map((e) => {
          const bull = e.level === 'bullish';
          const color = bull ? '#ef5350' : '#26a69a';
          const bg = bull ? 'rgba(239,83,80,0.08)' : 'rgba(38,166,154,0.08)';
          const label = bull ? '看多共振' : '看空共振';
          return (
            <div
              key={`${e.position}-${e.level}`}
              onClick={() => onSignalClick?.(e.position)}
              style={{
                flex: isMobile ? '1 1 100%' : '1 1 220px',
                minWidth: isMobile ? undefined : 220,
                maxWidth: isMobile ? undefined : 340,
                padding: isMobile ? '8px 10px' : '10px 12px',
                border: `1px solid ${color}`,
                borderLeftWidth: 4,
                borderRadius: 6,
                background: bg,
                cursor: onSignalClick ? 'pointer' : 'default',
                transition: 'transform 0.15s',
              }}
              onMouseEnter={(ev) => {
                (ev.currentTarget as HTMLDivElement).style.transform = 'translateY(-1px)';
              }}
              onMouseLeave={(ev) => {
                (ev.currentTarget as HTMLDivElement).style.transform = 'translateY(0)';
              }}
            >
              <Space size={6} style={{ marginBottom: 4 }} wrap>
                <Typography.Text strong style={{ color, fontSize: 13 }}>
                  {label}
                </Typography.Text>
                <Tag color={bull ? 'red' : 'green'} style={{ marginRight: 0, fontWeight: 600 }}>
                  ×{e.signals.length}
                </Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {e.date}
                </Typography.Text>
              </Space>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {e.signals.map((s) => s.name || s.type).join(' · ')}
                </Typography.Text>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
