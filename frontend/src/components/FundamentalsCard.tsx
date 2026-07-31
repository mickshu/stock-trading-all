import { useEffect, useState } from 'react';
import { Card, Descriptions, Spin, Typography, Tag, Tooltip, Space, Grid } from 'antd';
import { fetchFundamentals, type Fundamentals } from '../api/market';

const { useBreakpoint } = Grid;

interface Props {
  code: string;
  isEtf?: boolean;
}

function formatBigYuan(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—';
  const yi = 1e8;
  const wan = 1e4;
  if (Math.abs(v) >= yi) return `${(v / yi).toFixed(2)} 亿`;
  if (Math.abs(v) >= wan) return `${(v / wan).toFixed(2)} 万`;
  return v.toFixed(2);
}

function formatBigShares(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—';
  const yi = 1e8;
  const wan = 1e4;
  if (Math.abs(v) >= yi) return `${(v / yi).toFixed(2)} 亿股`;
  if (Math.abs(v) >= wan) return `${(v / wan).toFixed(2)} 万股`;
  return `${v.toFixed(0)} 股`;
}

function formatRatio(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—';
  return v.toFixed(2);
}

function formatPct(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—';
  return `${v.toFixed(2)}%`;
}

export default function FundamentalsCard({ code, isEtf }: Props) {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [data, setData] = useState<Fundamentals | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFundamentals(code)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) {
          const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          setError(detail || '加载财务指标失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  const titleNode = (
    <Space size={8}>
      <span>{isEtf ? 'ETF 指标' : '关键指标'}</span>
      {!isEtf && data?.industry ? <Tag color="blue">{data.industry}</Tag> : null}
      {isEtf && <Tag color="orange">ETF</Tag>}
      {!isMobile && data?.as_of && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          数据日期 {data.as_of}
        </Typography.Text>
      )}
    </Space>
  );

  const change = data?.change_pct;
  const changeColor = change == null ? undefined : change > 0 ? '#cf1322' : change < 0 ? '#3f8600' : undefined;

  return (
    <Card size="small" title={titleNode} style={{ marginBottom: isMobile ? 8 : 12 }}>
      <Spin spinning={loading}>
        {error ? (
          <Typography.Text type="danger">{error}</Typography.Text>
        ) : (
          isEtf ? (
            <Descriptions column={{ xs: 2, sm: 3, md: 4, lg: 6 }} size="small" colon={false}>
              <Descriptions.Item label="最新价">
                <Typography.Text strong>
                  {data?.price != null ? data.price.toFixed(3) : '—'}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="涨跌幅">
                <Typography.Text strong style={{ color: changeColor }}>
                  {formatPct(change)}
                </Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="IOPV">
                {(data as any)?.iopv != null ? (data as any).iopv.toFixed(3) : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="折溢价率">
                {formatPct((data as any)?.discount_rate)}
              </Descriptions.Item>
              {!isMobile && <Descriptions.Item label="最新份额">{formatBigYuan((data as any)?.total_size)}</Descriptions.Item>}
              {!isMobile && <Descriptions.Item label="总规模">{formatBigYuan(data?.total_market_cap)}</Descriptions.Item>}
              {!isMobile && <Descriptions.Item label="跟踪指数">{(data as any)?.tracking_index || '—'}</Descriptions.Item>}
              {!isMobile && <Descriptions.Item label="上市日期">{data?.listing_date || '—'}</Descriptions.Item>}
            </Descriptions>
          ) : (
            <Descriptions column={{ xs: 2, sm: 3, md: 4, lg: 6 }} size="small" colon={false}>
            <Descriptions.Item label="最新价">
              <Typography.Text strong>
                {data?.price != null ? data.price.toFixed(2) : '—'}
              </Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="涨跌幅">
              <Typography.Text strong style={{ color: changeColor }}>
                {formatPct(change)}
              </Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label={<Tooltip title="市盈率（静态）">PE</Tooltip>}>
              {formatRatio(data?.pe)}
            </Descriptions.Item>
            <Descriptions.Item label={<Tooltip title="市盈率（滚动 TTM）">PE(TTM)</Tooltip>}>
              {formatRatio(data?.pe_ttm)}
            </Descriptions.Item>
            <Descriptions.Item label={<Tooltip title="市净率">PB</Tooltip>}>
              {formatRatio(data?.pb)}
            </Descriptions.Item>
            <Descriptions.Item label={<Tooltip title="市销率 TTM">PS(TTM)</Tooltip>}>
              {formatRatio(data?.ps_ttm)}
            </Descriptions.Item>
            <Descriptions.Item label={<Tooltip title="股息率 TTM">股息率</Tooltip>}>
              {formatPct(data?.dv_ttm)}
            </Descriptions.Item>
            {!isMobile && <Descriptions.Item label="总市值">{formatBigYuan(data?.total_market_cap)}</Descriptions.Item>}
            {!isMobile && <Descriptions.Item label="流通市值">{formatBigYuan(data?.float_market_cap)}</Descriptions.Item>}
            {!isMobile && <Descriptions.Item label="总股本">{formatBigShares(data?.total_shares)}</Descriptions.Item>}
            {!isMobile && <Descriptions.Item label="流通股">{formatBigShares(data?.float_shares)}</Descriptions.Item>}
            {!isMobile && <Descriptions.Item label="上市日期">{data?.listing_date || '—'}</Descriptions.Item>}
          </Descriptions>
          )
        )}
      </Spin>
    </Card>
  );
}
