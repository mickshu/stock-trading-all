import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { CSSProperties } from 'react';

interface Props {
  content: string;
  fontSize?: number;
  style?: CSSProperties;
}

/** AI 输出统一的 markdown 渲染器：支持 GFM 表格 / 列表 / 引用 / 链接。 */
export default function MarkdownView({ content, fontSize = 13, style }: Props) {
  return (
    <div className="md-view" style={{ fontSize, lineHeight: 1.7, ...style }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div style={{ overflowX: 'auto', margin: '8px 0' }}>
              <table
                style={{
                  borderCollapse: 'collapse',
                  width: '100%',
                  fontSize: fontSize - 1,
                }}
              >
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th
              style={{
                border: '1px solid #e4e4e7',
                padding: '6px 10px',
                background: '#fafafa',
                textAlign: 'left',
                fontWeight: 600,
              }}
            >
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td style={{ border: '1px solid #e4e4e7', padding: '6px 10px' }}>{children}</td>
          ),
          blockquote: ({ children }) => (
            <blockquote
              style={{
                borderLeft: '3px solid #d4d4d8',
                margin: '8px 0',
                padding: '4px 12px',
                color: '#52525b',
                background: '#fafafa',
              }}
            >
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }) => {
            const inline = !className;
            if (inline) {
              return (
                <code
                  style={{
                    background: '#f4f4f5',
                    padding: '1px 5px',
                    borderRadius: 3,
                    fontSize: fontSize - 1,
                  }}
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <pre
                style={{
                  background: '#f4f4f5',
                  padding: 10,
                  borderRadius: 4,
                  overflowX: 'auto',
                  fontSize: fontSize - 1,
                }}
              >
                <code {...props}>{children}</code>
              </pre>
            );
          },
          h1: ({ children }) => (
            <h3 style={{ fontSize: fontSize + 4, margin: '12px 0 6px' }}>{children}</h3>
          ),
          h2: ({ children }) => (
            <h4 style={{ fontSize: fontSize + 2, margin: '10px 0 6px' }}>{children}</h4>
          ),
          h3: ({ children }) => (
            <h5 style={{ fontSize: fontSize + 1, margin: '8px 0 4px' }}>{children}</h5>
          ),
          ul: ({ children }) => (
            <ul style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ul>
          ),
          ol: ({ children }) => (
            <ol style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ol>
          ),
          p: ({ children }) => <p style={{ margin: '6px 0' }}>{children}</p>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
