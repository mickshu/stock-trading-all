import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
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
  isLocalAgentProvider,
  LOCAL_AGENT_PROVIDERS,
  type AiProvider,
  type AiSettings,
  type AiTestResult,
  type LocalAgentProvider,
  type SearchProvider,
} from '../api/settings';
import { probeAIAgents, type AIAgentInfo } from '../api/aiAgent';

type AiMode = 'native' | 'local';

const LOCAL_AGENT_LABELS: Record<LocalAgentProvider, string> = {
  hermes: 'Hermes',
  claude: 'Claude Code',
  codex: 'Codex CLI',
  gemini: 'Gemini CLI',
};

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
      <Space direction="vertical" style={{ width: '100%' }}>
        <Alert type="info" showIcon message="切换上游行情数据源。已缓存的 K 线会继续复用。" />
        <Spin spinning={saving}>
          <Radio.Group
            value={active}
            onChange={(e) => handleSwitch(e.target.value)}
            disabled={saving}
          >
            <Space direction="vertical">
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
  const [mode, setMode] = useState<AiMode>('native');
  const [provider, setProvider] = useState<AiProvider>('openai');
  // 本地模式选中的 Agent；与 provider 同步保存。
  const [localAgent, setLocalAgent] = useState<LocalAgentProvider>('hermes');
  const [searchProvider, setSearchProvider] = useState<SearchProvider>('none');
  const [agents, setAgents] = useState<AIAgentInfo[]>([]);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);

  const refreshAgents = async (): Promise<AIAgentInfo[]> => {
    setProbing(true);
    setProbeError(null);
    try {
      const list = await probeAIAgents();
      setAgents(list);
      return list;
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setProbeError(detail || '探测失败');
      setAgents([]);
      return [];
    } finally {
      setProbing(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchAiSettings()
      .then((s) => {
        form.setFieldsValue(s);
        const isLocal = isLocalAgentProvider(s.provider);
        setProvider(isLocal ? 'openai' : s.provider);
        if (isLocal) setLocalAgent(s.provider as LocalAgentProvider);
        setSearchProvider(s.search_provider);
        const initialMode: AiMode = isLocal ? 'local' : 'native';
        setMode(initialMode);
        if (initialMode === 'local') {
          refreshAgents();
        }
      })
      .catch(() => message.error('加载 AI 配置失败'))
      .finally(() => setLoading(false));
  }, [form]);

  const handleModeChange = (next: AiMode) => {
    setMode(next);
    setTestResult(null);
    if (next === 'local') {
      // 本地 Agent 模式：默认 hermes，探测后若不存在则自动切换到首个可用项。
      form.setFieldValue('provider', localAgent);
      refreshAgents().then((list) => {
        if (!list.length) return;
        const has = list.some((a) => a.name === localAgent);
        if (!has) {
          const first = list[0].name as LocalAgentProvider;
          setLocalAgent(first);
          form.setFieldValue('provider', first);
        }
      });
    } else {
      const restore = isLocalAgentProvider(provider) ? 'openai' : provider;
      form.setFieldValue('provider', restore);
      setProvider(restore);
    }
  };

  const handleLocalAgentChange = (next: LocalAgentProvider) => {
    setLocalAgent(next);
    form.setFieldValue('provider', next);
    setTestResult(null);
  };

  const onSave = async () => {
    try {
      const values = await form.validateFields();
      const payload: AiSettings = {
        ...values,
        provider: mode === 'local' ? localAgent : (values.provider || provider),
      };
      setSaving(true);
      const saved = await saveAiSettings(payload);
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
    setTestResult(null);
    if (mode === 'local') {
      // 本地 Agent：重新探测，校验当前选择的 CLI 是否安装。
      setTesting(true);
      try {
        const list = await refreshAgents();
        const hit = list.find((a) => a.name === localAgent);
        if (hit) {
          setTestResult({
            llm: { ok: true, provider: localAgent, model: hit.version || hit.path },
            search: null,
          });
          message.success(`检测到 ${LOCAL_AGENT_LABELS[localAgent]} CLI`);
        } else if (list.length > 0) {
          setTestResult({
            llm: {
              ok: false,
              error: `未检测到 ${localAgent}；已检测到其他 CLI：${list.map((a) => a.name).join(', ')}`,
            },
            search: null,
          });
          message.warning(`未检测到 ${localAgent}`);
        } else {
          setTestResult({
            llm: { ok: false, error: '未检测到任何本地 AI CLI' },
            search: null,
          });
          message.warning('未检测到任何本地 AI CLI');
        }
      } catch (e) {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setTestResult({
          llm: { ok: false, error: detail || '探测失败' },
          search: null,
        });
      } finally {
        setTesting(false);
      }
      return;
    }
    try {
      const values = await form.validateFields();
      setTesting(true);
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
        message="API Key 仅保存在本地数据库；空着不动 = 保留原值。LLM 配置同时供「AI 分析」（多智能体）使用。"
      />
      <Form
        form={form}
        layout={isMobile ? 'vertical' : 'vertical'}
        initialValues={{ provider: 'openai', search_provider: 'none' }}
      >
        <Form.Item label="配置模式" style={{ marginBottom: 16 }}>
          <Radio.Group
            value={mode}
            onChange={(e) => handleModeChange(e.target.value as AiMode)}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio.Button value="native">原生模型 API</Radio.Button>
            <Radio.Button value="local">本地 Agent CLI</Radio.Button>
          </Radio.Group>
          <Typography.Paragraph type="secondary" style={{ marginTop: 6, marginBottom: 0, fontSize: 12 }}>
            {mode === 'native'
              ? '通过 HTTP 调用 OpenAI / Anthropic 兼容接口。需要填写 API Key。'
              : '调用本地安装的 AI CLI（如 hermes / claude / codex / gemini），无需 API Key。'}
          </Typography.Paragraph>
        </Form.Item>

        {/* 始终保留 provider 字段在表单里，本地模式锁定为 hermes */}
        <Form.Item name="provider" hidden>
          <Input />
        </Form.Item>

        {mode === 'native' ? (
          <>
            <Typography.Title level={5} style={{ marginTop: 0 }}>基础 LLM</Typography.Title>

            <Form.Item label="LLM Provider" required>
              <Radio.Group
                value={provider}
                onChange={(e) => {
                  const v = e.target.value as AiProvider;
                  setProvider(v);
                  form.setFieldValue('provider', v);
                }}
              >
                <Space direction={isMobile ? 'vertical' : 'horizontal'}>
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
                <Space direction={isMobile ? 'vertical' : 'horizontal'}>
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
          </>
        ) : (
          <>
            <Typography.Title level={5} style={{ marginTop: 0 }}>本地 Agent CLI</Typography.Title>
            <Typography.Paragraph type="secondary" style={{ marginTop: -4, fontSize: 12 }}>
              选择任一已安装的本地 Agent（hermes / claude / codex / gemini）作为 AI 分析与收盘总结的 LLM 入口。AI 分析为可选功能，未选择或未安装时不影响行情、资金流等基础展示。
            </Typography.Paragraph>

            <Form.Item label="本地 Agent" style={{ marginBottom: 12 }}>
              <Select<LocalAgentProvider>
                style={{ minWidth: isMobile ? '100%' : 240 }}
                value={localAgent}
                onChange={handleLocalAgentChange}
                options={LOCAL_AGENT_PROVIDERS.map((name) => {
                  const detected = agents.find((a) => a.name === name);
                  return {
                    value: name,
                    label: detected
                      ? `${LOCAL_AGENT_LABELS[name]} · 已安装${detected.version ? ` (${detected.version})` : ''}`
                      : `${LOCAL_AGENT_LABELS[name]} · 未检测到`,
                    disabled: !detected,
                  };
                })}
              />
            </Form.Item>

            <Spin spinning={probing}>
              {probeError ? (
                <Alert type="error" showIcon style={{ marginBottom: 12 }} message={`探测失败：${probeError}`} />
              ) : agents.length === 0 ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message="未检测到任何本地 AI CLI"
                  description="请确认 hermes / claude / codex / gemini 已安装并在 PATH 中。AI 分析为可选功能，可不安装。"
                />
              ) : (
                <Alert
                  type={agents.some((a) => a.name === localAgent) ? 'success' : 'warning'}
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={
                    agents.some((a) => a.name === localAgent)
                      ? `已选择 ${LOCAL_AGENT_LABELS[localAgent]}（已安装），将作为 LLM 入口`
                      : `当前选择的 ${LOCAL_AGENT_LABELS[localAgent]} 未检测到，请改选已安装项或安装后重试`
                  }
                  description={
                    <Space direction="vertical" size={2} style={{ marginTop: 4 }}>
                      {agents.map((a) => (
                        <Typography.Text key={a.name} style={{ fontSize: 12 }}>
                          <strong>{a.label}</strong>
                          <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                            {a.path}{a.version ? ` · ${a.version}` : ''}
                          </Typography.Text>
                        </Typography.Text>
                      ))}
                    </Space>
                  }
                />
              )}
              <Button size="small" onClick={() => refreshAgents()} loading={probing} style={{ marginBottom: 16 }}>
                重新探测
              </Button>
            </Spin>
          </>
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
          <Space direction={isMobile ? 'vertical' : 'horizontal'} style={{ width: isMobile ? '100%' : undefined }}>
            <Button type="primary" onClick={onSave} loading={saving} block={isMobile}>
              保存
            </Button>
            <Button onClick={onTest} loading={testing} block={isMobile}>
              测试联调
            </Button>
          </Space>
        </Form.Item>

        {testResult && (
          <Space direction="vertical" style={{ width: '100%' }}>
            {testResult.llm && (
              <Alert
                type={testResult.llm.ok ? 'success' : (mode === 'local' ? 'warning' : 'error')}
                showIcon
                message={
                  testResult.llm.ok
                    ? (mode === 'local'
                      ? `本地 CLI 可用：${testResult.llm.provider} / ${testResult.llm.model}`
                      : `LLM 联通成功：${testResult.llm.provider} / ${testResult.llm.model}`)
                    : (mode === 'local'
                      ? `本地 CLI 检测：${testResult.llm.error}`
                      : `LLM 联通失败：${testResult.llm.error}`)
                }
              />
            )}
            {testResult.search && (
              <Alert
                type={testResult.search.ok ? 'success' : 'error'}
                showIcon
                message={
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
