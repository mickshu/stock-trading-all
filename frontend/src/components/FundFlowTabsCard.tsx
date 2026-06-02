import { useEffect, useMemo, useState } from 'react';
import { Card, Empty, Grid, Table, Tabs, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  fetchFundFlowSectors,
  fetchFundFlowStocks,
  type FundFlowSectorItem,
  type FundFlowSectors,
  type FundFlowStockItem,
  type FundFlowStocks,
} from '../api/summary';

const { useBreakpoint } = Grid;

type TabKey = 'stocks_in' | 'stocks_out' | 'sectors_in' | 'sectors_out';

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

function makeStockColumns(isMobile: boolean): ColumnsType<FundFlowStockItem> {
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
    ...(!isMobile
      ? [{
          title: '涨跌幅',
          dataIndex: 'change_pct',
          key: 'change_pct',
          width: 90,
          align: 'right' as const,
          render: (v: number) => {
            const { text, color } = fmtPct(v);
            return <Typography.Text style={{ color }}>{text}</Typography.Text>;
          },
        }]
      : []),
  ];
}

function makeSectorColumns(isMobile: boolean): ColumnsType<FundFlowSectorItem> {
  return [
    { title: '板块', dataIndex: 'name', key: 'name', ellipsis: true },
    ...(!isMobile
      ? [{
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
        }]
      : []),
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

export default function FundFlowTabsCard() {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [activeKey, setActiveKey] = useState<TabKey>('stocks_in');
  const [stocks, setStocks] = useState<FundFlowStocks | null>(null);
  const [sectors, setSectors] = useState<FundFlowSectors | null>(null);
  const [loadingStocks, setLoadingStocks] = useState(false);
  const [loadingSectors, setLoadingSectors] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoadingStocks(true);
    setLoadingSectors(true);
    fetchFundFlowStocks(10)
      .then((d) => { if (!cancelled) setStocks(d); })
      .catch(() => { if (!cancelled) setStocks(null); })
      .finally(() => { if (!cancelled) setLoadingStocks(false); });
    fetchFundFlowSectors(5)
      .then((d) => { if (!cancelled) setSectors(d); })
      .catch(() => { if (!cancelled) setSectors(null); })
      .finally(() => { if (!cancelled) setLoadingSectors(false); });
    return () => { cancelled = true; };
  }, []);

  const stockCols = useMemo(() => makeStockColumns(isMobile), [isMobile]);
  const sectorCols = useMemo(() => makeSectorColumns(isMobile), [isMobile]);

  const isStocksTab = activeKey === 'stocks_in' || activeKey === 'stocks_out';
  const activeDate = isStocksTab ? stocks?.date : sectors?.date;
  const activeLoading = isStocksTab ? loadingStocks && !stocks : loadingSectors && !sectors;

  const renderStockTable = (rows: FundFlowStockItem[] | undefined) => (
    !stocks ? (
      <Empty description="数据源不可用" />
    ) : (
      <Table<FundFlowStockItem>
        rowKey="code"
        size="small"
        columns={stockCols}
        dataSource={rows ?? []}
        pagination={false}
      />
    )
  );

  const renderSectorTable = (rows: FundFlowSectorItem[] | undefined) => (
    !sectors ? (
      <Empty description="数据源不可用" />
    ) : (
      <Table<FundFlowSectorItem>
        rowKey="code"
        size="small"
        columns={sectorCols}
        dataSource={rows ?? []}
        pagination={false}
      />
    )
  );

  const items = [
    { key: 'stocks_in', label: '个股流入', children: renderStockTable(stocks?.inflow) },
    { key: 'stocks_out', label: '个股流出', children: renderStockTable(stocks?.outflow) },
    { key: 'sectors_in', label: '板块流入', children: renderSectorTable(sectors?.inflow) },
    { key: 'sectors_out', label: '板块流出', children: renderSectorTable(sectors?.outflow) },
  ];

  return (
    <Card
      size="small"
      title={
        <>
          <span>主力资金</span>
          {activeDate && <Tag color="blue" style={{ marginLeft: 8 }}>{activeDate}</Tag>}
        </>
      }
      loading={activeLoading}
      style={{ marginTop: isMobile ? 12 : 16 }}
      styles={{ body: { padding: isMobile ? '0 0 8px' : '0 16px 12px' } }}
    >
      <Tabs
        activeKey={activeKey}
        onChange={(k) => setActiveKey(k as TabKey)}
        size={isMobile ? 'small' : 'middle'}
        items={items}
        tabBarStyle={{ marginBottom: 8, paddingLeft: isMobile ? 12 : 0 }}
      />
    </Card>
  );
}
