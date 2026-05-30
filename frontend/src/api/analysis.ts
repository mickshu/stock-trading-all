import api from './client';
import type { AnalysisResponse } from '../types';

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
