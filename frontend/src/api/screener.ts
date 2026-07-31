import api from './client';
import type { Signal, SystemTag } from '../types';

export interface ScreenerStockResult {
  code: string;
  name: string;
  market: string;
  latest_date: string;
  latest_close: number;
  matching_signals: Signal[];
  total_signals: number;
}

export interface ScreenerResponse {
  results: ScreenerStockResult[];
  total_stocks_screened: number;
  total_matches: number;
}

export interface ScreenerParams {
  signal_types?: string;
  signal_categories?: string;
  signal_levels?: string;
  period?: string;
  days?: number;
  recent_days?: number;
  codes?: string;
  group_id?: number;
  ungrouped?: boolean;
  tag?: SystemTag;
}

export async function runScreener(params: ScreenerParams): Promise<ScreenerResponse> {
  const { data } = await api.get<ScreenerResponse>('/screener', { params });
  return data;
}

export interface ConditionScreenerResult {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  pe: number | null;
  pb: number | null;
  total_market_cap: number | null;
  total_market_cap_yi: number | null;
  float_market_cap: number | null;
  turnover: number | null;
  volume_ratio: number | null;
  amplitude: number | null;
  amount: number | null;
  industry: string;
}

export interface ConditionScreenerResponse {
  results: ConditionScreenerResult[];
  total: number;
  page: number;
  page_size: number;
}

export interface ConditionScreenerParams {
  pe_min?: number;
  pe_max?: number;
  pb_min?: number;
  pb_max?: number;
  market_cap_min?: number;
  market_cap_max?: number;
  change_pct_min?: number;
  change_pct_max?: number;
  turnover_min?: number;
  turnover_max?: number;
  volume_ratio_min?: number;
  volume_ratio_max?: number;
  amplitude_min?: number;
  amplitude_max?: number;
  amount_min?: number;
  amount_max?: number;
  discount_rate_min?: number;
  discount_rate_max?: number;
  size_min?: number;
  size_max?: number;
  security_type?: string;
  sort_by?: string;
  sort_order?: string;
  page?: number;
  page_size?: number;
  scope?: string;
  group_id?: number;
  tag?: string;
}

export async function runConditionScreener(
  params: ConditionScreenerParams,
): Promise<ConditionScreenerResponse> {
  const { data } = await api.get<ConditionScreenerResponse>('/screener/condition', { params });
  return data;
}
