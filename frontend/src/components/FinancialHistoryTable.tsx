import { useEffect, useState } from 'react';
import { Card, Table, Spin, Typography, Grid } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { fetchFinancialHistory, type FinancialHistory } from '../api/market';

const { useBreakpoint } = Grid;

interface Props {
  code: string;
}

const GROWTH_INDICATORS = new Set(['营收同比', '净利润同比']);

function formatValue(v: number | null, unit: string): string {
  if (v == null) return '—';
  if (unit === '%') return `${v.toFixed(2)}%`;
  if (unit === '亿元' || unit === '亿股') return v.toFixed(2);
  if (unit === '元') return v.toFixed(2);
  return v.toFixed(2);
}

interface RowData {
  key: string;
  indicator: string;
  unit: string;
  isGrowth: boolean;
  [year: string]: string | number | null | boolean;
}

export default function FinancialHistoryTable({ code }: Props) {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [data, setData] = useState<FinancialHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFinancialHistory(code)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (!cancelled) {
          const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          setError(detail || '加载财务数据失败');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <Card size="small" title="关键财务指标" style={{ marginBottom: isMobile ? 8 : 12 }}>
        <Typography.Text type="danger">{error}</Typography.Text>
      </Card>
    );
  }

  const columns: ColumnsType<RowData> = [
    {
      title: '指标',
      dataIndex: 'indicator',
      key: 'indicator',
      fixed: 'left',
      width: isMobile ? 110 : 130,
      render: (text: string, record: RowData) => (
        <span>
          {text}
          {record.unit && (
            <Typography.Text type="secondary" style={{ fontSize: 11, marginLeft: 2 }}>
              ({record.unit})
            </Typography.Text>
          )}
        </span>
      ),
    },
  ];

  const dataSource: RowData[] = [];

  if (data) {
    for (const year of data.years) {
      columns.push({
        title: year,
        dataIndex: year,
        key: year,
        align: 'right',
        width: isMobile ? 80 : 100,
        render: (val: number | null, record: RowData) => {
          const text = formatValue(val as number | null, record.unit as string);
          if (record.isGrowth && val != null) {
            const color = val > 0 ? '#3f8600' : val < 0 ? '#cf1322' : undefined;
            return <span style={{ color }}>{text}</span>;
          }
          return text;
        },
      });
    }

    for (const ind of data.indicators) {
      const row: RowData = {
        key: ind.name,
        indicator: ind.name,
        unit: ind.unit,
        isGrowth: GROWTH_INDICATORS.has(ind.name),
      };
      for (let i = 0; i < data.years.length; i++) {
        row[data.years[i]] = ind.values[i];
      }
      dataSource.push(row);
    }
  }

  return (
    <Card size="small" title="关键财务指标" style={{ marginBottom: isMobile ? 8 : 12 }}>
      <Spin spinning={loading}>
        <Table
          columns={columns}
          dataSource={dataSource}
          pagination={false}
          size="small"
          bordered
          scroll={{ x: 'max-content' }}
          style={{ fontSize: isMobile ? 12 : 14 }}
        />
      </Spin>
    </Card>
  );
}
