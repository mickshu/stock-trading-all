import api from './client';

export type NewsTimeRange = 'today' | 'week' | 'all';

export interface NewsItem {
  id: string;
  title: string;
  summary: string;
  url: string | null;
  sources: string[];
  published_at: string;
  related_codes: string[];
  related_names: string[];
  hot_score: number;
}

export interface WatchlistNewsResponse {
  time_range: NewsTimeRange;
  codes: string[];
  count: number;
  items: NewsItem[];
}

export async function fetchWatchlistNews(opts: {
  timeRange: NewsTimeRange;
  codes?: string[];
  limit?: number;
}): Promise<WatchlistNewsResponse> {
  const params: Record<string, string | number> = { time_range: opts.timeRange };
  if (opts.codes && opts.codes.length > 0) params.codes = opts.codes.join(',');
  if (opts.limit) params.limit = opts.limit;
  const { data } = await api.get<WatchlistNewsResponse>('/news/watchlist', { params });
  return data;
}
