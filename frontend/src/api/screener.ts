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
