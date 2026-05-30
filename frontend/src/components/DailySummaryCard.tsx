import { useEffect, useState } from 'react';
import { Button, Card, Empty, Input, Modal, Space, Spin, Tag, Tooltip, Typography, message, Grid } from 'antd';
import { ReloadOutlined, OpenAIOutlined, SettingOutlined } from '@ant-design/icons';
import {
  fetchDailySummary,
  refreshDailySummary,
  type DailySummaryPayload,
} from '../api/summary';
import {
  fetchDailySummaryPrompt,
  resetDailySummaryPrompt,
  saveDailySummaryPrompt,
} from '../api/settings';
import MarkdownView from './MarkdownView';

const { useBreakpoint } = Grid;

export default function DailySummaryCard() {
  const screens = useBreakpoint();
  const isMobile = !screens.md;
  const [data, setData] = useState<DailySummaryPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [hint, setHint] = useState<string | null>(null);

  const [promptOpen, setPromptOpen] = useState(false);
  const [promptText, setPromptText] = useState('');
  const [promptDefault, setPromptDefault] = useState('');
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchDailySummary(false)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e) => {
        if (cancelled) return;
        const detail = (e as { response?: { data?: { detail?: string }; status?: number } })?.response?.data?.detail;
        const status = (e as { response?: { status?: number } })?.response?.status;
        if (status === 400) {
          setHint(detail || '未配置 AI');
        } else if (detail) {
          setHint(detail);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    setHint(null);
    try {
      const d = await refreshDailySummary();
      setData(d);
      message.success('已生成今日收盘总结');
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setHint(detail || '生成失败');
      message.error(detail || '生成失败');
    } finally {
      setRefreshing(false);
    }
  };

  const openPromptEditor = async () => {
    setPromptOpen(true);
    setPromptLoading(true);
    try {
      const r = await fetchDailySummaryPrompt();
      setPromptText(r.prompt);
      setPromptDefault(r.default);
    } catch {
      message.error('读取提示词失败');
    } finally {
      setPromptLoading(false);
    }
  };

  const handleSavePrompt = async () => {
    const text = promptText.trim();
    if (!text) {
      message.warning('提示词不能为空');
      return;
    }
    setPromptSaving(true);
    try {
      const r = await saveDailySummaryPrompt(text);
      setPromptText(r.prompt);
      message.success('提示词已保存');
      setPromptOpen(false);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || '保存失败');
    } finally {
      setPromptSaving(false);
    }
  };

  const handleResetPrompt = async () => {
    setPromptSaving(true);
    try {
      const r = await resetDailySummaryPrompt();
      setPromptText(r.prompt);
      setPromptDefault(r.default);
      message.success('已恢复默认提示词');
    } catch {
      message.error('重置失败');
    } finally {
      setPromptSaving(false);
    }
  };

  return (
    <Card
      size="small"
      title={
        <Space wrap size={6}>
          <OpenAIOutlined />
          <span>AI 收盘总结</span>
          {data?.model && <Tag color="purple" style={{ marginRight: 0 }}>{data.model}</Tag>}
        </Space>
      }
      extra={
        <Space size={4}>
          <Tooltip title="修改默认提示词">
            <Button
              icon={<SettingOutlined />}
              size="small"
              type="text"
              onClick={openPromptEditor}
            />
          </Tooltip>
          <Button
            icon={<ReloadOutlined />}
            size="small"
            loading={refreshing}
            onClick={handleRefresh}
          >
            {data ? '重新生成' : '生成'}
          </Button>
        </Space>
      }
      style={{ marginTop: isMobile ? 12 : 16 }}
    >
      <Spin spinning={loading || refreshing}>
        {data ? (
          <>
            <MarkdownView content={data.content} />
            {!isMobile && data.sources && data.sources.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  信息来源：
                </Typography.Text>
                <ul style={{ marginTop: 4, paddingLeft: 18 }}>
                  {data.sources.map((u) => (
                    <li key={u}>
                      <a href={u} target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
                        {u}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <Empty description={hint || '点击「生成」获取今日总结'} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Spin>

      <Modal
        title="收盘总结 · 默认提示词"
        open={promptOpen}
        onCancel={() => setPromptOpen(false)}
        onOk={handleSavePrompt}
        confirmLoading={promptSaving}
        okText="保存"
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        <Spin spinning={promptLoading}>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
            该提示词会随系统注入的「当日数据」一起发送给本地 Hermes Agent。
          </Typography.Paragraph>
          <Input.TextArea
            value={promptText}
            onChange={(e) => setPromptText(e.target.value)}
            autoSize={{ minRows: 10, maxRows: 18 }}
            placeholder={promptDefault}
          />
          <div style={{ marginTop: 8, textAlign: 'right' }}>
            <Button size="small" type="link" onClick={handleResetPrompt} loading={promptSaving}>
              恢复默认
            </Button>
          </div>
        </Spin>
      </Modal>
    </Card>
  );
}
