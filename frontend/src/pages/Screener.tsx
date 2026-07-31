import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Collapse,
  Empty,
  Grid,
  InputNumber,
  Select,
  Segmented,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { SearchOutlined, FilterOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table';
import type { SorterResult } from 'antd/es/table/interface';
import { runScreener, type ScreenerStockResult } from '../api/screener';
import {
  runConditionScreener,
  type ConditionScreenerResult,
  type ConditionScreenerParams,
} from '../api/screener';
import { fetchGroups } from '../api/stocks';
import type { Signal, SystemTag, SystemTagInfo, WatchlistGroup } from '../types';
import { SYSTEM_TAG_META } from '../types';

type GroupFilterValue = 'all' | 'ungrouped' | `tag:${SystemTag}` | number;

const { useBreakpoint } = Grid;
const { CheckableTag } = Tag;

// ═══════════════════════════════════════════════════════════
// 共享工具
// ═══════════════════════════════════════════════════════════

function useGroups() {
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [ungroupedCount, setUngroupedCount] = useState(0);
  const [systemTags, setSystemTags] = useState<SystemTagInfo[]>([]);

  useEffect(() => {
    fetchGroups()
      .then((resp) => {
        setGroups(resp.groups);
        setUngroupedCount(resp.ungrouped_count);
        setSystemTags(resp.system_tags ?? []);
      })
      .catch(() => {});
  }, []);

  const groupOptions = useMemo(() => {
    const options: { label: string; value: GroupFilterValue }[] = [
      { label: '全部分组', value: 'all' },
    ];
    for (const meta of SYSTEM_TAG_META) {
      const info = systemTags.find((t) => t.key === meta.key);
      const count = info?.count ?? 0;
      options.push({ label: `${meta.label}（${count}）`, value: `tag:${meta.key}` });
    }
    for (const g of groups) {
      const count = g.count ?? 0;
      options.push({ label: `${g.name}（${count}）`, value: g.id });
    }
    options.push({ label: `未分组（${ungroupedCount}）`, value: 'ungrouped' });
    return options;
  }, [groups, ungroupedCount, systemTags]);

  return { groups, ungroupedCount, systemTags, groupOptions };
}

// ═══════════════════════════════════════════════════════════
// Tab 1：条件选股
// ═══════════════════════════════════════════════════════════

const MARKET_CAP_OPTIONS = [
  { label: '不限', value: '' },
  { label: '50亿以下', value: '0-50' },
  { label: '50~200亿', value: '50-200' },
  { label: '200~1000亿', value: '200-1000' },
  { label: '1000亿以上', value: '1000-' },
];

const AMOUNT_OPTIONS = [
  { label: '不限', value: '' },
  { label: '1亿以下', value: '0-1' },
  { label: '1~5亿', value: '1-5' },
  { label: '5~20亿', value: '5-20' },
  { label: '20亿以上', value: '20-' },
];

function parseRange(val: string): [number | undefined, number | undefined] {
  if (!val) return [undefined, undefined];
  const [lo, hi] = val.split('-');
  return [lo ? Number(lo) : undefined, hi ? Number(hi) : undefined];
}

function formatMarketCap(val: number | null): string {
  if (val == null) return '-';
  const yi = val / 1e8;
  if (yi >= 10000) return `${(yi / 10000).toFixed(2)}万亿`;
  return `${yi.toFixed(2)}亿`;
}

function formatAmount(val: number | null): string {
  if (val == null) return '-';
  const yi = val / 1e8;
  if (yi >= 1) return `${yi.toFixed(2)}亿`;
  const wan = val / 1e4;
  return `${wan.toFixed(0)}万`;
}

function ConditionScreenerTab() {
  const navigate = useNavigate();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const { groupOptions } = useGroups();

  const [peMin, setPeMin] = useState<number | null>(null);
  const [peMax, setPeMax] = useState<number | null>(null);
  const [pbMin, setPbMin] = useState<number | null>(null);
  const [pbMax, setPbMax] = useState<number | null>(null);
  const [marketCapRange, setMarketCapRange] = useState('');
  const [changePctMin, setChangePctMin] = useState<number | null>(null);
  const [changePctMax, setChangePctMax] = useState<number | null>(null);
  const [turnoverMin, setTurnoverMin] = useState<number | null>(null);
  const [turnoverMax, setTurnoverMax] = useState<number | null>(null);
  const [volumeRatioMin, setVolumeRatioMin] = useState<number | null>(null);
  const [volumeRatioMax, setVolumeRatioMax] = useState<number | null>(null);
  const [amplitudeMin, setAmplitudeMin] = useState<number | null>(null);
  const [amplitudeMax, setAmplitudeMax] = useState<number | null>(null);
  const [amountRange, setAmountRange] = useState('');
  const [scope, setScope] = useState<'all' | 'watchlist'>('all');
  const [securityType, setSecurityType] = useState<'stock' | 'etf'>('stock');
  const [discountRateMin, setDiscountRateMin] = useState<number | null>(null);
  const [discountRateMax, setDiscountRateMax] = useState<number | null>(null);
  const [sizeMin, setSizeMin] = useState<number | null>(null);
  const [sizeMax, setSizeMax] = useState<number | null>(null);
  const [groupFilter, setGroupFilter] = useState<GroupFilterValue>('all');

  const [sortBy, setSortBy] = useState('amount');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const [results, setResults] = useState<ConditionScreenerResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const doSearch = useCallback(
    async (p: number = page, sb: string = sortBy, so: string = sortOrder) => {
      setLoading(true);
      try {
        const [capMin, capMax] = parseRange(marketCapRange);
        const [amtMin, amtMax] = parseRange(amountRange);

        const params: ConditionScreenerParams = {
          sort_by: sb,
          sort_order: so,
          page: p,
          page_size: pageSize,
          scope,
        };
        if (securityType === 'etf') {
          params.scope = 'all_etf';
        }
        if (peMin != null) params.pe_min = peMin;
        if (peMax != null) params.pe_max = peMax;
        if (pbMin != null) params.pb_min = pbMin;
        if (pbMax != null) params.pb_max = pbMax;
        if (capMin != null) params.market_cap_min = capMin;
        if (capMax != null) params.market_cap_max = capMax;
        if (changePctMin != null) params.change_pct_min = changePctMin;
        if (changePctMax != null) params.change_pct_max = changePctMax;
        if (turnoverMin != null) params.turnover_min = turnoverMin;
        if (turnoverMax != null) params.turnover_max = turnoverMax;
        if (volumeRatioMin != null) params.volume_ratio_min = volumeRatioMin;
        if (volumeRatioMax != null) params.volume_ratio_max = volumeRatioMax;
        if (amplitudeMin != null) params.amplitude_min = amplitudeMin;
        if (amplitudeMax != null) params.amplitude_max = amplitudeMax;
        if (amtMin != null) params.amount_min = amtMin;
        if (amtMax != null) params.amount_max = amtMax;
        if (discountRateMin != null) params.discount_rate_min = discountRateMin;
        if (discountRateMax != null) params.discount_rate_max = discountRateMax;
        if (sizeMin != null) params.size_min = sizeMin;
        if (sizeMax != null) params.size_max = sizeMax;

        if (scope === 'watchlist') {
          if (typeof groupFilter === 'number') {
            params.group_id = groupFilter;
          } else if (typeof groupFilter === 'string' && groupFilter.startsWith('tag:')) {
            params.tag = groupFilter.slice(4);
          }
        }

        const resp = await runConditionScreener(params);
        setResults(resp.results);
        setTotal(resp.total);
        setPage(resp.page);
        setHasSearched(true);
      } catch (e) {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        message.error(detail || '筛选失败，请稍后重试');
      } finally {
        setLoading(false);
      }
    },
    [
      peMin, peMax, pbMin, pbMax, marketCapRange, changePctMin, changePctMax,
      turnoverMin, turnoverMax, volumeRatioMin, volumeRatioMax,
      amplitudeMin, amplitudeMax, amountRange, scope, groupFilter,
      discountRateMin, discountRateMax, sizeMin, sizeMax, securityType,
      page, pageSize, sortBy, sortOrder,
    ],
  );

  const handleReset = () => {
    setPeMin(null);
    setPeMax(null);
    setPbMin(null);
    setPbMax(null);
    setMarketCapRange('');
    setChangePctMin(null);
    setChangePctMax(null);
    setTurnoverMin(null);
    setTurnoverMax(null);
    setVolumeRatioMin(null);
    setVolumeRatioMax(null);
    setAmplitudeMin(null);
    setAmplitudeMax(null);
    setAmountRange('');
    setScope('all');
    setGroupFilter('all');
    setDiscountRateMin(null);
    setDiscountRateMax(null);
    setSizeMin(null);
    setSizeMax(null);
    setSecurityType('stock');
    setSortBy('amount');
    setSortOrder('desc');
    setPage(1);
  };

  const handleTableChange = (
    pagination: TablePaginationConfig,
    _filters: Record<string, unknown>,
    sorter: SorterResult<ConditionScreenerResult> | SorterResult<ConditionScreenerResult>[],
  ) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    const newPage = pagination.current ?? 1;
    const newSortBy = (s?.field as string) ?? sortBy;
    const newSortOrder = s?.order === 'ascend' ? 'asc' : 'desc';
    setSortBy(newSortBy);
    setSortOrder(newSortOrder);
    setPage(newPage);
    if (pagination.pageSize && pagination.pageSize !== pageSize) {
      setPageSize(pagination.pageSize);
    }
    doSearch(newPage, newSortBy, newSortOrder);
  };

  const columns: ColumnsType<ConditionScreenerResult> = [
    {
      title: '代码',
      dataIndex: 'code',
      width: 90,
      fixed: isMobile ? undefined : 'left',
      render: (code: string) => (
        <Typography.Link onClick={() => navigate(`/stock/${code}`)}>{code}</Typography.Link>
      ),
    },
    {
      title: '名称',
      dataIndex: 'name',
      width: 90,
      fixed: isMobile ? undefined : 'left',
      ellipsis: true,
      render: (name: string, record) => (
        <Typography.Link onClick={() => navigate(`/stock/${record.code}`)}>{name}</Typography.Link>
      ),
    },
    {
      title: '最新价',
      dataIndex: 'price',
      width: 80,
      sorter: true,
      render: (v: number | null) => (v != null ? v.toFixed(2) : '-'),
    },
    {
      title: '涨跌幅',
      dataIndex: 'change_pct',
      width: 85,
      sorter: true,
      render: (v: number | null) => {
        if (v == null) return '-';
        const color = v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : undefined;
        return <span style={{ color }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span>;
      },
    },
    {
      title: 'PE',
      dataIndex: 'pe',
      width: 70,
      sorter: securityType !== 'etf',
      render: (v: number | null) => {
        if (securityType === 'etf') return <Typography.Text type="secondary">—</Typography.Text>;
        return v != null ? v.toFixed(2) : '-';
      },
    },
    {
      title: 'PB',
      dataIndex: 'pb',
      width: 70,
      sorter: securityType !== 'etf',
      render: (v: number | null) => {
        if (securityType === 'etf') return <Typography.Text type="secondary">—</Typography.Text>;
        return v != null ? v.toFixed(2) : '-';
      },
    },
    {
      title: '总市值',
      dataIndex: 'total_market_cap',
      width: 100,
      sorter: securityType !== 'etf',
      render: (v: number | null) => {
        if (securityType === 'etf') return <Typography.Text type="secondary">—</Typography.Text>;
        return formatMarketCap(v);
      },
    },
    {
      title: '换手率',
      dataIndex: 'turnover',
      width: 80,
      sorter: true,
      render: (v: number | null) => (v != null ? `${v.toFixed(2)}%` : '-'),
    },
    {
      title: '量比',
      dataIndex: 'volume_ratio',
      width: 70,
      sorter: true,
      render: (v: number | null) => (v != null ? v.toFixed(2) : '-'),
    },
    {
      title: '振幅',
      dataIndex: 'amplitude',
      width: 75,
      sorter: true,
      render: (v: number | null) => (v != null ? `${v.toFixed(2)}%` : '-'),
    },
    {
      title: '成交额',
      dataIndex: 'amount',
      width: 100,
      sorter: true,
      render: (v: number | null) => formatAmount(v),
    },
    {
      title: '行业',
      dataIndex: 'industry',
      width: 80,
      ellipsis: true,
    },
  ];

  const rangeInputStyle = { width: isMobile ? 70 : 80 };
  const separator = <span style={{ margin: '0 4px', color: '#999' }}>~</span>;

  const filterBody = (
    <Space direction="vertical" size={isMobile ? 6 : 10} style={{ width: '100%' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: isMobile ? 8 : 16 }}>
        {securityType === 'stock' && (
          <>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                市盈率(PE)
              </Typography.Text>
              <Space size={0}>
                <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={peMin} onChange={setPeMin} />
                {separator}
                <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={peMax} onChange={setPeMax} />
              </Space>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                市净率(PB)
              </Typography.Text>
              <Space size={0}>
                <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={pbMin} onChange={setPbMin} />
                {separator}
                <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={pbMax} onChange={setPbMax} />
              </Space>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                总市值
              </Typography.Text>
              <Select
                size="small"
                style={{ width: isMobile ? 120 : 140 }}
                value={marketCapRange}
                onChange={setMarketCapRange}
                options={MARKET_CAP_OPTIONS}
              />
            </div>
          </>
        )}
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            涨跌幅(%)
          </Typography.Text>
          <Space size={0}>
            <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={changePctMin} onChange={setChangePctMin} />
            {separator}
            <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={changePctMax} onChange={setChangePctMax} />
          </Space>
        </div>
      </div>
      {securityType === 'etf' && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: isMobile ? 8 : 16 }}>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              折溢价率(%)
            </Typography.Text>
            <Space size={0}>
              <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={discountRateMin} onChange={setDiscountRateMin} />
              {separator}
              <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={discountRateMax} onChange={setDiscountRateMax} />
            </Space>
          </div>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              规模（亿）
            </Typography.Text>
            <Space size={0}>
              <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={sizeMin} onChange={setSizeMin} />
              {separator}
              <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={sizeMax} onChange={setSizeMax} />
            </Space>
          </div>
        </div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: isMobile ? 8 : 16 }}>
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            换手率(%)
          </Typography.Text>
          <Space size={0}>
            <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={turnoverMin} onChange={setTurnoverMin} />
            {separator}
            <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={turnoverMax} onChange={setTurnoverMax} />
          </Space>
        </div>
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            量比
          </Typography.Text>
          <Space size={0}>
            <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={volumeRatioMin} onChange={setVolumeRatioMin} />
            {separator}
            <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={volumeRatioMax} onChange={setVolumeRatioMax} />
          </Space>
        </div>
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            振幅(%)
          </Typography.Text>
          <Space size={0}>
            <InputNumber size="small" style={rangeInputStyle} placeholder="最小" value={amplitudeMin} onChange={setAmplitudeMin} />
            {separator}
            <InputNumber size="small" style={rangeInputStyle} placeholder="最大" value={amplitudeMax} onChange={setAmplitudeMax} />
          </Space>
        </div>
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            成交额
          </Typography.Text>
          <Select
            size="small"
            style={{ width: isMobile ? 120 : 140 }}
            value={amountRange}
            onChange={setAmountRange}
            options={AMOUNT_OPTIONS}
          />
        </div>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: isMobile ? 8 : 16, alignItems: 'flex-end' }}>
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            股票范围
          </Typography.Text>
          <Segmented
            size="small"
            value={securityType === 'etf' ? 'all_etf' : scope}
            onChange={(v) => {
              if (v === 'all_etf') {
                setSecurityType('etf');
                setScope('all');
              } else if (v === 'all') {
                setSecurityType('stock');
                setScope('all');
              } else {
                setSecurityType('stock');
                setScope(v as 'all' | 'watchlist');
              }
            }}
            options={[
              { label: '全部A股', value: 'all' },
              { label: '全部ETF', value: 'all_etf' },
              { label: '自选股', value: 'watchlist' },
            ]}
          />
        </div>
        {securityType === 'stock' && scope === 'watchlist' && (
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              分组
            </Typography.Text>
            <Select<GroupFilterValue>
              size="small"
              value={groupFilter}
              onChange={setGroupFilter}
              style={{ width: isMobile ? 120 : 160 }}
              options={groupOptions}
            />
          </div>
        )}
        <Space size={8}>
          <Button type="primary" size="small" icon={<SearchOutlined />} onClick={() => { setPage(1); doSearch(1); }} loading={loading}>
            筛选
          </Button>
          <Button size="small" onClick={handleReset}>重置</Button>
        </Space>
      </div>
    </Space>
  );

  return (
    <div>
      {isMobile ? (
        <Collapse
          size="small"
          defaultActiveKey={['filters']}
          style={{ marginBottom: 12 }}
          items={[{ key: 'filters', label: <Space size={6}><FilterOutlined /><span>筛选条件</span></Space>, children: filterBody }]}
        />
      ) : (
        <Card title={<Space size={6}><FilterOutlined /><span>筛选条件</span></Space>} size="small" style={{ marginBottom: 16 }}>
          {filterBody}
        </Card>
      )}

      {!hasSearched ? (
        <Empty description="设置筛选条件后点击「筛选」" />
      ) : (
        <>
          <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: isMobile ? 12 : undefined }}>
            共筛选出 {total} 只{securityType === 'etf' ? 'ETF' : '股票'}
          </Typography.Text>
          <Table<ConditionScreenerResult>
            columns={columns}
            dataSource={results}
            rowKey="code"
            size="small"
            loading={loading}
            scroll={{ x: 1000 }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: ['20', '50', '100'],
              showTotal: (t) => `共 ${t} 条`,
              size: 'small',
            }}
            onChange={handleTableChange}
          />
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// Tab 2：技术信号扫描（原有逻辑）
// ═══════════════════════════════════════════════════════════

const SIGNAL_CATEGORY_OPTIONS: { label: string; value: string }[] = [
  { label: '趋势', value: 'trend' },
  { label: '动量', value: 'momentum' },
  { label: '反转', value: 'reversal' },
  { label: '量能', value: 'volume' },
];

const SIGNAL_LEVEL_OPTIONS: { label: string; value: string }[] = [
  { label: '看多', value: 'bullish' },
  { label: '看空', value: 'bearish' },
];

const PERIOD_OPTIONS = [
  { label: '日线', value: 'daily' },
  { label: '周线', value: 'weekly' },
  { label: '月线', value: 'monthly' },
];

function levelColor(level?: string): string {
  if (level === 'bullish') return 'green';
  if (level === 'bearish') return 'red';
  return 'blue';
}

function SignalTags({ signals }: { signals: Signal[] }) {
  return (
    <Space size={[4, 4]} wrap>
      {signals.map((s, idx) => (
        <Tag key={`${s.date}-${s.type}-${idx}`} color={levelColor(s.level)}>
          {s.name || s.type}
        </Tag>
      ))}
    </Space>
  );
}

interface DateGroup {
  date: string;
  rows: { stock: ScreenerStockResult; signals: Signal[] }[];
  bullishCount: number;
  bearishCount: number;
}

function groupResultsByDate(results: ScreenerStockResult[]): DateGroup[] {
  const map = new Map<string, Map<string, { stock: ScreenerStockResult; signals: Signal[] }>>();

  for (const stock of results) {
    for (const sig of stock.matching_signals) {
      if (!sig.date) continue;
      let dayMap = map.get(sig.date);
      if (!dayMap) {
        dayMap = new Map();
        map.set(sig.date, dayMap);
      }
      let entry = dayMap.get(stock.code);
      if (!entry) {
        entry = { stock, signals: [] };
        dayMap.set(stock.code, entry);
      }
      entry.signals.push(sig);
    }
  }

  return Array.from(map.entries())
    .sort((a, b) => (a[0] < b[0] ? 1 : a[0] > b[0] ? -1 : 0))
    .map(([date, dayMap]) => {
      const rows = Array.from(dayMap.values()).sort(
        (a, b) => b.signals.length - a.signals.length,
      );
      let bullishCount = 0;
      let bearishCount = 0;
      for (const r of rows) {
        for (const s of r.signals) {
          if (s.level === 'bullish') bullishCount += 1;
          else if (s.level === 'bearish') bearishCount += 1;
        }
      }
      return { date, rows, bullishCount, bearishCount };
    });
}

interface ChipGroupProps {
  options: { label: string; value: string }[];
  values: string[];
  onChange: (values: string[]) => void;
}

function ChipGroup({ options, values, onChange }: ChipGroupProps) {
  const toggle = (val: string, checked: boolean) => {
    const next = checked ? [...values, val] : values.filter((v) => v !== val);
    onChange(next);
  };
  return (
    <Space size={[6, 6]} wrap>
      {options.map((opt) => {
        const checked = values.includes(opt.value);
        return (
          <CheckableTag
            key={opt.value}
            checked={checked}
            onChange={(c) => toggle(opt.value, c)}
            style={{ padding: '2px 10px', fontSize: 13, borderRadius: 12 }}
          >
            {opt.label}
          </CheckableTag>
        );
      })}
    </Space>
  );
}

function SignalScreenerTab() {
  const navigate = useNavigate();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const { groupOptions } = useGroups();

  const [period, setPeriod] = useState<string>('daily');
  const [categories, setCategories] = useState<string[]>([]);
  const [levels, setLevels] = useState<string[]>([]);
  const [recentDays, setRecentDays] = useState<number>(3);
  const [groupFilter, setGroupFilter] = useState<GroupFilterValue>('all');
  const [results, setResults] = useState<ScreenerStockResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasScanned, setHasScanned] = useState(false);
  const [summary, setSummary] = useState<{ total_stocks_screened: number; total_matches: number }>({
    total_stocks_screened: 0,
    total_matches: 0,
  });

  const activeFilterCount = useMemo(
    () => categories.length + levels.length + (groupFilter !== 'all' ? 1 : 0),
    [categories, levels, groupFilter],
  );

  const handleScan = async () => {
    setLoading(true);
    try {
      let scopeParams: { ungrouped?: boolean; group_id?: number; tag?: SystemTag } = {};
      if (groupFilter === 'ungrouped') {
        scopeParams = { ungrouped: true };
      } else if (typeof groupFilter === 'string' && groupFilter.startsWith('tag:')) {
        scopeParams = { tag: groupFilter.slice(4) as SystemTag };
      } else if (typeof groupFilter === 'number') {
        scopeParams = { group_id: groupFilter };
      }
      const resp = await runScreener({
        period,
        signal_categories: categories.join(','),
        signal_levels: levels.join(','),
        recent_days: recentDays,
        ...scopeParams,
      });
      setResults(resp.results);
      setSummary({
        total_stocks_screened: resp.total_stocks_screened,
        total_matches: resp.total_matches,
      });
      setHasScanned(true);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '扫描失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setCategories([]);
    setLevels([]);
    setRecentDays(3);
    setPeriod('daily');
    setGroupFilter('all');
  };

  const dateGroups = useMemo(() => groupResultsByDate(results), [results]);

  const renderGroupedResults = () => {
    if (dateGroups.length === 0) {
      return <Empty description="没有匹配的股票，请放宽筛选条件" />;
    }

    const items = dateGroups.map((group) => ({
      key: group.date,
      label: (
        <Space size={8} wrap>
          <Typography.Text strong>{group.date}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {group.rows.length} 只
          </Typography.Text>
          {group.bullishCount > 0 && <Tag color="green">多 {group.bullishCount}</Tag>}
          {group.bearishCount > 0 && <Tag color="red">空 {group.bearishCount}</Tag>}
        </Space>
      ),
      children: (
        <Space direction="vertical" size={isMobile ? 6 : 10} style={{ width: '100%' }}>
          {group.rows.map(({ stock, signals }) => (
            <div
              key={`${group.date}-${stock.code}`}
              style={{
                display: 'flex',
                flexDirection: isMobile ? 'column' : 'row',
                gap: isMobile ? 4 : 12,
                padding: isMobile ? '4px 0' : '8px 0',
                borderBottom: '1px dashed rgba(0,0,0,0.06)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 8,
                  minWidth: isMobile ? undefined : 220,
                }}
              >
                <Typography.Text strong>{stock.name}</Typography.Text>
                <Typography.Text code style={{ fontSize: 12 }}>
                  {stock.code}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {stock.latest_close != null ? stock.latest_close.toFixed(2) : '-'}
                </Typography.Text>
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <SignalTags signals={signals} />
              </div>
              <Button
                type="link"
                size="small"
                style={{ padding: 0, alignSelf: isMobile ? 'flex-end' : 'center' }}
                onClick={() => navigate(`/stock/${stock.code}`)}
              >
                分析 →
              </Button>
            </div>
          ))}
        </Space>
      ),
    }));

    return (
      <Collapse
        size={isMobile ? 'small' : 'middle'}
        defaultActiveKey={dateGroups.map((g) => g.date)}
        items={items}
      />
    );
  };

  const renderResults = () => {
    if (loading) {
      return (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" />
        </div>
      );
    }

    if (!hasScanned) {
      return <Empty description="设置筛选条件后点击「扫描」" />;
    }

    if (results.length === 0) {
      return <Empty description="没有匹配的股票，请放宽筛选条件" />;
    }

    return (
      <>
        <Typography.Text type="secondary" style={{ marginBottom: 12, display: 'block', fontSize: isMobile ? 12 : undefined }}>
          已扫描 {summary.total_stocks_screened} 只，命中 {summary.total_matches} 只，
          覆盖 {dateGroups.length} 个交易日
        </Typography.Text>
        {renderGroupedResults()}
      </>
    );
  };

  const filterBody = (
    <Space direction="vertical" size={isMobile ? 8 : 14} style={{ width: '100%' }}>
      <div>
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
          周期
        </Typography.Text>
        <Segmented
          value={period}
          onChange={(val) => setPeriod(val as string)}
          size={isMobile ? 'small' : 'middle'}
          options={PERIOD_OPTIONS}
          block={isMobile}
        />
      </div>

      <div>
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
          股票分组
        </Typography.Text>
        <Select<GroupFilterValue>
          value={groupFilter}
          onChange={(val) => setGroupFilter(val)}
          style={{ width: isMobile ? '100%' : 200 }}
          size={isMobile ? 'small' : 'middle'}
          options={groupOptions}
        />
      </div>

      <div>
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
          信号方向
        </Typography.Text>
        <ChipGroup options={SIGNAL_LEVEL_OPTIONS} values={levels} onChange={setLevels} />
      </div>

      <div>
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
          信号类别
        </Typography.Text>
        <ChipGroup
          options={SIGNAL_CATEGORY_OPTIONS}
          values={categories}
          onChange={setCategories}
        />
      </div>

      <div>
        <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 6 }}>
          最近交易日
        </Typography.Text>
        <Select
          value={recentDays}
          onChange={(val) => setRecentDays(val)}
          style={{ width: 96 }}
          size={isMobile ? 'small' : 'middle'}
          options={Array.from({ length: 10 }, (_, i) => ({
            label: `${i + 1} 天`,
            value: i + 1,
          }))}
        />
      </div>

      <Space size={8} style={{ width: '100%' }}>
        <Button
          type="primary"
          icon={<SearchOutlined />}
          onClick={handleScan}
          loading={loading}
          block={isMobile}
        >
          扫描
        </Button>
        <Button onClick={handleReset}>重置</Button>
      </Space>
    </Space>
  );

  const filterTitle = (
    <Space size={6}>
      <FilterOutlined />
      <span>筛选器</span>
      {activeFilterCount > 0 && <Tag color="blue">{activeFilterCount}</Tag>}
    </Space>
  );

  return (
    <div>
      {isMobile ? (
        <Collapse
          size="small"
          defaultActiveKey={[]}
          style={{ marginBottom: 12 }}
          items={[
            {
              key: 'filters',
              label: filterTitle,
              children: filterBody,
            },
          ]}
        />
      ) : (
        <Card title={filterTitle} size="small" style={{ marginBottom: 16 }}>
          {filterBody}
        </Card>
      )}

      {renderResults()}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════════

export default function Screener() {
  return (
    <div>
      <Typography.Title level={4} style={{ margin: '0 0 12px 0' }}>
        选股扫描
      </Typography.Title>
      <Tabs
        defaultActiveKey="condition"
        items={[
          {
            key: 'condition',
            label: '条件选股',
            children: <ConditionScreenerTab />,
          },
          {
            key: 'signal',
            label: '技术信号',
            children: <SignalScreenerTab />,
          },
        ]}
      />
    </div>
  );
}
