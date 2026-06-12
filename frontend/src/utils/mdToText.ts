export function mdToText(md: string): string {
  return (
    md
      // code blocks
      .replace(/```[\s\S]*?```/g, '')
      .replace(/`([^`]+)`/g, '$1')
      // images
      .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
      // links — keep text
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      // headings
      .replace(/^#{1,6}\s+/gm, '')
      // bold / italic
      .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
      .replace(/_{1,3}([^_]+)_{1,3}/g, '$1')
      // strikethrough
      .replace(/~~([^~]+)~~/g, '$1')
      // blockquote
      .replace(/^>\s?/gm, '')
      // horizontal rule
      .replace(/^[-*_]{3,}\s*$/gm, '')
      // table separator rows
      .replace(/^\|[-:\s|]+\|$/gm, '')
      // table pipes
      .replace(/\|/g, ' ')
      // html tags
      .replace(/<[^>]+>/g, '')
      // collapse whitespace
      .replace(/[ \t]+/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  );
}
