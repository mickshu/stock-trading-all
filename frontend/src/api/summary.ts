import api from './client';

export interface FundFlowStockItem {
  code: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  main_net: number | null;
  main_net_ratio: number | null;
}

export interface FundFlowSectorItem {
  code: string;
  name: string;
  change_pct: number | null;
  main_net: number | null;
  main_net_ratio: number | null;
  lead_stock?: string;
  lead_change_pct?: number | null;
}

export interface FundFlowStocks {
  date: string | null;
  inflow: FundFlowStockItem[];
  outflow: FundFlowStockItem[];
}

export interface FundFlowSectors {
  date: string | null;
  inflow: FundFlowSectorItem[];
  outflow: FundFlowSectorItem[];
}

export interface DailySummaryPayload {
  model: string;
  content: string;
  sources: string[];
  generated_at: string;
}

export async function fetchFundFlowStocks(n = 10): Promise<FundFlowStocks> {
  const { data } = await api.get<FundFlowStocks>('/summary/fund-flow/stocks', { params: { n } });
  return data;
}

export async function fetchFundFlowSectors(n = 5): Promise<FundFlowSectors> {
  const { data } = await api.get<FundFlowSectors>('/summary/fund-flow/sectors', { params: { n } });
  return data;
}

export async function fetchDailySummary(force = false): Promise<DailySummaryPayload> {
  const { data } = await api.get<DailySummaryPayload>('/summary/daily', { params: { force } });
  return data;
}

export async function refreshDailySummary(): Promise<DailySummaryPayload> {
  const { data } = await api.post<DailySummaryPayload>('/summary/daily/refresh');
  return data;
}
