import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Radio,
  Space,
  Spin,
  Tabs,
  Typography,
  message,
  Grid,
} from 'antd';
import { fetchDataSources, switchDataSource } from '../api/stocks';
import {
  fetchAiSettings,
  saveAiSettings,
  testAiSettings,
  type AiProvider,
  type AiSettings,
  type AiTestResult,
  type SearchProvider,
} from '../api/settings';

const { useBreakpoint } = Grid;

function DataSourceTab() {
  const [active, setActive] = useState<string>('');
  const [available, setAvailable] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchDataSources()
      .then((d) => {
        setActive(d.active);
        setAvailable(d.available);
      })
      .catch(() => message.error('加载数据源失败'))
      .finally(() => setLoading(false));
  }, []);

  const handleSwitch = async (source: string) => {
    setSaving(true);
    try {
      const r = await switchDataSource(source);
      setActive(r.active);
      message.success(`已切换至 ${r.active}`);
    } catch {
      message.error('切换失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="数据源" loading={loading} size="small">
      <Space orientation="vertical" style={{ width: '100%' }}>
        <Alert type="info" showIcon title="切换上游行情数据源。已缓存的 K 线会继续复用。" />
        <Spin spinning={saving}>
          <Radio.Group
            value={active}
            onChange={(e) => handleSwitch(e.target.value)}
            disabled={saving}
          >
            <Space orientation="vertical">
              {available.map((src) => (
                <Radio key={src} value={src}>
                  {src}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </Spin>
      </Space>
    </Card>
  );
}

function AiSettingsTab() {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [form] = Form.useForm<AiSettings>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<AiTestResult | null>(null);
  const [provider, setProvider] = useState<AiProvider>('openai');
  const [searchProvider, setSearchProvider] = useState<SearchProvider>('none');

  useEffect(() => {
    setLoading(true);
    fetchAiSettings()
      .then((s) => {
        form.setFieldsValue(s);
        setProvider(s.provider);
        setSearchProvider(s.search_provider);
      })
      .catch(() => message.error('加载 AI 配置失败'))
      .finally(() => setLoading(false));
  }, [form]);

  const onSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const saved = await saveAiSettings(values);
      form.setFieldsValue(saved);
      message.success('已保存');
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail) message.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const onTest = async () => {
    try {
      const values = await form.validateFields();
      setTesting(true);
      setTestResult(null);
      const r = await testAiSettings(values);
      setTestResult(r);
      if (r.llm?.ok && (r.search === null || r.search?.ok)) {
        message.success('测试通过');
      } else {
        message.warning('测试未全部通过');
      }
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '测试请求失败');
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card title="AI 配置" loading={loading} size="small">
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="API Key 仅保存在本地数据库；空着不动 = 保留原值。LLM 配置同时供「AI 分析」（多智能体）使用。"
      />
      <Form
        form={form}
        layout={isMobile ? 'vertical' : 'vertical'}
        initialValues={{ provider: 'openai', search_provider: 'none' }}
      >
        <Typography.Title level={5} style={{ marginTop: 0 }}>基础 LLM</Typography.Title>

        <Form.Item
          name="provider"
          label="LLM Provider"
          rules={[{ required: true }]}
        >
          <Radio.Group onChange={(e) => setProvider(e.target.value)}>
            <Space orientation={isMobile ? 'vertical' : 'horizontal'}>
              <Radio value="openai">OpenAI 兼容</Radio>
              <Radio value="anthropic">Anthropic Claude</Radio>
            </Space>
          </Radio.Group>
        </Form.Item>

        {provider === 'openai' ? (
          <>
            <Form.Item name="openai_base_url" label="OpenAI Base URL">
              <Input placeholder="https://api.openai.com/v1" />
            </Form.Item>
            <Form.Item name="openai_api_key" label="OpenAI API Key">
              <Input.Password autoComplete="off" placeholder="留空 = 保留原值" />
            </Form.Item>
            <Form.Item name="openai_model" label="Model">
              <Input placeholder="如 gpt-4o-mini、deepseek-chat" />
            </Form.Item>
          </>
        ) : (
          <>
            <Form.Item name="anthropic_api_key" label="Anthropic API Key">
              <Input.Password autoComplete="off" placeholder="留空 = 保留原值" />
            </Form.Item>
            <Form.Item name="anthropic_model" label="Model">
              <Input placeholder="如 claude-sonnet-4-6" />
            </Form.Item>
          </>
        )}

        <Form.Item name="search_provider" label="联网搜索">
          <Radio.Group onChange={(e) => setSearchProvider(e.target.value)}>
            <Space orientation={isMobile ? 'vertical' : 'horizontal'}>
              <Radio value="none">不启用</Radio>
              <Radio value="tavily">Tavily</Radio>
            </Space>
          </Radio.Group>
        </Form.Item>

        {searchProvider === 'tavily' && (
          <Form.Item name="tavily_api_key" label="Tavily API Key">
            <Input.Password autoComplete="off" placeholder="留空 = 保留原值" />
          </Form.Item>
        )}

        <Typography.Title level={5} style={{ marginTop: 24 }}>多智能体 (TradingAgents)</Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginTop: -4, fontSize: 12 }}>
          API Key 沿用上方「基础 LLM」配置；此处只设定 TradingAgents 框架特有的字段。
        </Typography.Paragraph>

        <Form.Item
          name="ta_deep_think_llm"
          label="深度思考模型 (Deep Think LLM)"
          extra="用于研究员辩论、风险评估等长链推理。"
        >
          <Input placeholder="如 deepseek-v4-pro / gpt-4o / claude-sonnet-4-6" />
        </Form.Item>
        <Form.Item
          name="ta_quick_think_llm"
          label="快速思考模型 (Quick Think LLM)"
          extra="用于分析师初步分析。可与深度模型相同。"
        >
          <Input placeholder="如 deepseek-v4-pro / gpt-4o-mini" />
        </Form.Item>
        <Form.Item
          name="ta_backend_url"
          label="多智能体 LLM Base URL"
          extra="OpenAI 兼容接口端点。Anthropic 默认 https://api.anthropic.com。可与上方 Base URL 不同。"
        >
          <Input placeholder="https://api.deepseek.com/v1" />
        </Form.Item>
        <Form.Item
          name="ta_max_debate_rounds"
          label="辩论轮数"
          extra="1=快 / 2=中 / 3=深。轮数越多耗时越长。"
        >
          <InputNumber min={1} max={5} style={{ width: 120 }} />
        </Form.Item>

        <Form.Item>
          <Space orientation={isMobile ? 'vertical' : 'horizontal'} style={{ width: isMobile ? '100%' : undefined }}>
            <Button type="primary" onClick={onSave} loading={saving} block={isMobile}>
              保存
            </Button>
            <Button onClick={onTest} loading={testing} block={isMobile}>
              测试联调
            </Button>
          </Space>
        </Form.Item>

        {testResult && (
          <Space orientation="vertical" style={{ width: '100%' }}>
            {testResult.llm && (
              <Alert
                type={testResult.llm.ok ? 'success' : 'error'}
                showIcon
                title={
                  testResult.llm.ok
                    ? `LLM 联通成功：${testResult.llm.provider} / ${testResult.llm.model}`
                    : `LLM 联通失败：${testResult.llm.error}`
                }
              />
            )}
            {testResult.search && (
              <Alert
                type={testResult.search.ok ? 'success' : 'error'}
                showIcon
                title={
                  testResult.search.ok
                    ? `Tavily 联通成功（${testResult.search.results ?? 0} 条）`
                    : `Tavily 联通失败：${testResult.search.error}`
                }
              />
            )}
          </Space>
        )}
      </Form>
    </Card>
  );
}

export default function Settings() {
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <Typography.Title level={4} style={{ margin: '0 0 16px 0' }}>设置</Typography.Title>
      <Tabs
        size={isMobile ? 'small' : 'middle'}
        items={[
          { key: 'data', label: '数据源', children: <DataSourceTab /> },
          { key: 'ai', label: 'AI 配置', children: <AiSettingsTab /> },
        ]}
      />
    </div>
  );
}
