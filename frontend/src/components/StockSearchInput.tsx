import { useEffect, useRef, useState } from 'react';
import { AutoComplete, Space, Tag, Typography, message } from 'antd';
import type { CSSProperties } from 'react';
import { searchStocks } from '../api/stocks';
import type { StockInfo } from '../types';

export interface StockSearchInputProps {
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  onSelect?: (stock: StockInfo) => void;
  onResultsChange?: (results: StockInfo[]) => void;
  placeholder?: string;
  style?: CSSProperties;
  size?: 'small' | 'middle' | 'large';
  allowClear?: boolean;
  autoFocus?: boolean;
  disabled?: boolean;
  debounceMs?: number;
  popupMatchSelectWidth?: boolean | number;
}

const DEFAULT_PLACEHOLDER = '输入代码 / 名称 / 拼音，如 600519 / 茅台 / mt';

export default function StockSearchInput({
  value,
  defaultValue = '',
  onChange,
  onSelect,
  onResultsChange,
  placeholder = DEFAULT_PLACEHOLDER,
  style,
  size = 'middle',
  allowClear = true,
  autoFocus,
  disabled,
  debounceMs = 250,
  popupMatchSelectWidth = true,
}: StockSearchInputProps) {
  const controlled = value !== undefined;
  const [inner, setInner] = useState(defaultValue);
  const text = controlled ? (value ?? '') : inner;

  const [results, setResults] = useState<StockInfo[]>([]);
  const [searching, setSearching] = useState(false);
  const debounceRef = useRef<number | null>(null);
  const seqRef = useRef(0);

  useEffect(() => {
    return () => {
      if (debounceRef.current != null) window.clearTimeout(debounceRef.current);
    };
  }, []);

  const applyResults = (r: StockInfo[]) => {
    setResults(r);
    onResultsChange?.(r);
  };

  const runSearch = (term: string) => {
    const trimmed = term.trim();
    if (!trimmed) {
      applyResults([]);
      setSearching(false);
      return;
    }
    const seq = ++seqRef.current;
    setSearching(true);
    searchStocks(trimmed)
      .then(({ results: r }) => {
        if (seq === seqRef.current) applyResults(r);
      })
      .catch(() => {
        if (seq === seqRef.current) message.error('搜索失败');
      })
      .finally(() => {
        if (seq === seqRef.current) setSearching(false);
      });
  };

  const handleChange = (next: string) => {
    if (!controlled) setInner(next);
    onChange?.(next);
    if (debounceRef.current != null) window.clearTimeout(debounceRef.current);
    if (!next.trim()) {
      applyResults([]);
      setSearching(false);
      return;
    }
    debounceRef.current = window.setTimeout(() => runSearch(next), debounceMs);
  };

  const handleSelect = (picked: string) => {
    const stock = results.find((s) => s.code === picked);
    if (!stock) return;
    onSelect?.(stock);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return;
    if (!text.trim() || results.length === 0) return;
    e.preventDefault();
    onSelect?.(results[0]);
  };

  return (
    <AutoComplete
      value={text}
      onChange={handleChange}
      onSelect={handleSelect}
      onInputKeyDown={handleKeyDown}
      placeholder={placeholder}
      style={{ width: '100%', ...style }}
      size={size}
      allowClear={allowClear}
      autoFocus={autoFocus}
      disabled={disabled}
      popupMatchSelectWidth={popupMatchSelectWidth}
      notFoundContent={
        searching ? '搜索中…' : text.trim() ? '未找到匹配结果' : null
      }
      options={results.map((s) => ({
        value: s.code,
        label: (
          <Space size={6}>
            <Tag style={{ marginRight: 0 }}>{s.code}</Tag>
            <span>{s.name}</span>
            {s.market && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                [{s.market}]
              </Typography.Text>
            )}
          </Space>
        ),
      }))}
    />
  );
}
