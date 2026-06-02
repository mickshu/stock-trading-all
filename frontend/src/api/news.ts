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

export interface NewsSettings {
  prompt: string;
  default_prompt: string;
  sources: string[];
  available_sources: string[];
  default_sources: string[];
}

export async function fetchNewsSettings(): Promise<NewsSettings> {
  const { data } = await api.get<NewsSettings>('/settings/news');
  return data;
}

export async function saveNewsSettings(payload: {
  prompt?: string;
  sources?: string[];
}): Promise<NewsSettings> {
  const { data } = await api.put<NewsSettings>('/settings/news', payload);
  return data;
}

export async function resetNewsPrompt(): Promise<NewsSettings> {
  const { data } = await api.post<NewsSettings>('/settings/news/reset-prompt');
  return data;
}

export interface AiDigestResponse {
  codes: string[];
  prompt: string;
  model: string;
  content: string;
  sources: string[];
  generated_at: string;
}

export async function fetchAiDigest(payload: {
  codes?: string[];
  prompt?: string;
}): Promise<AiDigestResponse> {
  const { data } = await api.post<AiDigestResponse>('/news/ai-digest', payload, {
    timeout: 360000,
  });
  return data;
}
