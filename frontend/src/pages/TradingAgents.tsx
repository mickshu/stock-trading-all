import { useEffect, useState } from 'react';
import {
  Card,
  Form,
  Input,
  DatePicker,
  Slider,
  Switch,
  Button,
  Space,
  Alert,
  Tag,
  Collapse,
  Empty,
  Typography,
  Descriptions,
  message,
  Spin,
  Row,
  Col,
} from 'antd';
import {
  DeploymentUnitOutlined,
  ThunderboltOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import MarkdownView from '../components/MarkdownView';
import {
  fetchTAHealth,
  runTradingAgents,
  type TAHealth,
  type TAResult,
} from '../api/tradingAgents';

const { Title, Text, Paragraph } = Typography;

interface FormValues {
  ticker: string;
  trade_date: Dayjs;
  depth: number;
  online_tools: boolean;
}

function DecisionTag({ decision }: { decision: string }) {
  const upper = (decision || '').toUpperCase();
  let color = 'default';
  let label = decision || '未知';
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
  return (
    <Tag color={color} style={{ fontSize: 20, padding: '6px 18px', fontWeight: 700 }}>
      {label}
    </Tag>
  );
}

export default function TradingAgentsPage() {
  const [form] = Form.useForm<FormValues>();
  const [health, setHealth] = useState<TAHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TAResult | null>(null);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    fetchTAHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const onFinish = async (values: FormValues) => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const data = await runTradingAgents({
        ticker: values.ticker.trim(),
        trade_date: values.trade_date.format('YYYY-MM-DD'),
        depth: values.depth,
        online_tools: values.online_tools,
      });
      setResult(data);
      message.success('分析完成');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      message.error('分析失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Title level={3}>
        <DeploymentUnitOutlined /> TradingAgents 多智能体分析
      </Title>
      <Paragraph type="secondary">
        基于 LangGraph 编排的多智能体框架：市场 / 舆情 / 新闻 / 基本面 4 位分析师 →
        多空研究员辩论 → 风险评估 → 最终决策。
      </Paragraph>

      {health && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            <Space size="middle" wrap>
              <span>
                <Text strong>Provider:</Text> {health.provider}
              </span>
              <span>
                <Text strong>深度模型:</Text> {health.deep_think_llm}
              </span>
              <span>
                <Text strong>数据源:</Text> {health.data_source}
              </span>
              <Text type="secondary">配置可在「设置 → AI 配置」修改</Text>
            </Space>
          }
        />
      )}

      <Card size="small" title="发起分析" style={{ marginBottom: 16 }}>
        <Form
          form={form}
          layout="inline"
          initialValues={{
            ticker: '600000',
            trade_date: dayjs(),
            depth: 1,
            online_tools: true,
          }}
          onFinish={onFinish}
        >
          <Form.Item name="ticker" label="股票代码" rules={[{ required: true }]}>
            <Input style={{ width: 140 }} placeholder="如 600000 / NVDA" />
          </Form.Item>
          <Form.Item name="trade_date" label="分析日期" rules={[{ required: true }]}>
            <DatePicker />
          </Form.Item>
          <Form.Item name="depth" label="辩论轮数" style={{ minWidth: 200 }}>
            <Slider min={1} max={3} marks={{ 1: '快', 2: '中', 3: '深' }} />
          </Form.Item>
          <Form.Item name="online_tools" label="在线数据" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<PlayCircleOutlined />}
            >
              开始分析
            </Button>
          </Form.Item>
        </Form>
      </Card>

      {loading && (
        <Card style={{ marginBottom: 16, textAlign: 'center', padding: 24 }}>
          <Spin tip="多智能体协作中，整体耗时取决于辩论轮数（通常 1-5 分钟）..." size="large">
            <div style={{ minHeight: 60 }} />
          </Spin>
        </Card>
      )}

      {error && !loading && (
        <Alert
          type="error"
          showIcon
          message="分析失败"
          description={error}
          style={{ marginBottom: 16 }}
        />
      )}

      {result && (
        <>
          <Card style={{ marginBottom: 16 }}>
            <Row gutter={16} align="middle">
              <Col flex="none">
                <DecisionTag decision={result.decision} />
              </Col>
              <Col flex="auto">
                <Descriptions size="small" column={2}>
                  <Descriptions.Item label="股票">{result.ticker}</Descriptions.Item>
                  <Descriptions.Item label="日期">{result.trade_date}</Descriptions.Item>
                  <Descriptions.Item label="模型">
                    {result.config.deep_think_llm}
                  </Descriptions.Item>
                  <Descriptions.Item label="数据源">
                    {result.config.data_source}
                  </Descriptions.Item>
                  <Descriptions.Item label="辩论轮数">
                    {result.config.max_debate_rounds}
                  </Descriptions.Item>
                  <Descriptions.Item label="在线工具">
                    {result.config.online_tools ? '是' : '否'}
                  </Descriptions.Item>
                </Descriptions>
              </Col>
            </Row>
          </Card>

          <Card size="small" title="维度摘要" style={{ marginBottom: 16 }}>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="📊 市场技术">{result.summary.market}</Descriptions.Item>
              <Descriptions.Item label="💬 舆情社交">{result.summary.sentiment}</Descriptions.Item>
              <Descriptions.Item label="📰 新闻宏观">{result.summary.news}</Descriptions.Item>
              <Descriptions.Item label="📈 基本面">{result.summary.fundamentals}</Descriptions.Item>
            </Descriptions>
          </Card>

          <Collapse
            defaultActiveKey={['market']}
            items={[
              {
                key: 'market',
                label: '📊 市场分析报告',
                children: result.reports.market ? (
                  <MarkdownView content={result.reports.market} />
                ) : (
                  <Empty />
                ),
              },
              {
                key: 'sentiment',
                label: '💬 舆情分析报告',
                children: result.reports.sentiment ? (
                  <MarkdownView content={result.reports.sentiment} />
                ) : (
                  <Empty />
                ),
              },
              {
                key: 'news',
                label: '📰 新闻分析报告',
                children: result.reports.news ? (
                  <MarkdownView content={result.reports.news} />
                ) : (
                  <Empty />
                ),
              },
              {
                key: 'fundamentals',
                label: '📈 基本面分析报告',
                children: result.reports.fundamentals ? (
                  <MarkdownView content={result.reports.fundamentals} />
                ) : (
                  <Empty />
                ),
              },
              {
                key: 'debate',
                label: (
                  <span>
                    <ThunderboltOutlined /> 多空辩论 & 评判
                  </span>
                ),
                children: (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    {result.debate.bull_history.length > 0 && (
                      <Card type="inner" size="small" title="多头观点">
                        <MarkdownView
                          content={String(result.debate.bull_history.slice(-1)[0] || '')}
                        />
                      </Card>
                    )}
                    {result.debate.bear_history.length > 0 && (
                      <Card type="inner" size="small" title="空头观点">
                        <MarkdownView
                          content={String(result.debate.bear_history.slice(-1)[0] || '')}
                        />
                      </Card>
                    )}
                    {result.debate.judge_decision && (
                      <Card type="inner" size="small" title="评判">
                        <MarkdownView content={String(result.debate.judge_decision)} />
                      </Card>
                    )}
                  </Space>
                ),
              },
              {
                key: 'risk',
                label: '🛡️ 风险评估',
                children: result.risk.current_response ? (
                  <MarkdownView content={String(result.risk.current_response)} />
                ) : (
                  <Empty />
                ),
              },
            ]}
          />
        </>
      )}
    </div>
  );
}
