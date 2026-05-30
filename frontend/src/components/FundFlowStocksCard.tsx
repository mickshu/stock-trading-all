import { useEffect, useState } from 'react';
import { Card, Col, Row, Table, Typography, Tag, Empty, Grid } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { fetchFundFlowStocks, type FundFlowStockItem, type FundFlowStocks } from '../api/summary';

const { useBreakpoint } = Grid;

function fmtYi(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${(v / 1e8).toFixed(2)} 亿`;
}

function fmtPct(v: number | null | undefined): { text: string; color?: string } {
  if (v == null) return { text: '—' };
  const color = v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : undefined;
  const sign = v > 0 ? '+' : '';
  return { text: `${sign}${v.toFixed(2)}%`, color };
}

function makeColumns(isMobile: boolean): ColumnsType<FundFlowStockItem> {
  return [
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: isMobile ? 68 : 80,
      onCell: () => ({ style: { whiteSpace: 'nowrap', padding: isMobile ? '6px 4px 6px 8px' : undefined } }),
      onHeaderCell: () => ({ style: { padding: isMobile ? '6px 4px 6px 8px' : undefined } }),
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      ellipsis: !isMobile,
      onCell: () => ({ style: { padding: isMobile ? '6px 4px' : undefined } }),
      onHeaderCell: () => ({ style: { padding: isMobile ? '6px 4px' : undefined } }),
      render: (name: string, record: FundFlowStockItem) => {
        if (!isMobile) return name;
        const { text, color } = fmtPct(record.change_pct);
        return (
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, minWidth: 0 }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: '1 1 auto', minWidth: 0 }}>{name}</span>
            <span style={{ color, fontSize: 11, flexShrink: 0 }}>{text}</span>
          </div>
        );
      },
    },
    {
      title: '主力净额',
      dataIndex: 'main_net',
      key: 'main_net',
      align: 'right',
      width: isMobile ? 92 : undefined,
      onCell: () => ({ style: { whiteSpace: 'nowrap', padding: isMobile ? '6px 8px 6px 4px' : undefined } }),
      onHeaderCell: () => ({ style: { padding: isMobile ? '6px 8px 6px 4px' : undefined } }),
      render: (v: number) => {
        const c = v >= 0 ? '#cf1322' : '#3f8600';
        return <Typography.Text style={{ color: c, fontSize: isMobile ? 13 : undefined }} strong>{fmtYi(v)}</Typography.Text>;
      },
    },
    ...(!isMobile ? [{
      title: '涨跌幅',
      dataIndex: 'change_pct',
      key: 'change_pct',
      width: 90,
      align: 'right' as const,
      render: (v: number) => {
        const { text, color } = fmtPct(v);
        return <Typography.Text style={{ color }}>{text}</Typography.Text>;
      },
    }] : []),
  ];
}

export default function FundFlowStocksCard() {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [data, setData] = useState<FundFlowStocks | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchFundFlowStocks(10)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const cols = makeColumns(isMobile);
  const dateTag = data?.date ? <Tag color="blue">{data.date}</Tag> : null;

  return (
    <Card
      size="small"
      title={
        <>
          <span>主力资金 TOP10</span>
          {dateTag && <span style={{ marginLeft: 8 }}>{dateTag}</span>}
        </>
      }
      loading={loading && !data}
      style={{ marginTop: isMobile ? 12 : 16 }}
      styles={{ body: { padding: isMobile ? '8px 0' : undefined } }}
    >
      {!data ? (
        <Empty description="数据源不可用" />
      ) : (
        <Row gutter={[isMobile ? 0 : 16, isMobile ? 0 : 16]}>
          <Col xs={24} md={12}>
            <Typography.Text type="secondary" style={{ fontSize: 12, padding: isMobile ? '0 12px' : 0 }}>
              资金净流入 TOP
            </Typography.Text>
            <Table<FundFlowStockItem>
              rowKey="code"
              size="small"
              columns={cols}
              dataSource={data.inflow}
              pagination={false}
              style={{ marginTop: 4 }}
            />
          </Col>
          <Col xs={24} md={12}>
            <Typography.Text type="secondary" style={{ fontSize: 12, padding: isMobile ? '0 12px' : 0 }}>
              资金净流出 TOP
            </Typography.Text>
            <Table<FundFlowStockItem>
              rowKey="code"
              size="small"
              columns={cols}
              dataSource={data.outflow}
              pagination={false}
              style={{ marginTop: 4 }}
            />
          </Col>
        </Row>
      )}
    </Card>
  );
}
