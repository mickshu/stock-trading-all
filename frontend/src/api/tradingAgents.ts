import api from './client';

export interface TARunRequest {
  ticker: string;
  trade_date: string;
  depth: number;
  online_tools: boolean;
}

export interface TACreateTaskRequest extends TARunRequest {
  stock_name?: string;
}

export interface TAHealth {
  provider: string;
  deep_think_llm: string;
  quick_think_llm: string;
  backend_url: string;
  data_source: string;
}

export interface TAResult {
  ticker: string;
  trade_date: string;
  decision: string;
  summary: {
    market: string;
    sentiment: string;
    news: string;
    fundamentals: string;
  };
  reports: {
    market: string;
    sentiment: string;
    news: string;
    fundamentals: string;
  };
  debate: {
    bull_history: string[];
    bear_history: string[];
    judge_decision: string;
  };
  risk: {
    current_response: string;
  };
  config: {
    llm_provider: string;
    deep_think_llm: string;
    quick_think_llm: string;
    data_source: string;
    max_debate_rounds: number;
    online_tools: boolean;
  };
}

export type TATaskStatus = 'pending' | 'running' | 'success' | 'failed';

export interface TATask {
  id: string;
  ticker: string;
  stock_name: string;
  trade_date: string;
  depth: number;
  online_tools: boolean;
  status: TATaskStatus;
  decision: string;
  decision_raw: string;
  report_filename: string;
  report_url: string;
  report_md?: string;
  error: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_sec: number | null;
}

export async function fetchTAHealth(): Promise<TAHealth> {
  const { data } = await api.get<TAHealth>('/trading-agents/health');
  return data;
}

export async function runTradingAgents(payload: TARunRequest): Promise<TAResult> {
  const { data } = await api.post<TAResult>('/trading-agents/analyze', payload, {
    timeout: 600_000,
  });
  return data;
}

export async function createTATask(payload: TACreateTaskRequest): Promise<TATask> {
  const { data } = await api.post<TATask>('/trading-agents/tasks', payload);
  return data;
}

export async function listTATasks(limit = 100): Promise<TATask[]> {
  const { data } = await api.get<{ items: TATask[] }>('/trading-agents/tasks', {
    params: { limit },
  });
  return data.items;
}

export async function getTATask(taskId: string, withMd = false): Promise<TATask> {
  const { data } = await api.get<TATask>(`/trading-agents/tasks/${taskId}`, {
    params: { with_md: withMd },
  });
  return data;
}

export async function deleteTATask(taskId: string): Promise<void> {
  await api.delete(`/trading-agents/tasks/${taskId}`);
}
