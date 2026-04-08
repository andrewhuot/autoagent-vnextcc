import { useState, useCallback } from 'react';
import { Check, Clock, FileText, Plus, Save } from 'lucide-react';
import { classNames, formatTimestamp } from '../../lib/utils';
import type { SpecVersion } from './studio-types';
import { MOCK_SPEC_CONTENT, MOCK_SPEC_VERSIONS } from './studio-mock';
import { toastSuccess } from '../../lib/toast';

// ─── Minimal markdown → HTML renderer ────────────────────────────────────────

function renderMarkdownPreview(md: string): string {
  const lines = md.split('\n');
  const out: string[] = [];
  let inList = false;

  for (const raw of lines) {
    const line = raw;
    if (line.startsWith('# ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h1 class="text-xl font-semibold text-gray-900 mt-4 mb-2">${esc(line.slice(2))}</h1>`);
    } else if (line.startsWith('## ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h2 class="text-base font-semibold text-gray-800 mt-4 mb-1.5 border-b border-gray-100 pb-1">${esc(line.slice(3))}</h2>`);
    } else if (line.startsWith('### ')) {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<h3 class="text-sm font-semibold text-gray-700 mt-3 mb-1">${esc(line.slice(4))}</h3>`);
    } else if (line.startsWith('- ')) {
      if (!inList) { out.push('<ul class="space-y-1 ml-3 my-1.5">'); inList = true; }
      const content = inlineFormat(line.slice(2));
      out.push(`<li class="flex gap-2 text-sm text-gray-700"><span class="text-indigo-400 mt-0.5 shrink-0">•</span><span>${content}</span></li>`);
    } else if (line.trim() === '') {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push('<div class="h-2"></div>');
    } else {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<p class="text-sm text-gray-700 leading-relaxed">${inlineFormat(line)}</p>`);
    }
  }
  if (inList) out.push('</ul>');
  return out.join('\n');
}

function esc(str: string): string {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function inlineFormat(str: string): string {
  return esc(str)
    .replace(/`([^`]+)`/g, '<code class="rounded bg-gray-100 px-1 py-0.5 font-mono text-xs text-indigo-700">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold">$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

// ─── Version History Rail ─────────────────────────────────────────────────────

interface VersionRailProps {
  versions: SpecVersion[];
  activeVersionId: string;
  onSelect: (v: SpecVersion) => void;
}

function VersionRail({ versions, activeVersionId, onSelect }: VersionRailProps) {
  const statusStyles: Record<SpecVersion['status'], string> = {
    draft: 'bg-amber-100 text-amber-700',
    published: 'bg-green-100 text-green-700',
    archived: 'bg-gray-100 text-gray-500',
  };

  return (
    <div className="flex h-full flex-col border-l border-gray-200 bg-gray-50">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          Version History
        </span>
        <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-medium text-indigo-700">
          {versions.length}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {versions.map((v) => (
          <button
            key={v.version_id}
            onClick={() => onSelect(v)}
            className={classNames(
              'w-full border-b border-gray-100 px-4 py-3 text-left transition-colors hover:bg-white',
              activeVersionId === v.version_id ? 'bg-white shadow-[inset_2px_0_0_0_#6366f1]' : ''
            )}
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-800">v{v.version_number}</span>
              <span className={classNames('rounded px-1.5 py-0.5 text-[10px] font-medium', statusStyles[v.status])}>
                {v.status}
              </span>
            </div>
            <p className="line-clamp-2 text-[11px] leading-relaxed text-gray-600">{v.summary}</p>
            <div className="mt-1.5 flex items-center gap-1 text-[10px] text-gray-400">
              <Clock className="h-2.5 w-2.5" />
              <span>{formatTimestamp(v.created_at)}</span>
            </div>
            <div className="mt-0.5 text-[10px] text-gray-400">{v.author}</div>
          </button>
        ))}
      </div>

      <div className="border-t border-gray-200 p-3">
        <button className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-gray-300 py-2 text-xs text-gray-500 hover:border-indigo-400 hover:text-indigo-600 transition-colors">
          <Plus className="h-3.5 w-3.5" />
          New draft from current
        </button>
      </div>
    </div>
  );
}

// ─── StudioSpec ───────────────────────────────────────────────────────────────

export function StudioSpec() {
  const [content, setContent] = useState(MOCK_SPEC_CONTENT);
  const [activeVersionId, setActiveVersionId] = useState(MOCK_SPEC_VERSIONS[0].version_id);
  const [previewMode, setPreviewMode] = useState<'split' | 'preview'>('split');
  const [saved, setSaved] = useState(false);

  const handleVersionSelect = useCallback((v: SpecVersion) => {
    setContent(v.content);
    setActiveVersionId(v.version_id);
  }, []);

  const handleSave = () => {
    setSaved(true);
    toastSuccess('Draft saved');
    setTimeout(() => setSaved(false), 2000);
  };

  const handlePublish = () => {
    toastSuccess('Version published — ready for optimization');
  };

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2.5">
        <div className="flex items-center gap-1 rounded-lg bg-gray-100 p-0.5">
          {(['split', 'preview'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setPreviewMode(m)}
              className={classNames(
                'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                previewMode === m
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              {m === 'split' ? 'Split' : 'Preview'}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            className={classNames(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              saved
                ? 'bg-green-50 text-green-700'
                : 'border border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
            )}
          >
            {saved ? <Check className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
            {saved ? 'Saved' : 'Save draft'}
          </button>
          <button
            onClick={handlePublish}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 transition-colors"
          >
            <FileText className="h-3.5 w-3.5" />
            Publish version
          </button>
        </div>
      </div>

      {/* Main content: editor + preview + version rail */}
      <div className="flex flex-1 overflow-hidden">
        {/* Editor */}
        <div className={classNames('flex flex-col overflow-hidden', previewMode === 'split' ? 'w-[40%]' : 'hidden')}>
          <div className="border-b border-r border-gray-200 bg-gray-50 px-4 py-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-gray-400">Markdown</span>
          </div>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="flex-1 resize-none border-r border-gray-200 bg-gray-950 p-4 font-mono text-[13px] leading-relaxed text-green-300 outline-none placeholder:text-gray-600"
            spellCheck={false}
            placeholder="Write your agent spec in Markdown..."
          />
        </div>

        {/* Preview */}
        <div className={classNames('flex flex-col overflow-hidden', previewMode === 'split' ? 'w-[40%]' : 'flex-1')}>
          <div className="border-b border-r border-gray-200 bg-gray-50 px-4 py-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-gray-400">Preview</span>
          </div>
          <div
            className="flex-1 overflow-y-auto p-6"
            dangerouslySetInnerHTML={{ __html: renderMarkdownPreview(content) }}
          />
        </div>

        {/* Version history rail */}
        <div className="w-[20%] min-w-[180px] overflow-hidden">
          <VersionRail
            versions={MOCK_SPEC_VERSIONS}
            activeVersionId={activeVersionId}
            onSelect={handleVersionSelect}
          />
        </div>
      </div>
    </div>
  );
}
