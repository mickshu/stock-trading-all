import api from './client';
import type { StockInfo, WatchlistGroup, SystemTag, SystemTagInfo } from '../types';

export interface ListWatchlistOptions {
  groupId?: number | null;
  ungrouped?: boolean;
  tag?: SystemTag;
}

export async function fetchWatchlist(options: ListWatchlistOptions = {}): Promise<StockInfo[]> {
  const params: Record<string, string | number | boolean | undefined> = {};
  if (options.tag) {
    params.tag = options.tag;
  } else if (options.ungrouped) {
    params.ungrouped = true;
  } else if (options.groupId != null) {
    params.group_id = options.groupId;
  }
  const { data } = await api.get<StockInfo[]>('/stocks', { params });
  return data;
}

export async function addStock(
  code: string,
  name = '',
  market = 'A',
  groupId?: number | null,
  tags?: SystemTag[],
): Promise<StockInfo> {
  const params: Record<string, string | number | undefined> = { code, name, market };
  if (groupId != null) params.group_id = groupId;
  if (tags && tags.length > 0) params.tags = tags.join(',');
  const { data } = await api.post<StockInfo>('/stocks', null, { params });
  return data;
}

export async function deleteStock(id: number): Promise<void> {
  await api.delete(`/stocks/${id}`);
}

export async function searchStocks(q: string): Promise<{ query: string; results: StockInfo[] }> {
  const { data } = await api.get<{ query: string; results: StockInfo[] }>('/stocks/search', {
    params: { q },
  });
  return data;
}

export interface GroupsResponse {
  groups: WatchlistGroup[];
  ungrouped_count: number;
  system_tags: SystemTagInfo[];
}

export async function fetchGroups(): Promise<GroupsResponse> {
  const { data } = await api.get<GroupsResponse>('/stocks/groups');
  return data;
}

export async function createGroup(name: string): Promise<WatchlistGroup> {
  const { data } = await api.post<WatchlistGroup>('/stocks/groups', { name });
  return data;
}

export async function renameGroup(id: number, name: string): Promise<WatchlistGroup> {
  const { data } = await api.patch<WatchlistGroup>(`/stocks/groups/${id}`, { name });
  return data;
}

export async function deleteGroup(id: number): Promise<void> {
  await api.delete(`/stocks/groups/${id}`);
}

export async function reorderGroups(ids: number[]): Promise<void> {
  await api.put('/stocks/groups/order', { ids });
}

export async function setStockGroup(stockId: number, groupId: number | null): Promise<StockInfo> {
  const { data } = await api.patch<StockInfo>(`/stocks/${stockId}`, { group_id: groupId });
  return data;
}

export async function setStockTags(stockId: number, tags: SystemTag[]): Promise<StockInfo> {
  const { data } = await api.patch<StockInfo>(`/stocks/${stockId}`, { tags });
  return data;
}

export interface DataSourceInfo {
  active: string;
  available: string[];
}

export async function fetchDataSources(): Promise<DataSourceInfo> {
  const { data } = await api.get<DataSourceInfo>('/data-sources');
  return data;
}

export async function switchDataSource(source: string): Promise<{ active: string }> {
  const { data } = await api.post<{ active: string }>('/data-sources/switch', null, {
    params: { source },
  });
  return data;
}
