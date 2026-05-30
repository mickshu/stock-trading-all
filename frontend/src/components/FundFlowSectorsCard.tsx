import { useEffect, useState } from 'react';
import { Card, Col, Row, Table, Typography, Tag, Empty, Grid } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { fetchFundFlowSectors, type FundFlowSectorItem, type FundFlowSectors } from '../api/summary';

const { useBreakpoint } = Grid;

function fmtYi(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${(v / 1e8).toFixed(2)} 亿`;
}

function makeColumns(isMobile: boolean): ColumnsType<FundFlowSectorItem> {
  return [
    { title: '板块', dataIndex: 'name', key: 'name', ellipsis: true },
    ...(!isMobile ? [{
      title: '板块涨跌',
      dataIndex: 'change_pct',
      key: 'change_pct',
      width: 90,
      align: 'right' as const,
      render: (v: number | null) => {
        if (v == null) return '—';
        const color = v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : undefined;
        const sign = v > 0 ? '+' : '';
        return <Typography.Text style={{ color }}>{`${sign}${v.toFixed(2)}%`}</Typography.Text>;
      },
    }] : []),
    {
      title: '主力净额',
      dataIndex: 'main_net',
      key: 'main_net',
      align: 'right',
      render: (v: number | null) => {
        if (v == null) return '—';
        const c = v >= 0 ? '#cf1322' : '#3f8600';
        return <Typography.Text style={{ color: c }} strong>{fmtYi(v)}</Typography.Text>;
      },
    },
  ];
}

export default function FundFlowSectorsCard() {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [data, setData] = useState<FundFlowSectors | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchFundFlowSectors(5)
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
          <span>行业板块 TOP5</span>
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
              资金净流入板块
            </Typography.Text>
            <Table<FundFlowSectorItem>
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
              资金净流出板块
            </Typography.Text>
            <Table<FundFlowSectorItem>
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
