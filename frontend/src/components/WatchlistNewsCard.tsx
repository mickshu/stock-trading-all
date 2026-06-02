import { useEffect, useMemo, useRef, useState } from 'react';
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
  Input,
  Alert,
  message,
} from 'antd';
import {
  ReloadOutlined,
  FireOutlined,
  LinkOutlined,
  RobotOutlined,
  EditOutlined,
  SaveOutlined,
  RollbackOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  fetchWatchlistNews,
  fetchNewsSettings,
  saveNewsSettings,
  resetNewsPrompt,
  fetchAiDigest,
  type NewsItem,
  type NewsTimeRange,
  type AiDigestResponse,
} from '../api/news';
import MarkdownView from './MarkdownView';

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

type NewsMode = 'aggregate' | 'ai';

export default function WatchlistNewsCard({ codes, scopeLabel }: Props) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<NewsMode>('aggregate');
  const [timeRange, setTimeRange] = useState<NewsTimeRange>('today');
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [stale, setStale] = useState(false);
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // AI 检索：当前会话使用的 prompt（可能与已存默认值不同）
  const [aiPrompt, setAiPrompt] = useState('');
  const [savedPrompt, setSavedPrompt] = useState('');
  const [defaultPrompt, setDefaultPrompt] = useState('');
  const [promptEditing, setPromptEditing] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<AiDigestResponse | null>(null);

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
      setStale(Boolean(resp.stale));
      setRefreshedAt(resp.refreshed_at ?? null);
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
      // 后端已 BackgroundTasks 异步刷新；6 秒后回拉一次取新结果。
      if (resp.stale) {
        pollTimerRef.current = setTimeout(() => {
          pollTimerRef.current = null;
          reload();
        }, 6000);
      }
    } catch {
      message.error('加载资讯失败，请稍后再试');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (mode !== 'aggregate') return;
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeRange, codesKey, mode]);

  // 切走聚合模式 / 卸载时清理轮询定时器，避免重复触发
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  // 切到 AI 模式时按需加载 prompt 配置
  useEffect(() => {
    if (mode !== 'ai' || savedPrompt) return;
    fetchNewsSettings()
      .then((s) => {
        setSavedPrompt(s.prompt);
        setDefaultPrompt(s.default_prompt);
        setAiPrompt(s.prompt);
      })
      .catch(() => message.error('加载 AI 资讯配置失败'));
  }, [mode, savedPrompt]);

  const runAiDigest = async () => {
    const prompt = (aiPrompt || savedPrompt).trim();
    if (!prompt) {
      message.warning('提示词不能为空');
      return;
    }
    setAiLoading(true);
    try {
      const resp = await fetchAiDigest({ codes, prompt });
      setAiResult(resp);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || 'AI 资讯检索失败，请检查 AI 配置或稍后重试');
    } finally {
      setAiLoading(false);
    }
  };

  const handleSavePrompt = async () => {
    const text = aiPrompt.trim();
    if (!text) {
      message.warning('提示词不能为空');
      return;
    }
    setPromptSaving(true);
    try {
      const s = await saveNewsSettings({ prompt: text });
      setSavedPrompt(s.prompt);
      setAiPrompt(s.prompt);
      setPromptEditing(false);
      message.success('已保存为默认提示词');
    } catch {
      message.error('保存失败');
    } finally {
      setPromptSaving(false);
    }
  };

  const handleResetPrompt = async () => {
    setPromptSaving(true);
    try {
      const s = await resetNewsPrompt();
      setSavedPrompt(s.prompt);
      setAiPrompt(s.prompt);
      message.success('已恢复默认提示词');
    } catch {
      message.error('恢复失败');
    } finally {
      setPromptSaving(false);
    }
  };

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

  const headerHint =
    mode === 'aggregate'
      ? '多源聚合（财联社 / 东方财富 / 同花顺 / 新浪），按热度排序'
      : '基于「设置 → 资讯」的提示词与 AI 配置，让大模型联网检索并生成 markdown 简报';

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
          {headerHint}
        </Typography.Text>
        <div style={{ flex: 1 }} />
        {mode === 'aggregate' && (
          <>
            {refreshedAt && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {stale ? '更新中…' : '更新于'} {formatPublishedAt(refreshedAt)}
              </Typography.Text>
            )}
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={reload}
              loading={loading || stale}
            >
              刷新
            </Button>
          </>
        )}
      </div>

      <Tabs
        size="small"
        activeKey={mode}
        onChange={(k) => setMode(k as NewsMode)}
        items={[
          { key: 'aggregate', label: '多源聚合' },
          { key: 'ai', label: <span><RobotOutlined /> AI 智能检索</span> },
        ]}
        style={{ marginBottom: 4 }}
      />

      {mode === 'aggregate' ? (
        <>
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
        </>
      ) : (
        <div>
          <div style={{ marginBottom: 8 }}>
            <Space size={6} wrap>
              <Button
                type="primary"
                size="small"
                icon={<RobotOutlined />}
                onClick={runAiDigest}
                loading={aiLoading}
                disabled={codes.length === 0}
              >
                {aiResult ? '重新检索' : '开始 AI 检索'}
              </Button>
              <Button
                size="small"
                icon={<EditOutlined />}
                onClick={() => setPromptEditing((v) => !v)}
              >
                {promptEditing ? '收起提示词' : '编辑提示词'}
              </Button>
              {aiResult && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  模型：{aiResult.model} · 生成于 {aiResult.generated_at}
                </Typography.Text>
              )}
            </Space>
          </div>

          {promptEditing && (
            <div style={{ marginBottom: 12 }}>
              <Input.TextArea
                value={aiPrompt}
                onChange={(e) => setAiPrompt(e.target.value)}
                autoSize={{ minRows: 4, maxRows: 12 }}
                placeholder="自定义资讯检索提示词…"
              />
              <Space size={6} style={{ marginTop: 6 }} wrap>
                <Button
                  size="small"
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={promptSaving}
                  onClick={handleSavePrompt}
                  disabled={aiPrompt.trim() === savedPrompt.trim()}
                >
                  保存为默认
                </Button>
                <Button
                  size="small"
                  icon={<RollbackOutlined />}
                  loading={promptSaving}
                  onClick={handleResetPrompt}
                  disabled={savedPrompt.trim() === defaultPrompt.trim()}
                >
                  恢复默认
                </Button>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  当前默认：{savedPrompt === defaultPrompt ? '内置默认值' : '自定义'}
                </Typography.Text>
              </Space>
            </div>
          )}

          {codes.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="当前分组无自选股，先添加几只"
            />
          ) : aiLoading ? (
            <div style={{ padding: 32, textAlign: 'center' }}>
              <Spin tip="AI 联网检索中，可能需要 30 秒至几分钟…" />
            </div>
          ) : aiResult ? (
            <div>
              <MarkdownView content={aiResult.content} />
              {aiResult.sources.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    引用来源：
                  </Typography.Text>
                  <Space size={4} wrap style={{ marginTop: 4 }}>
                    {aiResult.sources.map((u) => (
                      <a
                        key={u}
                        href={u}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ fontSize: 12 }}
                      >
                        <LinkOutlined /> {u.length > 60 ? u.slice(0, 60) + '…' : u}
                      </a>
                    ))}
                  </Space>
                </div>
              )}
            </div>
          ) : (
            <Alert
              type="info"
              showIcon
              message="点击「开始 AI 检索」让大模型联网生成自选股资讯简报"
              description="提示词与默认数据源可在「设置 → 资讯」中调整。"
            />
          )}
        </div>
      )}
    </div>
  );
}
