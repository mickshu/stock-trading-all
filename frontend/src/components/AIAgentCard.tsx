import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Divider,
  Empty,
  Input,
  List,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
  Grid,
} from 'antd';
import {
  ExperimentOutlined,
  FileMarkdownOutlined,
  HistoryOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  analyzeWithAIAgent,
  fetchAIAgentReport,
  listAIAgentReports,
  probeAIAgents,
  type AIAgentAnalyzeResult,
  type AIAgentInfo,
  type AIAgentReport,
} from '../api/aiAgent';
import MarkdownView from './MarkdownView';

const { useBreakpoint } = Grid;

interface Props {
  code: string;
  stockName?: string;
}

const DIMENSION_PRESETS = ['综合', '技术面', '基本面', '主力资金', '行业对比', '风险点'];

export default function AIAgentCard({ code, stockName }: Props) {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [agents, setAgents] = useState<AIAgentInfo[]>([]);
  const [agent, setAgent] = useState<string | undefined>(undefined);
  const [dimension, setDimension] = useState('综合');
  const [probing, setProbing] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AIAgentAnalyzeResult | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [reports, setReports] = useState<AIAgentReport[]>([]);
  const [viewingReport, setViewingReport] = useState<{ filename: string; content: string } | null>(null);
  const [viewingLoading, setViewingLoading] = useState(false);

  const reloadReports = useCallback(() => {
    listAIAgentReports(stockName || undefined)
      .then(setReports)
      .catch(() => {});
  }, [stockName]);

  const loadProbe = () => {
    setProbing(true);
    setProbeError(null);
    probeAIAgents()
      .then((list) => {
        setAgents(list);
        if (list.length > 0 && !list.find((a) => a.name === agent)) {
          setAgent(list[0].name);
        }
      })
      .catch((e) => {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setProbeError(detail || '探测失败');
      })
      .finally(() => setProbing(false));
  };

  useEffect(() => {
    loadProbe();
  }, []);

  useEffect(() => {
    reloadReports();
  }, [reloadReports]);

  const handleAnalyze = async () => {
    if (!agent) {
      message.warning('请选择 AI 工具');
      return;
    }
    setRunning(true);
    setResult(null);
    setViewingReport(null);
    try {
      const data = await analyzeWithAIAgent({
        agent,
        code,
        name: stockName,
        dimension,
      });
      setResult(data);
      if (data.ok) {
        message.success(`分析完成（${data.duration.toFixed(1)}s）`);
        reloadReports();
      } else {
        message.error(`分析未成功（exit=${data.exit_code}）`);
      }
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '调用失败');
    } finally {
      setRunning(false);
    }
  };

  const handleViewReport = async (filename: string) => {
    setViewingLoading(true);
    try {
      const data = await fetchAIAgentReport(filename);
      setViewingReport(data);
    } catch {
      message.error('读取报告失败');
    } finally {
      setViewingLoading(false);
    }
  };

  const currentAgent = agents.find((a) => a.name === agent);

  return (
    <Card
      size="small"
      style={{ marginTop: isMobile ? 8 : 16 }}
      title={
        <Space wrap size={6}>
          <ExperimentOutlined />
          <span>AI 分析</span>
          {currentAgent && <Tag color="purple" style={{ marginRight: 0 }}>{currentAgent.label}</Tag>}
        </Space>
      }
      extra={
        <Button size="small" onClick={loadProbe} loading={probing}>
          重新探测
        </Button>
      }
    >
      {probeError && <Alert type="error" message={probeError} style={{ marginBottom: 12 }} />}

      {agents.length === 0 && !probing ? (
        <Empty description="未检测到本地 AI CLI（claude / codex / gemini / hermes）" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <Space wrap style={{ marginBottom: 12, width: isMobile ? '100%' : undefined }} direction={isMobile ? 'vertical' : 'horizontal'}>
            <Select
              style={{ minWidth: isMobile ? '100%' : 180 }}
              placeholder="选择 AI 工具"
              value={agent}
              onChange={setAgent}
              loading={probing}
              options={agents.map((a) => ({
                value: a.name,
                label: `${a.label}${a.version ? ` · ${a.version}` : ''}`,
              }))}
            />
            <Select
              style={{ minWidth: isMobile ? '100%' : 140 }}
              value={DIMENSION_PRESETS.includes(dimension) ? dimension : '自定义'}
              onChange={(v) => {
                if (v !== '自定义') setDimension(v);
              }}
              options={[
                ...DIMENSION_PRESETS.map((d) => ({ value: d, label: d })),
                { value: '自定义', label: '自定义…' },
              ]}
            />
            {(!DIMENSION_PRESETS.includes(dimension)) && (
              <Input
                style={{ minWidth: isMobile ? '100%' : 220 }}
                placeholder="自定义分析维度"
                value={dimension}
                onChange={(e) => setDimension(e.target.value)}
                allowClear
              />
            )}
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={running}
              onClick={handleAnalyze}
              disabled={!agent}
              block={isMobile}
            >
              开始分析
            </Button>
          </Space>

          <Spin spinning={running} description="本地 CLI 运行中…">
            {result ? (
              <>
                {!result.ok && result.stderr && (
                  <Alert
                    type="warning"
                    message={`exit=${result.exit_code}`}
                    description={
                      <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 12 }}>
                        {result.stderr}
                      </pre>
                    }
                    style={{ marginBottom: 12 }}
                  />
                )}
                {result.report_url && result.report_filename && (
                  <Alert
                    type="success"
                    showIcon
                    icon={<FileMarkdownOutlined />}
                    style={{ marginBottom: 12 }}
                    message={
                      <Space size={8} wrap>
                        <span>已保存报告：</span>
                        <a href={result.report_url} target="_blank" rel="noreferrer">
                          {result.report_filename}
                        </a>
                      </Space>
                    }
                  />
                )}
                {result.output ? (
                  <MarkdownView content={result.output} />
                ) : (
                  <Typography.Text type="secondary">（无输出）</Typography.Text>
                )}
              </>
            ) : (
              !running && !viewingReport && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  选择工具与维度后点击「开始分析」
                </Typography.Text>
              )
            )}

            {viewingReport && !result && (
              <>
                <Alert
                  type="info"
                  showIcon
                  icon={<FileMarkdownOutlined />}
                  style={{ marginBottom: 12 }}
                  message={
                    <Space size={8} wrap>
                      <span>历史报告：</span>
                      <a
                        href={`/reports/${encodeURIComponent(viewingReport.filename)}`}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {viewingReport.filename}
                      </a>
                      <Button size="small" type="link" onClick={() => setViewingReport(null)}>
                        关闭
                      </Button>
                    </Space>
                  }
                />
                <MarkdownView content={viewingReport.content} />
              </>
            )}
          </Spin>

          {reports.length > 0 && (
            <>
              <Divider style={{ margin: '12px 0 8px' }} plain>
                <Space size={6}>
                  <HistoryOutlined />
                  <span style={{ fontSize: 12 }}>历史报告{stockName ? `（${stockName}）` : ''}</span>
                </Space>
              </Divider>
              <Spin spinning={viewingLoading} size="small">
                <List
                  size="small"
                  dataSource={reports}
                  renderItem={(item) => (
                    <List.Item
                      style={{ padding: '6px 0' }}
                      actions={[
                        <Button
                          key="view"
                          type="link"
                          size="small"
                          onClick={() => handleViewReport(item.filename)}
                        >
                          查看
                        </Button>,
                      ]}
                    >
                      <Space size={8} wrap>
                        <Tag color="blue" style={{ marginRight: 0 }}>{item.date || '—'}</Tag>
                        <span style={{ fontSize: 13 }}>{item.name}</span>
                        {!isMobile && (
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {item.mtime}
                          </Typography.Text>
                        )}
                      </Space>
                    </List.Item>
                  )}
                />
              </Spin>
            </>
          )}
        </>
      )}
    </Card>
  );
}
