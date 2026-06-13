import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  DatePicker,
  Empty,
  List,
  Modal,
  Popconfirm,
  Slider,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  DeploymentUnitOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import MarkdownView from './MarkdownView';
import SpeechButton from './SpeechButton';
import {
  createTATask,
  deleteTATask,
  getTATask,
  listTATasks,
  type TATask,
  type TATaskStatus,
} from '../api/tradingAgents';

const { Text } = Typography;

interface Props {
  code: string;
  stockName?: string;
}

function StatusBadge({ status }: { status: TATaskStatus }) {
  const map: Record<TATaskStatus, { color: 'default' | 'processing' | 'success' | 'error' | 'warning'; text: string }> = {
    pending: { color: 'warning', text: '排队中' },
    running: { color: 'processing', text: '运行中' },
    success: { color: 'success', text: '已完成' },
    failed: { color: 'error', text: '失败' },
  };
  const m = map[status] || { color: 'default' as const, text: status };
  return <Badge status={m.color} text={m.text} />;
}

function DecisionTag({ decision }: { decision: string }) {
  const upper = (decision || '').toUpperCase();
  let color = 'default';
  let label = decision || '—';
  if (upper.includes('BUY')) { color = 'green'; label = 'BUY'; }
  else if (upper.includes('SELL')) { color = 'red'; label = 'SELL'; }
  else if (upper.includes('HOLD')) { color = 'gold'; label = 'HOLD'; }
  return <Tag color={color} style={{ fontWeight: 600 }}>{label}</Tag>;
}

function formatDuration(sec: number | null): string {
  if (sec == null) return '-';
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec - m * 60);
  return `${m}m${s}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return '-';
  try { return dayjs(iso).format('MM-DD HH:mm:ss'); } catch { return iso; }
}

export default function TradingAgentsPanel({ code, stockName }: Props) {
  const [tasks, setTasks] = useState<TATask[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [tradeDate, setTradeDate] = useState(dayjs());
  const [depth, setDepth] = useState(1);
  const [onlineTools, setOnlineTools] = useState(true);
  const [viewTask, setViewTask] = useState<TATask | null>(null);
  const [viewMd, setViewMd] = useState('');
  const [viewLoading, setViewLoading] = useState(false);

  const ticker = code.toUpperCase();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const items = await listTATasks(50, ticker);
      setTasks(items);
    } catch { /* keep last list */ }
    finally { setLoading(false); }
  }, [ticker]);

  useEffect(() => { refresh(); }, [refresh]);

  const hasActive = useMemo(
    () => tasks.some((t) => t.status === 'pending' || t.status === 'running'),
    [tasks],
  );

  useEffect(() => {
    if (!hasActive) return;
    const id = window.setInterval(refresh, 4000);
    return () => window.clearInterval(id);
  }, [hasActive, refresh]);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const t = await createTATask({
        ticker,
        stock_name: stockName || '',
        trade_date: tradeDate.format('YYYY-MM-DD'),
        depth,
        online_tools: onlineTools,
      });
      message.success('已加入多智能体分析队列');
      setTasks((prev) => [t, ...prev.filter((x) => x.id !== t.id)]);
    } catch (e: unknown) {
      let msg = e instanceof Error ? e.message : String(e);
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (detail) msg = typeof detail === 'string' ? detail : JSON.stringify(detail);
      message.error(`提交失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  const openView = async (task: TATask) => {
    setViewTask(task);
    setViewMd('');
    if (task.status !== 'success') return;
    setViewLoading(true);
    try {
      const full = await getTATask(task.id, true);
      setViewMd(full.report_md || '');
    } catch { setViewMd('（加载报告内容失败）'); }
    finally { setViewLoading(false); }
  };

  const onDelete = async (task: TATask) => {
    try {
      await deleteTATask(task.id);
      message.success('已删除');
      setTasks((prev) => prev.filter((t) => t.id !== task.id));
    } catch { message.error('删除失败'); }
  };

  return (
    <Card
      size="small"
      style={{ marginTop: 16 }}
      title={
        <Space size={6}>
          <DeploymentUnitOutlined />
          <span>多智能体分析</span>
          {hasActive && <Badge status="processing" />}
        </Space>
      }
      extra={
        <Button size="small" icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
          刷新
        </Button>
      }
    >
      <Space wrap style={{ marginBottom: 12 }}>
        <Space size={4}>
          <Text type="secondary">日期</Text>
          <DatePicker
            size="small"
            value={tradeDate}
            onChange={(d) => d && setTradeDate(d)}
          />
        </Space>
        <Space size={4}>
          <Text type="secondary">轮数</Text>
          <Slider
            min={1}
            max={3}
            value={depth}
            onChange={setDepth}
            marks={{ 1: '快', 2: '中', 3: '深' }}
            style={{ width: 120 }}
          />
        </Space>
        <Space size={4}>
          <Text type="secondary">在线数据</Text>
          <Switch size="small" checked={onlineTools} onChange={setOnlineTools} />
        </Space>
        <Button
          type="primary"
          size="small"
          icon={<PlayCircleOutlined />}
          loading={submitting}
          onClick={handleSubmit}
        >
          发起分析
        </Button>
      </Space>

      <Text type="secondary" style={{ display: 'block', fontSize: 12, marginBottom: 8 }}>
        基于 LangGraph 多智能体框架：市场/舆情/新闻/基本面分析 → 多空辩论 → 风险评估 → 决策。任务异步执行，离开页面也会继续。
      </Text>

      {tasks.length === 0 && !loading ? (
        <Empty description="暂无分析任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Spin spinning={loading}>
          <List
            size="small"
            dataSource={tasks}
            renderItem={(t) => (
              <List.Item
                style={{ padding: '8px 0' }}
                actions={[
                  <Button
                    key="view"
                    type="link"
                    size="small"
                    icon={<EyeOutlined />}
                    disabled={t.status !== 'success'}
                    onClick={() => openView(t)}
                  >
                    查看
                  </Button>,
                  <SpeechButton
                    key="speech"
                    disabled={t.status !== 'success'}
                    getText={() => getTATask(t.id, true).then((f) => f.report_md || '')}
                  />,
                  t.report_url ? (
                    <Tooltip key="dl" title="下载报告">
                      <Button
                        type="link"
                        size="small"
                        icon={<DownloadOutlined />}
                        href={t.report_url}
                        target="_blank"
                        download={t.report_filename?.split('/').pop()}
                      />
                    </Tooltip>
                  ) : null,
                  <Popconfirm key="del" title="确认删除？" onConfirm={() => onDelete(t)}>
                    <Button type="link" size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>,
                ].filter(Boolean) as React.ReactNode[]}
              >
                <Space size={8} wrap>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t.trade_date}</Text>
                  <StatusBadge status={t.status} />
                  <DecisionTag decision={t.decision} />
                  {t.analysis_tool === 'cli' && <Tag color="purple">CLI</Tag>}
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    轮数{t.depth} · {formatDuration(t.duration_sec)}
                  </Text>
                  {t.finished_at && (
                    <Text type="secondary" style={{ fontSize: 12 }}>{formatTime(t.finished_at)}</Text>
                  )}
                  {t.status === 'failed' && t.error && (
                    <Tooltip title={t.error}><Tag color="red">错误详情</Tag></Tooltip>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </Spin>
      )}

      <Modal
        open={!!viewTask}
        onCancel={() => setViewTask(null)}
        footer={
          viewTask?.report_url ? (
            <Space>
              <Button
                icon={<DownloadOutlined />}
                href={viewTask.report_url}
                target="_blank"
                download={viewTask.report_filename?.split('/').pop()}
              >
                下载 .md
              </Button>
              <Button onClick={() => setViewTask(null)}>关闭</Button>
            </Space>
          ) : (
            <Button onClick={() => setViewTask(null)}>关闭</Button>
          )
        }
        width={900}
        title={
          viewTask && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingRight: 24 }}>
              <Space size={8} wrap>
                <span>
                  {viewTask.stock_name || viewTask.ticker} ({viewTask.ticker}) · {viewTask.trade_date}
                </span>
                <DecisionTag decision={viewTask.decision} />
              </Space>
              {viewMd && <SpeechButton text={viewMd} />}
            </div>
          )
        }
        destroyOnHidden
      >
        {viewLoading ? (
          <div style={{ padding: 24, textAlign: 'center' }}>加载中…</div>
        ) : viewMd ? (
          <MarkdownView content={viewMd} />
        ) : (
          <Empty description="尚无内容（任务可能未完成）" />
        )}
      </Modal>
    </Card>
  );
}
