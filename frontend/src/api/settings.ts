import api from './client';

export type LocalAgentProvider = 'hermes' | 'claude' | 'codex' | 'gemini';
export type AiProvider = LocalAgentProvider | 'openai' | 'anthropic';
export type SearchProvider = 'none' | 'tavily';

export const LOCAL_AGENT_PROVIDERS: LocalAgentProvider[] = [
  'hermes',
  'claude',
  'codex',
  'gemini',
];

export function isLocalAgentProvider(p: string | undefined): p is LocalAgentProvider {
  return !!p && (LOCAL_AGENT_PROVIDERS as string[]).includes(p);
}

export interface DailySummaryPrompt {
  prompt: string;
  default: string;
}

export async function fetchDailySummaryPrompt(): Promise<DailySummaryPrompt> {
  const { data } = await api.get<DailySummaryPrompt>('/settings/daily-summary-prompt');
  return data;
}

export async function saveDailySummaryPrompt(prompt: string): Promise<DailySummaryPrompt> {
  const { data } = await api.put<DailySummaryPrompt>('/settings/daily-summary-prompt', { prompt });
  return data;
}

export async function resetDailySummaryPrompt(): Promise<DailySummaryPrompt> {
  const { data } = await api.post<DailySummaryPrompt>('/settings/daily-summary-prompt/reset');
  return data;
}

export interface AiSettings {
  provider: AiProvider;
  openai_base_url: string;
  openai_api_key: string;
  openai_model: string;
  anthropic_api_key: string;
  anthropic_model: string;
  search_provider: SearchProvider;
  tavily_api_key: string;
  // === TradingAgents 多智能体专属（可选） ===
  ta_deep_think_llm?: string;
  ta_quick_think_llm?: string;
  ta_backend_url?: string;
  ta_max_debate_rounds?: number;
  ta_request_timeout?: number;
  ta_max_retries?: number;
}

export async function fetchAiSettings(): Promise<AiSettings> {
  const { data } = await api.get<AiSettings>('/settings/ai');
  return data;
}

export async function saveAiSettings(payload: Partial<AiSettings> & { provider: AiProvider }): Promise<AiSettings> {
  const { data } = await api.put<AiSettings>('/settings/ai', payload);
  return data;
}

export interface AiTestResult {
  llm: {
    ok: boolean;
    provider?: string;
    model?: string;
    sample?: string;
    base_url?: string;
    error?: string;
  } | null;
  search: {
    ok: boolean;
    provider?: string;
    results?: number;
    error?: string;
  } | null;
}

export async function testAiSettings(
  payload: Partial<AiSettings> & { provider: AiProvider },
): Promise<AiTestResult> {
  const { data } = await api.post<AiTestResult>('/settings/ai/test', payload);
  return data;
}
