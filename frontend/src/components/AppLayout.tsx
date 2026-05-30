import { useState } from 'react';
import { Layout, Menu, Typography, Grid } from 'antd';
import {
  BarChartOutlined,
  StarOutlined,
  SearchOutlined,
  SettingOutlined,
  DeploymentUnitOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';

const { Sider, Header, Content } = Layout;
const { useBreakpoint } = Grid;

const menuItems = [
  { key: '/', icon: <BarChartOutlined />, label: '行情' },
  { key: '/stocks', icon: <StarOutlined />, label: '自选' },
  { key: '/screener', icon: <SearchOutlined />, label: '选股' },
  { key: '/trading-agents', icon: <DeploymentUnitOutlined />, label: 'AI 分析' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const screens = useBreakpoint();
  const isMobile = !screens.lg;

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {!isMobile && (
        <Sider
          breakpoint="lg"
          collapsedWidth={80}
          collapsible
          collapsed={collapsed}
          onCollapse={(value) => setCollapsed(value)}
        >
          <Typography.Title
            level={5}
            style={{ color: 'white', textAlign: 'center', margin: '16px 0' }}
          >
            {collapsed ? 'AI' : 'AI 股票分析'}
          </Typography.Title>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[location.pathname]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
          />
        </Sider>
      )}
      <Layout style={{ paddingBottom: isMobile ? 56 : 0 }}>
        {isMobile && (
          <Header
            style={{
              position: 'sticky',
              top: 0,
              zIndex: 10,
              background: '#fff',
              borderBottom: '1px solid #f0f0f0',
              padding: '8px 12px',
              height: 48,
              lineHeight: 'normal',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <Typography.Text strong style={{ fontSize: 14, whiteSpace: 'nowrap' }}>
              AI 股票
            </Typography.Text>
          </Header>
        )}
        <Content
          style={{
            margin: isMobile ? 0 : 16,
            padding: isMobile ? 12 : 24,
            background: isMobile ? '#f5f5f5' : '#fff',
            borderRadius: isMobile ? 0 : 8,
            minHeight: 'calc(100vh - 48px)',
          }}
        >
          <Outlet />
        </Content>
      </Layout>

      {isMobile && (
        <div
          style={{
            position: 'fixed',
            bottom: 0,
            left: 0,
            right: 0,
            height: 56,
            background: '#fff',
            borderTop: '1px solid #f0f0f0',
            display: 'flex',
            justifyContent: 'space-around',
            alignItems: 'center',
            zIndex: 100,
            boxShadow: '0 -2px 8px rgba(0,0,0,0.06)',
          }}
        >
          {menuItems.map((item) => {
            const active = location.pathname === item.key;
            return (
              <div
                key={item.key}
                onClick={() => navigate(item.key)}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 2,
                  cursor: 'pointer',
                  color: active ? '#1677ff' : '#999',
                  fontSize: 10,
                  flex: 1,
                  padding: '4px 0',
                  transition: 'color 0.2s',
                }}
              >
                <span style={{ fontSize: 20 }}>{item.icon}</span>
                <span>{item.label}</span>
              </div>
            );
          })}
        </div>
      )}
    </Layout>
  );
}
