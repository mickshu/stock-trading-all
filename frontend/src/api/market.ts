import api from './client';
import type { KlineResponse, IndexData } from '../types';

export async function fetchKline(
  code: string,
  period: string,
  start?: string,
  end?: string,
  forceRefresh?: boolean,
): Promise<KlineResponse> {
  const params: Record<string, string | boolean | undefined> = {
    code,
    period,
    start,
    end,
    force_refresh: forceRefresh,
  };
  const { data } = await api.get<KlineResponse>('/market/kline', { params });
  return data;
}

export async function fetchIndices(): Promise<IndexData[]> {
  const { data } = await api.get<IndexData[]>('/market/indices');
  return data;
}

export interface QuoteData {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  volume?: number | null;
  amount?: number | null;
  main_net?: number | null;
  main_net_ratio?: number | null;
}

export async function fetchQuote(code: string): Promise<QuoteData> {
  const { data } = await api.get<QuoteData>('/market/quote', { params: { code } });
  return data;
}

export async function fetchQuotes(codes: string[]): Promise<QuoteData[]> {
  if (!codes || codes.length === 0) return [];
  const { data } = await api.get<{ quotes: QuoteData[] }>('/market/quotes', {
    params: { codes: codes.join(',') },
  });
  return data.quotes || [];
}

export interface Fundamentals {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  pe: number | null;
  pe_ttm: number | null;
  pb: number | null;
  ps_ttm: number | null;
  dv_ttm: number | null;
  total_market_cap: number | null;
  float_market_cap: number | null;
  total_shares: number | null;
  float_shares: number | null;
  industry: string;
  listing_date: string;
  as_of: string | null;
}

export async function fetchFundamentals(code: string): Promise<Fundamentals> {
  const { data } = await api.get<Fundamentals>('/market/fundamentals', { params: { code } });
  return data;
}
