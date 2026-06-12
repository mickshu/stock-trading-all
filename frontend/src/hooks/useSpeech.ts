import { useCallback, useEffect, useRef, useState } from 'react';

export type SpeechStatus = 'idle' | 'speaking' | 'paused';

const MAX_CHUNK = 200;

function pickVoice(): SpeechSynthesisVoice | null {
  const voices = speechSynthesis.getVoices();
  return (
    voices.find((v) => v.lang === 'zh-CN') ??
    voices.find((v) => v.lang.startsWith('zh')) ??
    null
  );
}

function splitChunks(text: string): string[] {
  const paragraphs = text.split(/\n+/).filter((p) => p.trim());
  const chunks: string[] = [];
  for (const p of paragraphs) {
    if (p.length <= MAX_CHUNK) {
      chunks.push(p);
    } else {
      const sentences = p.split(/(?<=[。！？；\n])/);
      let buf = '';
      for (const s of sentences) {
        if (buf.length + s.length > MAX_CHUNK && buf) {
          chunks.push(buf);
          buf = '';
        }
        buf += s;
      }
      if (buf) chunks.push(buf);
    }
  }
  return chunks;
}

export function useSpeech() {
  const [status, setStatus] = useState<SpeechStatus>('idle');
  const idxRef = useRef(0);
  const chunksRef = useRef<string[]>([]);
  const activeRef = useRef(false);

  const speakNext = useCallback(() => {
    if (!activeRef.current) return;
    if (idxRef.current >= chunksRef.current.length) {
      setStatus('idle');
      activeRef.current = false;
      return;
    }
    const u = new SpeechSynthesisUtterance(chunksRef.current[idxRef.current]);
    u.lang = 'zh-CN';
    const voice = pickVoice();
    if (voice) u.voice = voice;
    u.rate = 1.1;
    u.onend = () => {
      idxRef.current++;
      speakNext();
    };
    u.onerror = () => {
      setStatus('idle');
      activeRef.current = false;
    };
    speechSynthesis.speak(u);
  }, []);

  const speak = useCallback(
    (text: string) => {
      speechSynthesis.cancel();
      chunksRef.current = splitChunks(text);
      idxRef.current = 0;
      activeRef.current = true;
      setStatus('speaking');
      speakNext();
    },
    [speakNext],
  );

  const pause = useCallback(() => {
    speechSynthesis.pause();
    setStatus('paused');
  }, []);

  const resume = useCallback(() => {
    speechSynthesis.resume();
    setStatus('speaking');
  }, []);

  const stop = useCallback(() => {
    activeRef.current = false;
    speechSynthesis.cancel();
    setStatus('idle');
  }, []);

  useEffect(() => {
    return () => {
      activeRef.current = false;
      speechSynthesis.cancel();
    };
  }, []);

  return { status, speak, pause, resume, stop };
}
