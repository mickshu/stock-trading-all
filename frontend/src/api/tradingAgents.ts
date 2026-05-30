import api from './client';

export interface TARunRequest {
  ticker: string;
  trade_date: string;
  depth: number;
  online_tools: boolean;
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
