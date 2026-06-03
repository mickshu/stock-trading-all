import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Card,
  Form,
  DatePicker,
  Slider,
  Switch,
  Button,
  Space,
  Alert,
  Tag,
  Empty,
  Typography,
  message,
  Row,
  Col,
  Tabs,
  Table,
  Modal,
  Popconfirm,
  Tooltip,
  Badge,
  Select,
} from 'antd';
import {
  DeploymentUnitOutlined,
  PlayCircleOutlined,
  DownloadOutlined,
  FileMarkdownOutlined,
  ReloadOutlined,
  DeleteOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import type { ColumnsType } from 'antd/es/table';
import MarkdownView from '../components/MarkdownView';
import StockSearchInput from '../components/StockSearchInput';
import {
  fetchTAHealth,
  createTATask,
  listTATasks,
  getTATask,
  deleteTATask,
  type TAHealth,
  type TATask,
  type TATaskStatus,
} from '../api/tradingAgents';
import { probeAIAgents, type AIAgentInfo } from '../api/aiAgent';

// 「模型」下拉常用选项；用户也可以直接在 Select 里输入自定义模型名。
const MODEL_OPTIONS = [
  'deepseek-v4-pro',
  'deepseek-chat',
  'deepseek-reasoner',
  'gpt-4o',
  'gpt-4o-mini',
  'claude-opus-4-7',
  'claude-sonnet-4-6',
  'claude-haiku-4-5',
];

const { Title, Text, Paragraph } = Typography;

interface FormValues {
  ticker: string;
  trade_date: Dayjs;
  depth: number;
  online_tools: boolean;
  model_override?: string;
  provider_override?: string;
}

function DecisionTag({ decision }: { decision: string }) {
  const upper = (decision || '').toUpperCase();
  let color = 'default';
  let label = decision || '—';
  if (upper.includes('BUY')) {
    color = 'green';
    label = 'BUY';
  } else if (upper.includes('SELL')) {
    color = 'red';
    label = 'SELL';
  } else if (upper.includes('HOLD')) {
    color = 'gold';
    label = 'HOLD';
  }
  return <Tag color={color} style={{ fontWeight: 600 }}>{label}</Tag>;
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

function formatDuration(sec: number | null): string {
  if (sec == null) return '-';
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec - m * 60);
  return `${m}m${s}s`;
}

function formatTime(iso: string | null): string {
  if (!iso) return '-';
  try {
    return dayjs(iso).format('MM-DD HH:mm:ss');
  } catch {
    return iso;
  }
}

export default function TradingAgentsPage() {
  const [form] = Form.useForm<FormValues>();
  const [health, setHealth] = useState<TAHealth | null>(null);
  const [tasks, setTasks] = useState<TATask[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<'new' | 'list'>('new');
  const [viewTask, setViewTask] = useState<TATask | null>(null);
  const [viewMd, setViewMd] = useState<string>('');
  const [viewLoading, setViewLoading] = useState(false);
  const [agents, setAgents] = useState<AIAgentInfo[]>([]);
  const stockNameRef = useRef<string>('');

  // 模型 / CLI 二选一：watch 两个字段，一个被选中时禁用另一个。
  const watchModel = Form.useWatch('model_override', form);
  const watchProvider = Form.useWatch('provider_override', form);

  useEffect(() => {
    probeAIAgents()
      .then(setAgents)
      .catch(() => setAgents([]));
  }, []);

  useEffect(() => {
    fetchTAHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const refresh = useCallback(async () => {
    setLoadingList(true);
    try {
      const items = await listTATasks();
      setTasks(items);
    } catch {
      // ignore — keep last list
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // 轮询：只要有 pending/running 任务，就每 4 秒刷一次
  const hasActive = useMemo(
    () => tasks.some((t) => t.status === 'pending' || t.status === 'running'),
    [tasks],
  );
  useEffect(() => {
    if (!hasActive) return;
    const id = window.setInterval(() => {
      refresh();
    }, 4000);
    return () => window.clearInterval(id);
  }, [hasActive, refresh]);

  const onFinish = async (values: FormValues) => {
    setSubmitting(true);
    try {
      const t = await createTATask({
        ticker: values.ticker.trim(),
        stock_name: stockNameRef.current || '',
        trade_date: values.trade_date.format('YYYY-MM-DD'),
        depth: values.depth,
        online_tools: values.online_tools,
        model_override: (values.model_override || '').trim(),
        provider_override: (values.provider_override || '').trim(),
      });
      message.success('已加入队列，可在「任务记录」查看进度');
      setActiveTab('list');
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
    } catch {
      setViewMd('（加载报告内容失败）');
    } finally {
      setViewLoading(false);
    }
  };

  const onDelete = async (task: TATask) => {
    try {
      await deleteTATask(task.id);
      message.success('已删除');
      setTasks((prev) => prev.filter((t) => t.id !== task.id));
    } catch {
      message.error('删除失败');
    }
  };

  const columns: ColumnsType<TATask> = [
    {
      title: '股票',
      key: 'stock',
      width: 160,
      render: (_, t) => (
        <Space size={4} direction="vertical">
          <span><Tag color="blue">{t.ticker}</Tag>{t.stock_name && <Text>{t.stock_name}</Text>}</span>
          <Text type="secondary" style={{ fontSize: 12 }}>{t.trade_date}</Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      render: (s: TATaskStatus) => <StatusBadge status={s} />,
    },
    {
      title: '决策',
      dataIndex: 'decision',
      key: 'decision',
      width: 90,
      render: (d: string) => <DecisionTag decision={d} />,
    },
    {
      title: '参数',
      key: 'params',
      width: 140,
      render: (_, t) => (
        <Space size={4} direction="vertical">
          <Text style={{ fontSize: 12 }}>轮数 {t.depth}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{t.online_tools ? '在线数据' : '离线'}</Text>
        </Space>
      ),
    },
    {
      title: '耗时',
      dataIndex: 'duration_sec',
      key: 'duration_sec',
      width: 80,
      render: (v) => <Text style={{ fontSize: 12 }}>{formatDuration(v)}</Text>,
    },
    {
      title: '完成时间',
      dataIndex: 'finished_at',
      key: 'finished_at',
      width: 130,
      render: (v) => <Text style={{ fontSize: 12 }}>{formatTime(v)}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 260,
      render: (_, t) => (
        <Space size={4} wrap>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            disabled={t.status !== 'success'}
            onClick={() => openView(t)}
          >
            查看
          </Button>
          <Tooltip title={t.report_url || '尚未生成'}>
            <Button
              type="link"
              size="small"
              icon={<DownloadOutlined />}
              disabled={!t.report_url}
              href={t.report_url || undefined}
              target="_blank"
              download={t.report_filename ? t.report_filename.split('/').pop() : undefined}
            >
              下载 .md
            </Button>
          </Tooltip>
          <Popconfirm title="确认删除该任务？" onConfirm={() => onDelete(t)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
          {t.status === 'failed' && t.error && (
            <Tooltip title={t.error}>
              <Tag color="red">错误详情</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>
        <DeploymentUnitOutlined /> TradingAgents 多智能体分析
      </Title>
      <Paragraph type="secondary">
        基于 LangGraph 编排的多智能体框架：市场 / 舆情 / 新闻 / 基本面 4 位分析师 →
        多空研究员辩论 → 风险评估 → 最终决策。任务异步排队执行，离开页面也会继续。
      </Paragraph>

      {health && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            <Space size="middle" wrap>
              <span><Text strong>Provider:</Text> {health.provider}</span>
              <span><Text strong>深度模型:</Text> {health.deep_think_llm}</span>
              <span><Text strong>数据源:</Text> {health.data_source}</span>
              <Text type="secondary">配置可在「设置 → AI 配置」修改</Text>
            </Space>
          }
        />
      )}

      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as 'new' | 'list')}
        items={[
          {
            key: 'new',
            label: '发起分析',
            children: (
              <Card size="small">
                <Form
                  form={form}
                  layout="inline"
                  initialValues={{
                    ticker: '600000',
                    trade_date: dayjs(),
                    depth: 1,
                    online_tools: true,
                    model_override: '',
                    provider_override: '',
                  }}
                  onFinish={onFinish}
                >
                  <Form.Item name="ticker" label="股票代码" rules={[{ required: true }]}>
                    <StockSearchInput
                      style={{ width: 260 }}
                      placeholder="输入代码 / 名称 / 拼音，如 600000 / 浦发 / pf"
                      onSelect={(s) => {
                        stockNameRef.current = s.name || '';
                        form.setFieldValue('ticker', s.code);
                      }}
                      onChange={() => {
                        // 用户手动改输入即清掉缓存的中文名
                        stockNameRef.current = '';
                      }}
                    />
                  </Form.Item>
                  <Form.Item name="trade_date" label="分析日期" rules={[{ required: true }]}>
                    <DatePicker />
                  </Form.Item>
                  <Form.Item name="depth" label="辩论轮数" style={{ minWidth: 200 }}>
                    <Slider min={1} max={3} marks={{ 1: '快', 2: '中', 3: '深' }} />
                  </Form.Item>
                  <Form.Item
                    name="model_override"
                    label="模型"
                    tooltip="覆盖「设置」里的深度/快速思考模型；与「CLI 分析工具」二选一"
                  >
                    <Select
                      style={{ width: 200 }}
                      allowClear
                      showSearch
                      disabled={!!watchProvider}
                      placeholder={watchProvider ? '已选 CLI（互斥）' : '默认（按 AI 配置）'}
                      options={MODEL_OPTIONS.map((m) => ({ value: m, label: m }))}
                      onChange={(v) => {
                        if (v) form.setFieldValue('provider_override', undefined);
                      }}
                    />
                  </Form.Item>
                  <Form.Item
                    name="provider_override"
                    label="CLI 分析工具"
                    tooltip="选择本地已安装的 AI CLI（替代全局 provider）；与「模型」二选一"
                  >
                    <Select
                      style={{ width: 180 }}
                      allowClear
                      disabled={!!watchModel}
                      placeholder={watchModel ? '已选模型（互斥）' : '默认（按 AI 配置）'}
                      options={agents.map((a) => ({
                        value: a.name,
                        label: `${a.label}${a.version ? ` · ${a.version}` : ''}`,
                      }))}
                      notFoundContent={<span style={{ color: '#999' }}>未检测到本地 CLI</span>}
                      onChange={(v) => {
                        if (v) form.setFieldValue('model_override', undefined);
                      }}
                    />
                  </Form.Item>
                  <Form.Item name="online_tools" label="在线数据" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <Form.Item>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={submitting}
                      icon={<PlayCircleOutlined />}
                    >
                      加入队列
                    </Button>
                  </Form.Item>
                </Form>
                <Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0 }}>
                  报告以 <Text code>日期_公司名.md</Text> 命名，保存在
                  <Text code>data/reports/trading-agents/</Text>，可在「任务记录」标签下下载。
                </Paragraph>
              </Card>
            ),
          },
          {
            key: 'list',
            label: (
              <Space size={6}>
                <span>任务记录</span>
                {hasActive && <Badge status="processing" />}
              </Space>
            ),
            children: (
              <Card
                size="small"
                title={
                  <Row justify="space-between" align="middle">
                    <Col>共 {tasks.length} 条</Col>
                    <Col>
                      <Button icon={<ReloadOutlined />} size="small" onClick={refresh} loading={loadingList}>
                        刷新
                      </Button>
                    </Col>
                  </Row>
                }
              >
                {tasks.length === 0 && !loadingList ? (
                  <Empty description="还没有分析任务" />
                ) : (
                  <Table<TATask>
                    rowKey="id"
                    size="small"
                    loading={loadingList}
                    dataSource={tasks}
                    columns={columns}
                    pagination={{ pageSize: 20, showSizeChanger: false }}
                    scroll={{ x: 880 }}
                  />
                )}
              </Card>
            ),
          },
        ]}
      />

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
            <Space size={8} wrap>
              <FileMarkdownOutlined />
              <span>
                {viewTask.stock_name || viewTask.ticker} ({viewTask.ticker}) · {viewTask.trade_date}
              </span>
              <DecisionTag decision={viewTask.decision} />
            </Space>
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
    </div>
  );
}
