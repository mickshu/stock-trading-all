import { useEffect, useRef, useState } from 'react';
import { Button, Space, Tooltip } from 'antd';
import { SoundOutlined, PauseCircleOutlined, BorderOutlined } from '@ant-design/icons';
import { useSpeech } from '../hooks/useSpeech';
import { mdToText } from '../utils/mdToText';

interface Props {
  text?: string;
  getText?: () => Promise<string>;
  disabled?: boolean;
  size?: 'small' | 'middle' | 'large';
}

export default function SpeechButton({ text, getText, disabled, size = 'small' }: Props) {
  const { status, speak, pause, resume, stop } = useSpeech();
  const [loading, setLoading] = useState(false);
  const cachedRef = useRef('');

  useEffect(() => {
    return () => stop();
  }, [stop]);

  useEffect(() => {
    if (text) cachedRef.current = text;
  }, [text]);

  const handleClick = async () => {
    if (status === 'idle') {
      let md = cachedRef.current;
      if (!md && getText) {
        setLoading(true);
        try {
          md = await getText();
          cachedRef.current = md;
        } finally {
          setLoading(false);
        }
      }
      if (md) speak(mdToText(md));
    } else if (status === 'speaking') {
      pause();
    } else {
      resume();
    }
  };

  const icon = status === 'speaking' ? <PauseCircleOutlined /> : <SoundOutlined />;
  const label = status === 'idle' ? '播报' : status === 'speaking' ? '暂停' : '继续';
  const isDisabled = disabled || (!text && !getText);

  return (
    <Space size={0}>
      <Tooltip title={label}>
        <Button
          type="link"
          size={size}
          icon={icon}
          disabled={isDisabled}
          loading={loading}
          onClick={handleClick}
          style={status !== 'idle' ? { color: '#1677ff' } : undefined}
        >
          {label}
        </Button>
      </Tooltip>
      {status !== 'idle' && (
        <Tooltip title="停止">
          <Button type="link" size={size} icon={<BorderOutlined />} onClick={stop} danger />
        </Tooltip>
      )}
    </Space>
  );
}
