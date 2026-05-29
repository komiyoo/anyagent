import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Clipboard } from "lucide-react";

type MarkdownMessageProps = {
  content: string;
  isStreaming?: boolean;
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
    return escaped.replace(
      /(&quot;[^&]+?&quot;)(\s*:)?/g,
      (_m, key: string, colon: string) =>
        colon
          ? `<span class="token-key">${key}</span>${colon}`
          : `<span class="token-string">${key}</span>`,
    );
  }
  if (["ts","tsx","js","jsx","python","py","bash","sh"].includes(language)) {
    return escaped
      .replace(/(\/\/.*)/g, '<span class="token-comment">$1</span>')
      .replace(
        /\b(import|from|export|const|let|function|return|async|await|if|else|for|while|class|def|try|catch|finally|throw|new|type|interface)\b/g,
        '<span class="token-keyword">$1</span>',
      )
      .replace(
        /(&quot;.*?&quot;|'.*?'|`.*?`)/g,
        '<span class="token-string">$1</span>',
      )
      .replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="token-number">$1</span>');
  }
  return escaped;
}

function CodeBlock({ children, language }: { children: string; language: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(children.trimEnd());
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="code-block-wrap">
      <div className="code-block-header">
        <span className="code-block-lang">{language || "text"}</span>
        <button type="button" className="code-block-copy" onClick={handleCopy} title="Copy code">
          {copied ? <Check size={13} /> : <Clipboard size={13} />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <pre className="markdown-code">
        <code dangerouslySetInnerHTML={{ __html: highlightCode(children, language) }} />
      </pre>
    </div>
  );
}

type CodeProps = {
  children?: unknown;
  className?: string;
};

function Code({ children, className = "" }: CodeProps) {
  const text = String(children ?? "").replace(/\n$/, "");
  const language = className.replace("language-", "");
  if (!language) {
    return <code className="inline-code">{text}</code>;
  }
  return <CodeBlock language={language}>{text}</CodeBlock>;
}

export function MarkdownMessage({ content, isStreaming }: MarkdownMessageProps) {
  return (
    <div className={`markdown-message ${isStreaming ? "streaming" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ children, className }) {
            return <Code className={className}>{children}</Code>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
      {isStreaming && <span className="streaming-cursor" />}
    </div>
  );
}
