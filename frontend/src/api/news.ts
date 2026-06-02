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
  /** true = 返回的是 stale cache，后端已异步刷新；前端宜数秒后轮询。 */
  stale?: boolean;
  /** ISO（含 +08:00），首次启动且无缓存时可能为 null。 */
  refreshed_at?: string | null;
}

export async function fetchWatchlistNews(opts: {
  timeRange: NewsTimeRange;
  codes?: string[];
  limit?: number;
}): Promise<WatchlistNewsResponse> {
  const params: Record<string, string | number> = { time_range: opts.timeRange };
  if (opts.codes && opts.codes.length > 0) params.codes = opts.codes.join(',');
  if (opts.limit) params.limit = opts.limit;
  // 冷缓存场景下 akshare 多源聚合即使已并发也可能 10-30s，覆盖默认 30s 超时以避免「已取消」
  const { data } = await api.get<WatchlistNewsResponse>('/news/watchlist', {
    params,
    timeout: 90000,
  });
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
