import { useEffect, useMemo, useState } from 'react';
import {
  Tabs,
  List,
  Tag,
  Space,
  Typography,
  Empty,
  Spin,
  Button,
  Tooltip,
  message,
} from 'antd';
import { ReloadOutlined, FireOutlined, LinkOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { fetchWatchlistNews, type NewsItem, type NewsTimeRange } from '../api/news';

interface Props {
  /** 当前筛选范围内的股票代码池；为空表示「全部自选股」由后端兜底。 */
  codes: string[];
  /** 用于卡片标题展示的范围说明，如「全部 / 持有 / 分组X」。 */
  scopeLabel: string;
}

const SOURCE_COLORS: Record<string, string> = {
  财联社: 'red',
  东方财富: 'blue',
  东财快讯: 'geekblue',
  同花顺: 'purple',
  新浪: 'orange',
};

const TIME_TABS: { key: NewsTimeRange; label: string }[] = [
  { key: 'today', label: '今日' },
  { key: 'week', label: '本周' },
  { key: 'all', label: '全部' },
];

function formatPublishedAt(iso: string): string {
  // 后端返回 ISO 带 +08:00；本地时区显示相对时间或 MM-DD HH:mm
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin}分钟前`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}小时前`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay <= 3) return `${diffDay}天前`;
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${mm}-${dd} ${hh}:${mi}`;
}

export default function WatchlistNewsCard({ codes, scopeLabel }: Props) {
  const navigate = useNavigate();
  const [timeRange, setTimeRange] = useState<NewsTimeRange>('today');
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);

  // codes 数组稳定化，避免每次新引用都触发 effect
  const codesKey = useMemo(() => [...codes].sort().join(','), [codes]);

  const reload = async () => {
    setLoading(true);
    try {
      const resp = await fetchWatchlistNews({
        timeRange,
        codes,
        limit: 80,
      });
      setItems(resp.items);
    } catch {
      message.error('加载资讯失败，请稍后再试');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange, codesKey]);

  const renderItem = (item: NewsItem) => {
    const isHot = item.hot_score >= 6;
    return (
      <List.Item
        key={item.id}
        style={{ alignItems: 'flex-start', padding: '12px 8px' }}
      >
        <div style={{ width: '100%' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            {isHot && (
              <Tooltip title={`热度 ${item.hot_score}`}>
                <Tag color="red" style={{ marginInlineEnd: 0 }} icon={<FireOutlined />}>
                  热
                </Tag>
              </Tooltip>
            )}
            <Typography.Text
              strong
              style={{ fontSize: 14, lineHeight: 1.4, flex: 1, minWidth: 0 }}
            >
              {item.url ? (
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  {item.title}
                  <LinkOutlined style={{ marginLeft: 4, fontSize: 11, color: '#8c8c8c' }} />
                </a>
              ) : (
                item.title
              )}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
              {formatPublishedAt(item.published_at)}
            </Typography.Text>
          </div>

          {item.summary && (
            <Typography.Paragraph
              type="secondary"
              ellipsis={{ rows: 2, expandable: false }}
              style={{ marginTop: 6, marginBottom: 6, fontSize: 12 }}
            >
              {item.summary}
            </Typography.Paragraph>
          )}

          <Space size={4} wrap style={{ marginTop: 4 }}>
            {item.sources.map((src) => (
              <Tag
                key={src}
                color={SOURCE_COLORS[src] || 'default'}
                style={{ marginInlineEnd: 0, fontSize: 11 }}
              >
                {src}
              </Tag>
            ))}
            {item.related_codes.map((code, idx) => {
              const name = item.related_names[idx];
              return (
                <Tag
                  key={code}
                  color="cyan"
                  style={{ marginInlineEnd: 0, cursor: 'pointer', fontSize: 11 }}
                  onClick={() => navigate(`/stock/${code}`)}
                >
                  {name ? `${name} ${code}` : code}
                </Tag>
              );
            })}
          </Space>
        </div>
      </List.Item>
    );
  };

  return (
    <div
      style={{
        background: '#fff',
        borderRadius: 8,
        padding: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginBottom: 8,
          flexWrap: 'wrap',
        }}
      >
        <Typography.Text strong style={{ fontSize: 14 }}>
          重要资讯 · {scopeLabel}
        </Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          多源聚合（财联社 / 东方财富 / 同花顺 / 新浪），按热度排序
        </Typography.Text>
        <div style={{ flex: 1 }} />
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={reload}
          loading={loading}
        >
          刷新
        </Button>
      </div>

      <Tabs
        size="small"
        activeKey={timeRange}
        onChange={(k) => setTimeRange(k as NewsTimeRange)}
        items={TIME_TABS.map((t) => ({ key: t.key, label: t.label }))}
        style={{ marginBottom: 4 }}
      />

      {loading && items.length === 0 ? (
        <div style={{ padding: 32, textAlign: 'center' }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            codes.length === 0
              ? '当前分组无自选股，先添加几只'
              : '该时间窗口暂无相关资讯'
          }
        />
      ) : (
        <List
          dataSource={items}
          renderItem={renderItem}
          split
          loading={loading && items.length > 0}
        />
      )}
    </div>
  );
}
