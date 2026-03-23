import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

interface YamlViewerProps {
  content: string;
}

function highlightYamlLine(line: string): React.ReactNode {
  const commentMatch = line.match(/^(\s*)(#.*)$/);
  if (commentMatch) {
    return (
      <>
        <span>{commentMatch[1]}</span>
        <span className="text-gray-400 italic">{commentMatch[2]}</span>
      </>
    );
  }

  const keyValueMatch = line.match(/^(\s*)([\w-]+)(\s*:\s*)(.*)$/);
  if (keyValueMatch) {
    const [, indent, key, separator, value] = keyValueMatch;
    return (
      <>
        <span>{indent}</span>
        <span className="text-blue-700">{key}</span>
        <span className="text-gray-500">{separator}</span>
        <span className="text-gray-900">{value}</span>
      </>
    );
  }

  const listMatch = line.match(/^(\s*)(- )(.*)$/);
  if (listMatch) {
    return (
      <>
        <span>{listMatch[1]}</span>
        <span className="text-gray-500">{listMatch[2]}</span>
        <span className="text-gray-900">{listMatch[3]}</span>
      </>
    );
  }

  return <span>{line}</span>;
}

export function YamlViewer({ content }: YamlViewerProps) {
  const lines = content.split('\n');
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 bg-gray-50">
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2">
        <p className="text-xs font-medium uppercase tracking-wide text-gray-500">YAML</p>
        <button
          onClick={handleCopy}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-600 transition hover:bg-gray-50"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="p-4 text-sm leading-relaxed font-mono">
        {lines.map((line, i) => (
          <div key={i} className="flex">
            <span className="inline-block w-10 shrink-0 select-none pr-4 text-right text-gray-400">
              {i + 1}
            </span>
            <span>{highlightYamlLine(line)}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}
