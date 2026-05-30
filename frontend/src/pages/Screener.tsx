import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Segmented,
  Select,
  Tag,
  Space,
  Typography,
  Empty,
  Spin,
  message,
  Grid,
  Collapse,
} from 'antd';
import { SearchOutlined, FilterOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { runScreener, type ScreenerStockResult } from '../api/screener';
import { fetchGroups } from '../api/stocks';
import type { Signal, SystemTag, SystemTagInfo, WatchlistGroup } from '../types';
import { SYSTEM_TAG_META } from '../types';

type GroupFilterValue = 'all' | 'ungrouped' | `tag:${SystemTag}` | number;

const { useBreakpoint } = Grid;
const { CheckableTag } = Tag;

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

export default function Screener() {
  const navigate = useNavigate();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const [period, setPeriod] = useState<string>('daily');
  const [categories, setCategories] = useState<string[]>([]);
  const [levels, setLevels] = useState<string[]>([]);
  const [recentDays, setRecentDays] = useState<number>(3);
  const [groupFilter, setGroupFilter] = useState<GroupFilterValue>('all');
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [ungroupedCount, setUngroupedCount] = useState<number>(0);
  const [systemTags, setSystemTags] = useState<SystemTagInfo[]>([]);
  const [results, setResults] = useState<ScreenerStockResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasScanned, setHasScanned] = useState(false);
  const [summary, setSummary] = useState<{ total_stocks_screened: number; total_matches: number }>({
    total_stocks_screened: 0,
    total_matches: 0,
  });

  useEffect(() => {
    fetchGroups()
      .then((resp) => {
        setGroups(resp.groups);
        setUngroupedCount(resp.ungrouped_count);
        setSystemTags(resp.system_tags ?? []);
      })
      .catch(() => {
        /* 加载分组失败时静默降级，仅影响筛选下拉项 */
      });
  }, []);

  const groupOptions = useMemo(() => {
    const options: { label: string; value: GroupFilterValue }[] = [
      { label: '全部分组', value: 'all' },
      { label: `未分组（${ungroupedCount}）`, value: 'ungrouped' },
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
    return options;
  }, [groups, ungroupedCount, systemTags]);

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
        <Space orientation="vertical" size={isMobile ? 6 : 10} style={{ width: '100%' }}>
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
    <Space orientation="vertical" size={isMobile ? 8 : 14} style={{ width: '100%' }}>
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
      <Typography.Title level={4} style={{ margin: '0 0 12px 0' }}>
        选股扫描
      </Typography.Title>

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
