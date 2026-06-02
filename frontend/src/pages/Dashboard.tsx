import { useState, useEffect, useCallback } from 'react';
import { Card, Row, Col, Statistic, Typography, Empty, Button, Result, Grid } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined } from '@ant-design/icons';
import type { IndexData } from '../types';
import { fetchIndices } from '../api/market';
import FundFlowTabsCard from '../components/FundFlowTabsCard';
import DailySummaryCard from '../components/DailySummaryCard';

const { useBreakpoint } = Grid;

export default function Dashboard() {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [indices, setIndices] = useState<IndexData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchIndices()
      .then((data) => {
        setIndices(data);
        if (data.length === 0) setError('暂无指数数据，数据源可能不可用');
      })
      .catch(() => setError('加载指数数据失败'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: isMobile ? 12 : 16 }}>
        <Col>
          <Typography.Title level={4} style={{ margin: 0 }}>行情总览</Typography.Title>
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading} size={isMobile ? 'small' : 'middle'}>
            刷新
          </Button>
        </Col>
      </Row>

      {loading && indices.length === 0 ? (
        <Row gutter={[12, 12]}>
          {[1, 2, 3, 4].map((i) => (
            <Col xs={12} sm={12} md={6} key={i}>
              <Card loading style={{ minHeight: 100 }} />
            </Col>
          ))}
        </Row>
      ) : error && indices.length === 0 ? (
        <Result
          status="warning"
          title="指数数据不可用"
          subTitle={error}
          extra={
            <Button type="primary" icon={<ReloadOutlined />} onClick={load} loading={loading}>
              重试
            </Button>
          }
        />
      ) : indices.length === 0 ? (
        <Empty description="暂无指数数据" />
      ) : (
        <Row gutter={[12, 12]}>
          {indices.map((idx) => (
            <Col xs={12} sm={12} md={6} key={idx.code}>
              <Card size="small" styles={{ body: { padding: isMobile ? '12px 12px' : undefined } }}>
                <Statistic
                  title={<span style={{ fontSize: isMobile ? 12 : 14 }}>{idx.name}</span>}
                  value={idx.price}
                  precision={2}
                  styles={{
                    content: {
                      color: idx.change_pct >= 0 ? '#cf1322' : '#3f8600',
                      fontSize: isMobile ? 18 : 22,
                    },
                  }}
                  prefix={idx.change_pct >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                  suffix={
                    <span style={{ fontSize: isMobile ? 11 : 14, fontWeight: 500 }}>
                      {idx.change_pct >= 0 ? '+' : ''}{idx.change_pct.toFixed(2)}%
                    </span>
                  }
                />
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <FundFlowTabsCard />
      <DailySummaryCard />
    </div>
  );
}
