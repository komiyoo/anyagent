import ReactMarkdown from "react-markdown";

type MarkdownMessageProps = {
  content: string;
};

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function highlightCode(source: string, language: string) {
  const escaped = escapeHtml(source.trimEnd());
  if (["json", "jsonc", "yaml", "yml"].includes(language)) {
    return escaped.replace(/(&quot;[^&]+?&quot;)(\s*:)?/g, (_match, key: string, colon: string) =>
      colon ? `<span class="token-key">${key}</span>${colon}` : `<span class="token-string">${key}</span>`,
    );
  }
  if (["ts", "tsx", "js", "jsx", "python", "py", "bash", "sh"].includes(language)) {
    return escaped
      .replace(/\b(import|from|export|const|let|function|return|async|await|if|else|for|while|class|def|try|catch|finally)\b/g, '<span class="token-keyword">$1</span>')
      .replace(/(&quot;.*?&quot;|'.*?'|`.*?`)/g, '<span class="token-string">$1</span>')
      .replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="token-number">$1</span>');
  }
  return escaped;
}

type CodeProps = {
  children?: unknown;
  className?: string;
};

function Code({ children, className = "" }: CodeProps) {
  const text = String(children ?? "");
  const language = className.replace("language-", "");
  if (!language) {
    return <code>{text}</code>;
  }
  return (
    <pre className="markdown-code">
      <code dangerouslySetInnerHTML={{ __html: highlightCode(text, language) }} />
    </pre>
  );
}

export function MarkdownMessage({ content }: MarkdownMessageProps) {
  return (
    <div className="markdown-message">
      <ReactMarkdown
        components={{
          code({ children, className }) {
            return <Code className={className}>{children}</Code>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
