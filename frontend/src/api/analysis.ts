import api from './client';
import type { AnalysisResponse, LivermoreResponse } from '../types';

export async function fetchAnalysis(
  code: string,
  period: string,
  indicators = 'MACD,MA,KDJ,RSI',
  forceRefresh = false,
): Promise<AnalysisResponse> {
  const { data } = await api.get<AnalysisResponse>('/analysis/indicators', {
    params: { code, period, indicators, force_refresh: forceRefresh },
  });
  return data;
}

export interface LivermoreQuery {
  high_n?: number;
  box_n?: number;
  stop_pct?: number;
  first_pct?: number;
  add_step_pct?: number;
  add_pct?: number;
  levels?: number;
}

export async function fetchLivermore(
  code: string,
  params: LivermoreQuery = {},
): Promise<LivermoreResponse> {
  const { data } = await api.get<LivermoreResponse>('/analysis/livermore', {
    params: { code, ...params },
  });
  return data;
}
