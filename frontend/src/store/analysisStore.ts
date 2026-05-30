import { create } from 'zustand';
import type { KlineData, IndicatorData, Signal, Period } from '../types';
import { fetchAnalysis } from '../api/analysis';

interface AnalysisState {
  klineData: (KlineData & Partial<IndicatorData>)[];
  signals: Signal[];
  period: Period;
  loading: boolean;
  error: string | null;
  showMA: boolean;
  showMACD: boolean;
  showKDJ: boolean;
  showRSI: boolean;
  showSignals: boolean;
  highlightPosition: number | null;
  setPeriod: (period: Period) => void;
  setShowMA: (show: boolean) => void;
  setShowMACD: (show: boolean) => void;
  setShowKDJ: (show: boolean) => void;
  setShowRSI: (show: boolean) => void;
  setShowSignals: (show: boolean) => void;
  setHighlightPosition: (pos: number | null) => void;
  loadAnalysis: (code: string, forceRefresh?: boolean) => Promise<void>;
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  klineData: [],
  signals: [],
  period: 'daily',
  loading: false,
  error: null,
  showMA: true,
  showMACD: false,
  showKDJ: false,
  showRSI: false,
  showSignals: true,
  highlightPosition: null,

  setPeriod: (period) => set({ period }),
  setShowMA: (show) => set({ showMA: show }),
  setShowMACD: (show) => set({ showMACD: show }),
  setShowKDJ: (show) => set({ showKDJ: show }),
  setShowRSI: (show) => set({ showRSI: show }),
  setShowSignals: (show) => set({ showSignals: show }),
  setHighlightPosition: (pos) => set({ highlightPosition: pos }),

  loadAnalysis: async (code, forceRefresh = false) => {
    set({ loading: true, error: null });
    try {
      const { period } = get();
      const resp = await fetchAnalysis(code, period, 'MACD,MA,KDJ,RSI', forceRefresh);
      set({ klineData: resp.kline, signals: resp.signals, loading: false });
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      const msg = detail || (e instanceof Error ? e.message : 'Failed to load analysis');
      set({ error: msg, loading: false, klineData: [], signals: [] });
    }
  },
}));
