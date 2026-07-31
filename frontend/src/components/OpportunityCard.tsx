import { useEffect, useState } from 'react';
import { Card, List, Tag, Typography, Spin, Empty, Space, Button, Grid } from 'antd';
import { FireOutlined, ReloadOutlined, RightOutlined, RiseOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';

const { useBreakpoint } = Grid;

interface Candidate {
  code: string;
  name: string;
  score: number;
  reasons: string[];
  price: number | null;
  target_price: number | null;
}

interface OpportunityData {
  date: string | null;
  candidates: Candidate[];
  ai_evaluation: string;
  generated_at: string | null;
}

function formatAiLines(text: string): string[] {
  if (!text) return [];
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
}

export default function OpportunityCard() {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const navigate = useNavigate();
  const [data, setData] = useState<OpportunityData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data: d } = await api.get<OpportunityData>('/summary/opportunities');
      setData(d);
    } catch {
      setError('加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const triggerScan = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data: d } = await api.post<OpportunityData>('/summary/opportunities/scan');
      setData(d);
    } catch {
      setError('扫描失败');
    } finally {
      setLoading(false);
    }
  };

  const title = (
    <Space size={8}>
      <FireOutlined style={{ color: '#fa541c' }} />
      <span>关注机会</span>
      {data?.date && (
        <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>
          {data.date} 更新
        </Typography.Text>
      )}
    </Space>
  );

  const extra = (
    <Space size={4}>
      <Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading} />
      <Button size="small" type="link" onClick={triggerScan} loading={loading}>
        手动扫描
      </Button>
    </Space>
  );

  return (
    <Card
      size="small"
      title={title}
      extra={extra}
      style={{ marginTop: 16, marginBottom: 16 }}
    >
      <Spin spinning={loading}>
        {error ? (
          <Typography.Text type="danger">{error}</Typography.Text>
        ) : !data || data.candidates.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="暂无买入机会，点击「手动扫描」立即分析"
          />
        ) : (
          <>
            <List
              size="small"
              dataSource={data.candidates}
              renderItem={(item) => (
                <List.Item
                  style={{
                    cursor: 'pointer',
                    flexWrap: 'wrap',
                    padding: isMobile ? '8px 0' : undefined,
                  }}
                  onClick={() => navigate(`/stock/${item.code}`)}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      width: '100%',
                      flexWrap: 'wrap',
                    }}
                  >
                    <Space size={4}>
                      <RiseOutlined style={{ color: '#fa541c', fontSize: isMobile ? 12 : 14 }} />
                      <Typography.Text strong style={{ fontSize: isMobile ? 13 : 14 }}>
                        {item.name}
                      </Typography.Text>
                      <Typography.Text code style={{ fontSize: 11 }}>
                        {item.code}
                      </Typography.Text>
                    </Space>
                    {item.price != null && (
                      <Typography.Text style={{ fontSize: 12 }}>
                        ¥{item.price.toFixed(2)}
                      </Typography.Text>
                    )}
                    <Space size={2} wrap style={{ flex: 1, justifyContent: 'flex-end' }}>
                      {item.reasons.slice(0, 3).map((r) => (
                        <Tag key={r} color="orange" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', marginInlineEnd: 0 }}>
                          {r}
                        </Tag>
                      ))}
                      <RightOutlined style={{ color: '#bbb', fontSize: 10, marginLeft: 4 }} />
                    </Space>
                  </div>
                </List.Item>
              )}
            />
            {data.ai_evaluation && (
              <div
                style={{
                  marginTop: 10,
                  padding: '8px 12px',
                  background: '#fffbe6',
                  borderRadius: 6,
                  fontSize: 12,
                  lineHeight: 1.7,
                  color: '#595959',
                }}
              >
                <Typography.Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
                  🤖 AI 评估
                </Typography.Text>
                {formatAiLines(data.ai_evaluation).map((line, i) => (
                  <div key={i}>{line}</div>
                ))}
              </div>
            )}
          </>
        )}
      </Spin>
    </Card>
  );
}
