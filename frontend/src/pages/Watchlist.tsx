import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Table,
  Button,
  Modal,
  Space,
  Popconfirm,
  Typography,
  message,
  List,
  Tag,
  Grid,
  Select,
  Input,
  InputNumber,
  Tabs,
  Tooltip,
  Empty,
} from 'antd';
import StockSearchInput from '../components/StockSearchInput';
import WatchlistNewsCard from '../components/WatchlistNewsCard';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  AppstoreOutlined,
  HolderOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table';
import type { SorterResult, FilterValue } from 'antd/es/table/interface';
import type { TabsProps } from 'antd';
import type { StockInfo, SystemTag, SystemTagInfo, WatchlistGroup } from '../types';
import { SYSTEM_TAG_META } from '../types';

const { useBreakpoint } = Grid;
import {
  fetchWatchlist,
  addStock,
  deleteStock,
  fetchGroups,
  createGroup,
  renameGroup,
  deleteGroup,
  reorderGroups,
  setStockGroup,
  setStockTags,
  setStockTargets,
} from '../api/stocks';
import { fetchQuotes, type QuoteData } from '../api/market';

const ALL_KEY = '__all__';
const UNGROUPED_KEY = '__ungrouped__';
const TAG_PREFIX = '__tag_';

type GroupFilter =
  | typeof ALL_KEY
  | typeof UNGROUPED_KEY
  | `${typeof TAG_PREFIX}${SystemTag}__`
  | number;

function tagFilterKey(tag: SystemTag): `${typeof TAG_PREFIX}${SystemTag}__` {
  return `${TAG_PREFIX}${tag}__` as `${typeof TAG_PREFIX}${SystemTag}__`;
}

function parseTagFilter(key: string): SystemTag | null {
  if (!key.startsWith(TAG_PREFIX) || !key.endsWith('__')) return null;
  const t = key.slice(TAG_PREFIX.length, -2);
  if (t === 'holding' || t === 'watching') return t;
  return null;
}

interface TargetDiff {
  diff: number;
  diffPct: number;
  alerted: boolean;
}

function computeDiff(
  currentPrice: number | null | undefined,
  target: number | null | undefined,
  threshold: number | null | undefined,
): TargetDiff | null {
  if (currentPrice == null || !(currentPrice > 0)) return null;
  if (target == null || !(target > 0)) return null;
  const diff = currentPrice - target;
  const diffPct = (diff / target) * 100;
  const alerted = threshold != null && threshold >= 0 && Math.abs(diffPct) <= threshold;
  return { diff, diffPct, alerted };
}

function EditableTargetCellInner({
  initial,
  precision,
  placeholder,
  min,
  max,
  onCommit,
}: {
  initial: number | null;
  precision: number;
  placeholder?: string;
  min?: number;
  max?: number;
  onCommit: (next: number | null) => void;
}) {
  const [draft, setDraft] = useState<number | null>(initial);
  return (
    <InputNumber
      autoFocus
      size="small"
      value={draft}
      min={min}
      max={max}
      precision={precision}
      controls={false}
      style={{ width: '100%' }}
      placeholder={placeholder}
      onChange={(v) => setDraft(v == null ? null : Number(v))}
      onBlur={() => onCommit(draft)}
      onPressEnter={() => onCommit(draft)}
    />
  );
}

function EditableTargetCell({
  value,
  precision,
  suffix,
  placeholder,
  min,
  max,
  onSave,
}: {
  value: number | null | undefined;
  precision: number;
  suffix?: string;
  placeholder?: string;
  min?: number;
  max?: number;
  onSave: (next: number | null) => Promise<void> | void;
}) {
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <EditableTargetCellInner
        initial={value ?? null}
        precision={precision}
        placeholder={placeholder}
        min={min}
        max={max}
        onCommit={async (next) => {
          setEditing(false);
          if ((next ?? null) === (value ?? null)) return;
          await onSave(next);
        }}
      />
    );
  }
  const display =
    value != null
      ? `${value.toFixed(precision)}${suffix ?? ''}`
      : placeholder ?? '—';
  return (
    <Typography.Link
      onClick={() => setEditing(true)}
      style={{
        display: 'inline-block',
        minWidth: 48,
        color: value != null ? undefined : '#bfbfbf',
      }}
    >
      {display}
    </Typography.Link>
  );
}

function StockTagBadges({ tags, size = 'small' }: { tags: string[] | undefined; size?: 'small' | 'mini' }) {
  if (!tags || tags.length === 0) return null;
  return (
    <Space size={2} wrap>
      {SYSTEM_TAG_META.filter((m) => tags.includes(m.key)).map((m) => (
        <Tag
          key={m.key}
          color={m.color}
          style={{
            marginInlineEnd: 0,
            padding: size === 'mini' ? '0 4px' : '0 6px',
            fontSize: size === 'mini' ? 10 : 11,
            lineHeight: size === 'mini' ? '16px' : '18px',
            borderRadius: 8,
          }}
        >
          {m.label}
        </Tag>
      ))}
    </Space>
  );
}

function eastMoneyUrl(code: string): string {
  const c = code.replace(/\D/g, '');
  const prefix = c.startsWith('6') ? 'sh' : c.startsWith('8') || c.startsWith('4') ? 'bj' : 'sz';
  return `https://quote.eastmoney.com/${prefix}${c}.html`;
}

function formatVolume(v: number | null | undefined): string {
  if (v == null) return '—';
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toFixed(0);
}

function formatMoney(v: number | null | undefined): string {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toFixed(0);
}

export default function Watchlist() {
  const navigate = useNavigate();
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [data, setData] = useState<StockInfo[]>([]);
  const [quotes, setQuotes] = useState<Record<string, QuoteData>>({});
  const [groups, setGroups] = useState<WatchlistGroup[]>([]);
  const [ungroupedCount, setUngroupedCount] = useState(0);
  const [systemTagInfos, setSystemTagInfos] = useState<SystemTagInfo[]>([]);
  const [filter, setFilter] = useState<GroupFilter>(ALL_KEY);
  const [loading, setLoading] = useState(false);

  const [modalOpen, setModalOpen] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [searchResults, setSearchResults] = useState<StockInfo[]>([]);
  const [addTargetGroup, setAddTargetGroup] = useState<number | null>(null);

  const [groupMgrOpen, setGroupMgrOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState('');
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const [sortField, setSortField] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend' | null>(null);

  const [viewMode, setViewMode] = useState<'list' | 'news'>('list');

  const dragIndexRef = useRef<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const tabDragIndexRef = useRef<number | null>(null);

  const persistGroupOrder = async (next: WatchlistGroup[]) => {
    setGroups(next);
    try {
      await reorderGroups(next.map((g) => g.id));
      reloadGroups();
    } catch {
      message.error('排序保存失败');
      reloadGroups();
    }
  };

  const handleGroupDrop = async (targetIndex: number) => {
    const from = dragIndexRef.current;
    dragIndexRef.current = null;
    setDragOverIndex(null);
    if (from == null || from === targetIndex) return;
    const next = [...groups];
    const [moved] = next.splice(from, 1);
    next.splice(targetIndex, 0, moved);
    await persistGroupOrder(next);
  };

  const handleTabDrop = async (targetIndex: number) => {
    const from = tabDragIndexRef.current;
    tabDragIndexRef.current = null;
    if (from == null || from === targetIndex) return;
    const next = [...groups];
    const [moved] = next.splice(from, 1);
    next.splice(targetIndex, 0, moved);
    await persistGroupOrder(next);
  };

  const reloadGroups = async () => {
    try {
      const { groups: gs, ungrouped_count, system_tags } = await fetchGroups();
      setGroups(gs);
      setUngroupedCount(ungrouped_count);
      setSystemTagInfos(system_tags ?? []);
    } catch {
      message.error('加载分组失败');
    }
  };

  const quoteSeqRef = useRef(0);

  const reloadStocks = async (current: GroupFilter = filter) => {
    setLoading(true);
    try {
      let opts: Parameters<typeof fetchWatchlist>[0] = {};
      if (current === ALL_KEY) {
        opts = {};
      } else if (current === UNGROUPED_KEY) {
        opts = { ungrouped: true };
      } else if (typeof current === 'string') {
        const tag = parseTagFilter(current);
        if (tag) opts = { tag };
      } else {
        opts = { groupId: current as number };
      }
      const rows = await fetchWatchlist(opts);
      setData(rows);
      const seq = ++quoteSeqRef.current;
      setQuotes({});
      if (rows.length === 0) return;
      const codes = rows.map((r) => r.code);
      fetchQuotes(codes)
        .then((qs) => {
          if (seq !== quoteSeqRef.current) return;
          const next: Record<string, QuoteData> = {};
          for (const q of qs) {
            if (q?.code) next[q.code] = q;
          }
          setQuotes(next);
        })
        .catch(() => {
          /* 静默 */
        });
    } catch {
      message.error('加载自选股失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reloadGroups();
  }, []);

  useEffect(() => {
    reloadStocks(filter);
  }, [filter]);

  const handleAdd = async (stock: StockInfo) => {
    try {
      await addStock(stock.code, stock.name, stock.market || 'A', addTargetGroup, ['watching']);
      message.success(`已添加 ${stock.name}（已标记为关注）`);
      setModalOpen(false);
      setKeyword('');
      setSearchResults([]);
      reloadGroups();
      reloadStocks();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '添加失败');
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteStock(id);
      message.success('已移除');
      reloadGroups();
      reloadStocks();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '删除失败');
    }
  };

  const handleCreateGroup = async () => {
    const name = newGroupName.trim();
    if (!name) return;
    setCreatingGroup(true);
    try {
      await createGroup(name);
      setNewGroupName('');
      await reloadGroups();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '创建分组失败');
    } finally {
      setCreatingGroup(false);
    }
  };

  const handleRenameGroup = async (id: number) => {
    const name = renameValue.trim();
    if (!name) {
      setRenamingId(null);
      return;
    }
    try {
      await renameGroup(id, name);
      setRenamingId(null);
      setRenameValue('');
      reloadGroups();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '重命名失败');
    }
  };

  const handleDeleteGroup = async (id: number) => {
    try {
      await deleteGroup(id);
      if (filter === id) setFilter(ALL_KEY);
      reloadGroups();
      reloadStocks();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '删除分组失败');
    }
  };

  const handleMoveStock = async (stockId: number, groupId: number | null) => {
    try {
      await setStockGroup(stockId, groupId);
      reloadGroups();
      reloadStocks();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '调整分组失败');
    }
  };

  const handleToggleTag = async (stock: StockInfo, tag: SystemTag) => {
    if (stock.id == null) return;
    const current = stock.tags ?? [];
    const next = current.includes(tag)
      ? current.filter((t) => t !== tag)
      : [...current, tag];
    setData((prev) =>
      prev.map((s) => (s.id === stock.id ? { ...s, tags: next } : s)),
    );
    setSystemTagInfos((prev) =>
      prev.map((info) => {
        if (info.key !== tag) return info;
        const delta = next.includes(tag) ? 1 : -1;
        return { ...info, count: Math.max(0, info.count + delta) };
      }),
    );
    try {
      await setStockTags(stock.id, next as SystemTag[]);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '打标失败');
      reloadGroups();
      reloadStocks();
    }
  };

  const handleSaveTargets = async (
    stock: StockInfo,
    payload: { target_price?: number | null; alert_diff_pct?: number | null },
  ) => {
    if (stock.id == null) return;
    setData((prev) =>
      prev.map((s) => (s.id === stock.id ? { ...s, ...payload } : s)),
    );
    try {
      await setStockTargets(stock.id, payload);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '保存失败');
      reloadStocks();
    }
  };

  const totalCount = ungroupedCount + groups.reduce((sum, g) => sum + (g.count ?? 0), 0);

  const systemTagCount = (key: SystemTag) =>
    systemTagInfos.find((t) => t.key === key)?.count ?? 0;

  const tabItems = [
    { key: ALL_KEY, label: <Space size={4}>全部 <Tag>{totalCount}</Tag></Space> },
    ...SYSTEM_TAG_META.map((meta) => ({
      key: tagFilterKey(meta.key),
      label: (
        <Space size={4}>
          <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>
          <Tag>{systemTagCount(meta.key)}</Tag>
        </Space>
      ),
    })),
    ...groups.map((g) => ({
      key: String(g.id),
      label: <Space size={4}>{g.name} <Tag>{g.count ?? 0}</Tag></Space>,
    })),
    { key: UNGROUPED_KEY, label: <Space size={4}>未分组 <Tag>{ungroupedCount}</Tag></Space> },
  ];

  const renderTabBar: TabsProps['renderTabBar'] = (tabBarProps, DefaultTabBar) => (
    <DefaultTabBar {...tabBarProps}>
      {(node) => {
        const key = String(node.key);
        const idx = groups.findIndex((g) => String(g.id) === key);
        if (idx < 0) return node;
        return (
          <div
            key={node.key}
            draggable
            onDragStart={(e) => {
              tabDragIndexRef.current = idx;
              e.dataTransfer.effectAllowed = 'move';
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = 'move';
            }}
            onDrop={(e) => {
              e.preventDefault();
              handleTabDrop(idx);
            }}
            style={{ cursor: 'move' }}
          >
            {node}
          </div>
        );
      }}
    </DefaultTabBar>
  );

  const handleTabChange = (key: string) => {
    if (key === ALL_KEY || key === UNGROUPED_KEY) {
      setFilter(key as GroupFilter);
      return;
    }
    const tag = parseTagFilter(key);
    if (tag) {
      setFilter(tagFilterKey(tag));
      return;
    }
    setFilter(Number(key));
  };

  const sortedData = useMemo(() => {
    if (!sortField || !sortOrder) return data;
    const getVal = (s: StockInfo): number => {
      const q = quotes[s.code];
      if (!q) return Number.NEGATIVE_INFINITY;
      switch (sortField) {
        case 'price': return q.price ?? Number.NEGATIVE_INFINITY;
        case 'change_pct': return q.change_pct ?? Number.NEGATIVE_INFINITY;
        case 'volume': return q.volume ?? Number.NEGATIVE_INFINITY;
        case 'main_net_in': return (q.main_net ?? 0) > 0 ? (q.main_net as number) : Number.NEGATIVE_INFINITY;
        case 'main_net_out': return (q.main_net ?? 0) < 0 ? -(q.main_net as number) : Number.NEGATIVE_INFINITY;
        default: return 0;
      }
    };
    const dir = sortOrder === 'ascend' ? 1 : -1;
    return [...data].sort((a, b) => (getVal(a) - getVal(b)) * dir);
  }, [data, quotes, sortField, sortOrder]);

  const filterLabel = (() => {
    if (filter === ALL_KEY) return '全部';
    if (filter === UNGROUPED_KEY) return '未分组';
    if (typeof filter === 'string') {
      const tag = parseTagFilter(filter);
      if (tag) return SYSTEM_TAG_META.find((m) => m.key === tag)?.label || tag;
    }
    return groups.find((g) => g.id === filter)?.name || '分组';
  })();

  const renderTagToggleRow = (record: StockInfo) => (
    <Space size={4} wrap>
      {SYSTEM_TAG_META.map((meta) => {
        const active = record.tags?.includes(meta.key) ?? false;
        return (
          <Tag.CheckableTag
            key={meta.key}
            checked={active}
            onChange={() => handleToggleTag(record, meta.key)}
            style={{
              padding: '0 6px',
              fontSize: 11,
              lineHeight: '18px',
              borderRadius: 8,
              border: active ? undefined : '1px dashed #d9d9d9',
            }}
          >
            {meta.label}
          </Tag.CheckableTag>
        );
      })}
    </Space>
  );

  const renderMobileList = () => {
    if (sortedData.length === 0 && !loading) {
      return <Empty description="该分组暂无股票" />;
    }
    return (
      <List
        loading={loading}
        dataSource={sortedData}
        renderItem={(record) => {
          const q = quotes[record.code];
          const changeColor = q?.change_pct != null
            ? q.change_pct > 0 ? '#cf1322' : q.change_pct < 0 ? '#3f8600' : undefined
            : undefined;
          const mainNet = q?.main_net ?? null;
          const mainColor = mainNet != null && mainNet > 0 ? '#cf1322' : mainNet != null && mainNet < 0 ? '#3f8600' : undefined;
          return (
            <div
              style={{
                background: '#fff',
                borderRadius: 8,
                padding: '10px 12px',
                marginBottom: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Typography.Link href={eastMoneyUrl(record.code)} target="_blank" rel="noopener noreferrer" style={{ fontSize: 15, fontWeight: 600 }}>{record.name}</Typography.Link>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>{record.code}</Typography.Text>
                  <StockTagBadges tags={record.tags} size="mini" />
                </div>
                <Space size={4}>
                  <Button type="link" size="small" onClick={() => navigate(`/stock/${record.code}`)}>
                    分析
                  </Button>
                  <Popconfirm
                    title="从自选股移除？"
                    onConfirm={() => record.id != null && handleDelete(record.id)}
                  >
                    <Button type="link" size="small" danger>删</Button>
                  </Popconfirm>
                </Space>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 4 }}>
                <Typography.Text strong style={{ fontSize: 18, color: changeColor }}>
                  {q && q.price > 0 ? q.price.toFixed(2) : '—'}
                </Typography.Text>
                {q?.change_pct != null && (
                  <Typography.Text strong style={{ color: changeColor, fontSize: 14 }}>
                    {q.change_pct > 0 ? '+' : ''}{q.change_pct.toFixed(2)}%
                  </Typography.Text>
                )}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 12 }}>
                <Typography.Text type="secondary">成交 {formatVolume(q?.volume)}</Typography.Text>
                <Typography.Text style={{ color: mainColor }}>
                  主力 {mainNet != null ? `${mainNet > 0 ? '+' : ''}${formatMoney(mainNet)}` : '—'}
                </Typography.Text>
              </div>
              {(() => {
                const diff = computeDiff(q?.price, record.target_price, record.alert_diff_pct);
                const diffColor = diff
                  ? diff.diffPct > 0
                    ? '#cf1322'
                    : diff.diffPct < 0
                      ? '#3f8600'
                      : undefined
                  : undefined;
                return (
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 8,
                      marginTop: 6,
                      padding: '4px 6px',
                      background: diff?.alerted ? '#fffbe6' : '#fafafa',
                      borderRadius: 4,
                      fontSize: 12,
                      alignItems: 'center',
                    }}
                  >
                    <Space size={2}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>目标</Typography.Text>
                      <EditableTargetCell
                        value={record.target_price}
                        precision={2}
                        placeholder="设置"
                        min={0}
                        onSave={(next) => handleSaveTargets(record, { target_price: next })}
                      />
                    </Space>
                    <Space size={2}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>阈值</Typography.Text>
                      <EditableTargetCell
                        value={record.alert_diff_pct}
                        precision={2}
                        suffix="%"
                        placeholder="设置"
                        min={0}
                        max={100}
                        onSave={(next) => handleSaveTargets(record, { alert_diff_pct: next })}
                      />
                    </Space>
                    <div style={{ marginLeft: 'auto' }}>
                      {diff ? (
                        <Typography.Text
                          strong={diff.alerted}
                          style={{ color: diffColor, fontSize: 12 }}
                        >
                          差 {`${diff.diffPct > 0 ? '+' : ''}${diff.diffPct.toFixed(2)}%`}
                        </Typography.Text>
                      ) : (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>差 —</Typography.Text>
                      )}
                    </div>
                  </div>
                );
              })()}
              <div style={{ marginTop: 6 }}>{renderTagToggleRow(record)}</div>
            </div>
          );
        }}
      />
    );
  };

  const desktopColumns: ColumnsType<StockInfo> = [
    {
      title: '代码',
      dataIndex: 'code',
      key: 'code',
      width: 90,
      render: (code: string) => (
        <Typography.Link href={eastMoneyUrl(code)} target="_blank" rel="noopener noreferrer">
          {code}
        </Typography.Link>
      ),
    },
    {
      title: '名称',
      key: 'name',
      width: 160,
      render: (_, record) => (
        <Space size={4}>
          <span>{record.name}</span>
          <StockTagBadges tags={record.tags} size="mini" />
        </Space>
      ),
    },
    {
      title: '最新价',
      key: 'price',
      width: 90,
      align: 'right',
      sorter: true,
      sortOrder: sortField === 'price' ? sortOrder : null,
      render: (_, record) => {
        const q = quotes[record.code];
        if (!q || !(q.price > 0)) return <Typography.Text type="secondary">—</Typography.Text>;
        return <Typography.Text strong>{q.price.toFixed(2)}</Typography.Text>;
      },
    },
    {
      title: '涨跌幅',
      key: 'change_pct',
      width: 90,
      align: 'right',
      sorter: true,
      sortOrder: sortField === 'change_pct' ? sortOrder : null,
      render: (_, record) => {
        const q = quotes[record.code];
        if (!q || q.change_pct == null) return <Typography.Text type="secondary">—</Typography.Text>;
        const v = q.change_pct;
        const color = v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : undefined;
        const sign = v > 0 ? '+' : '';
        return <Typography.Text strong style={{ color }}>{`${sign}${v.toFixed(2)}%`}</Typography.Text>;
      },
    },
    {
      title: '最新成交量',
      key: 'volume',
      width: 110,
      align: 'right',
      sorter: true,
      sortOrder: sortField === 'volume' ? sortOrder : null,
      render: (_, record) => {
        const q = quotes[record.code];
        return <Typography.Text>{formatVolume(q?.volume)}</Typography.Text>;
      },
    },
    {
      title: '主力净流入',
      key: 'main_net_in',
      width: 110,
      align: 'right',
      sorter: true,
      sortOrder: sortField === 'main_net_in' ? sortOrder : null,
      render: (_, record) => {
        const q = quotes[record.code];
        const v = q?.main_net;
        if (v == null || v <= 0) return <Typography.Text type="secondary">—</Typography.Text>;
        return <Typography.Text strong style={{ color: '#cf1322' }}>{formatMoney(v)}</Typography.Text>;
      },
    },
    {
      title: '主力净流出',
      key: 'main_net_out',
      width: 110,
      align: 'right',
      sorter: true,
      sortOrder: sortField === 'main_net_out' ? sortOrder : null,
      render: (_, record) => {
        const q = quotes[record.code];
        const v = q?.main_net;
        if (v == null || v >= 0) return <Typography.Text type="secondary">—</Typography.Text>;
        return <Typography.Text strong style={{ color: '#3f8600' }}>{formatMoney(-v)}</Typography.Text>;
      },
    },
    {
      title: <Tooltip title="点击单元格设置目标价">目标价</Tooltip>,
      key: 'target_price',
      width: 100,
      align: 'right',
      render: (_, record) => (
        <EditableTargetCell
          value={record.target_price}
          precision={2}
          placeholder="设置"
          min={0}
          onSave={(next) => handleSaveTargets(record, { target_price: next })}
        />
      ),
    },
    {
      title: (
        <Tooltip title="当前价相对目标价的差值；当 |差值%| ≤ 阈值 时高亮提醒。点击阈值可编辑。">
          差值提醒
        </Tooltip>
      ),
      key: 'alert_diff_pct',
      width: 160,
      align: 'right',
      render: (_, record) => {
        const q = quotes[record.code];
        const diff = computeDiff(q?.price, record.target_price, record.alert_diff_pct);
        const diffColor = diff
          ? diff.diffPct > 0
            ? '#cf1322'
            : diff.diffPct < 0
              ? '#3f8600'
              : undefined
          : undefined;
        return (
          <Space direction="vertical" size={0} style={{ width: '100%' }} align="end">
            {diff ? (
              <Typography.Text
                strong={diff.alerted}
                style={{
                  color: diffColor,
                  background: diff.alerted ? '#fffbe6' : undefined,
                  padding: diff.alerted ? '0 4px' : undefined,
                  borderRadius: 4,
                  fontSize: 12,
                }}
              >
                {`${diff.diffPct > 0 ? '+' : ''}${diff.diffPct.toFixed(2)}% (${diff.diff > 0 ? '+' : ''}${diff.diff.toFixed(2)})`}
              </Typography.Text>
            ) : (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>—</Typography.Text>
            )}
            <Space size={2} style={{ fontSize: 11 }}>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>阈值</Typography.Text>
              <EditableTargetCell
                value={record.alert_diff_pct}
                precision={2}
                suffix="%"
                placeholder="设置"
                min={0}
                max={100}
                onSave={(next) => handleSaveTargets(record, { alert_diff_pct: next })}
              />
            </Space>
          </Space>
        );
      },
    },
    {
      title: '分组 / 标签',
      key: 'group',
      width: 200,
      render: (_, record) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Select
            size="small"
            style={{ width: 160 }}
            value={record.group_id ?? UNGROUPED_KEY}
            onChange={(val) =>
              record.id != null &&
              handleMoveStock(record.id, val === UNGROUPED_KEY ? null : (val as number))
            }
            options={[
              ...groups.map((g) => ({ value: g.id, label: g.name })),
              { value: UNGROUPED_KEY, label: '未分组' },
            ]}
          />
          {renderTagToggleRow(record)}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => navigate(`/stock/${record.code}`)}>
            分析
          </Button>
          <Popconfirm
            title="从自选股移除？"
            onConfirm={() => record.id != null && handleDelete(record.id)}
          >
            <Button type="link" size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const handleTableChange = (
    _pagination: TablePaginationConfig,
    _filters: Record<string, FilterValue | null>,
    sorter: SorterResult<StockInfo> | SorterResult<StockInfo>[],
  ) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    if (s && s.order && s.columnKey) {
      setSortField(String(s.columnKey));
      setSortOrder(s.order);
    } else {
      setSortField(null);
      setSortOrder(null);
    }
  };

  return (
    <div style={{ minWidth: 0, maxWidth: '100%', overflowX: 'hidden' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: isMobile ? 8 : 12,
          flexWrap: 'wrap',
        }}
      >
        <Typography.Title level={4} style={{ margin: 0 }}>
          自选股 · {filterLabel}
        </Typography.Title>
        <div style={{ flex: 1 }} />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setAddTargetGroup(typeof filter === 'number' ? (filter as number) : null);
            setModalOpen(true);
          }}
        >
          添加股票
        </Button>
      </div>

      <Tabs
        activeKey={viewMode}
        onChange={(k) => setViewMode(k as 'list' | 'news')}
        items={[
          { key: 'list', label: '股票列表' },
          { key: 'news', label: '重要资讯' },
        ]}
        size="middle"
        type="card"
        style={{ marginBottom: 8 }}
      />

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          borderBottom: '1px solid #f0f0f0',
          marginBottom: isMobile ? 8 : 12,
          minWidth: 0,
          maxWidth: '100%',
        }}
      >
        <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
          <Tabs
            activeKey={String(filter)}
            onChange={handleTabChange}
            items={tabItems}
            renderTabBar={renderTabBar}
            style={{ marginBottom: -1 }}
            size="small"
            moreIcon={null}
            tabBarGutter={isMobile ? 8 : undefined}
          />
        </div>
        <Tooltip title="管理分组">
          <Button
            type="text"
            size="small"
            icon={<AppstoreOutlined />}
            onClick={() => setGroupMgrOpen(true)}
            style={{ marginRight: isMobile ? 0 : 8, flexShrink: 0 }}
          />
        </Tooltip>
      </div>

      {viewMode === 'news' ? (
        <WatchlistNewsCard
          codes={sortedData.map((s) => s.code)}
          scopeLabel={filterLabel}
        />
      ) : isMobile ? (
        renderMobileList()
      ) : (
        sortedData.length === 0 && !loading ? (
          <Empty description="该分组暂无股票" />
        ) : (
          <Table
            rowKey={(r) => String(r.id ?? r.code)}
            columns={desktopColumns}
            dataSource={sortedData}
            loading={loading}
            size="middle"
            pagination={{ pageSize: 20 }}
            scroll={{ x: 1300 }}
            onChange={handleTableChange}
          />
        )
      )}

      <Modal
        title="添加股票"
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          setKeyword('');
          setSearchResults([]);
        }}
        footer={null}
        destroyOnHidden
      >
        <div style={{ marginBottom: 12 }}>
          <Typography.Text type="secondary">加入分组：</Typography.Text>
          <Select
            style={{ width: 200, marginLeft: 8 }}
            value={addTargetGroup ?? UNGROUPED_KEY}
            onChange={(val) =>
              setAddTargetGroup(val === UNGROUPED_KEY ? null : (val as number))
            }
            options={[
              ...groups.map((g) => ({ value: g.id, label: g.name })),
              { value: UNGROUPED_KEY, label: '未分组' },
            ]}
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <StockSearchInput
            value={keyword}
            onChange={setKeyword}
            onResultsChange={setSearchResults}
            onSelect={(stock) => handleAdd(stock)}
            placeholder="输入代码 / 名称 / 拼音，如 000001 / 平安 / pa"
          />
        </div>

        <List
          size="small"
          bordered
          dataSource={searchResults}
          locale={{ emptyText: '在上方搜索股票' }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Button type="link" key="add" onClick={() => handleAdd(item)}>
                  加入
                </Button>,
              ]}
            >
              <Space>
                <Tag>{item.code}</Tag>
                <span>{item.name}</span>
                {item.market && (
                  <Typography.Text type="secondary">[{item.market}]</Typography.Text>
                )}
              </Space>
            </List.Item>
          )}
        />
      </Modal>

      <Modal
        title={<Space><AppstoreOutlined />分组管理</Space>}
        open={groupMgrOpen}
        onCancel={() => {
          setGroupMgrOpen(false);
          setRenamingId(null);
          setRenameValue('');
        }}
        footer={null}
        destroyOnHidden
        width={460}
      >
        <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
          <Input
            placeholder="新建分组名称"
            value={newGroupName}
            onChange={(e) => setNewGroupName(e.target.value)}
            onPressEnter={handleCreateGroup}
            maxLength={50}
          />
          <Button
            type="primary"
            loading={creatingGroup}
            onClick={handleCreateGroup}
            disabled={!newGroupName.trim()}
            icon={<PlusOutlined />}
          >
            新建
          </Button>
        </Space.Compact>

        {groups.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无分组" />
        ) : (
          <div style={{ maxHeight: 360, overflowY: 'auto' }}>
          <List
            size="small"
            bordered
            dataSource={groups}
            renderItem={(g, index) => (
              <List.Item
                draggable
                onDragStart={(e) => {
                  dragIndexRef.current = index;
                  e.dataTransfer.effectAllowed = 'move';
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = 'move';
                  if (dragOverIndex !== index) setDragOverIndex(index);
                }}
                onDragLeave={() => {
                  if (dragOverIndex === index) setDragOverIndex(null);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  handleGroupDrop(index);
                }}
                style={{
                  cursor: 'move',
                  background: dragOverIndex === index ? '#e6f4ff' : undefined,
                }}
                actions={[
                  renamingId === g.id ? null : (
                    <Button
                      key="edit"
                      type="link"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => {
                        setRenamingId(g.id);
                        setRenameValue(g.name);
                      }}
                    />
                  ),
                  <Popconfirm
                    key="del"
                    title={`删除分组「${g.name}」？组内股票将变为未分组`}
                    onConfirm={() => handleDeleteGroup(g.id)}
                  >
                    <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>,
                ].filter(Boolean) as React.ReactNode[]}
              >
                {renamingId === g.id ? (
                  <Input
                    size="small"
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onPressEnter={() => handleRenameGroup(g.id)}
                    onBlur={() => handleRenameGroup(g.id)}
                    style={{ width: 200 }}
                  />
                ) : (
                  <Space>
                    <HolderOutlined style={{ color: '#bfbfbf' }} />
                    <span>{g.name}</span>
                    <Tag>{g.count ?? 0}</Tag>
                  </Space>
                )}
              </List.Item>
            )}
          />
          </div>
        )}
      </Modal>
    </div>
  );
}
