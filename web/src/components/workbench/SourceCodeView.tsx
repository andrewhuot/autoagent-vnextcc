/**
 * Minimal syntax-highlighted source viewer.
 *
 * WHY: Avoids pulling in a full highlighter (Shiki / highlight.js) and the
 * ~200KB of bundle size that comes with them. The reference UI just needs
 * readable mono-spaced code with keywords, strings, and comments faintly
 * colored — good enough for the 5 languages the workbench actually emits.
 */

import { useMemo } from 'react';
import { classNames } from '../../lib/utils';

interface SourceCodeViewProps {
  source: string;
  language: string;
  filename?: string;
}

type Token = { type: 'text' | 'keyword' | 'string' | 'comment' | 'number'; value: string };

const PYTHON_KEYWORDS = new Set([
  'def', 'class', 'return', 'import', 'from', 'as', 'if', 'elif', 'else',
  'for', 'while', 'try', 'except', 'finally', 'with', 'in', 'is', 'not',
  'and', 'or', 'pass', 'break', 'continue', 'raise', 'lambda', 'yield',
  'None', 'True', 'False', 'self', 'async', 'await', 'global', 'nonlocal',
]);

const JS_KEYWORDS = new Set([
  'const', 'let', 'var', 'function', 'return', 'if', 'else', 'for', 'while',
  'do', 'switch', 'case', 'break', 'continue', 'new', 'class', 'extends',
  'import', 'from', 'export', 'default', 'async', 'await', 'try', 'catch',
  'finally', 'throw', 'typeof', 'instanceof', 'in', 'of', 'this', 'null',
  'true', 'false', 'undefined',
]);

function tokenizePython(source: string): Token[] {
  const tokens: Token[] = [];
  // Split into lines so comments are easy to catch; tokenize each line.
  const lines = source.split('\n');
  lines.forEach((line, lineIndex) => {
    let remainder = line;
    // Comment first — consumes the rest of the line.
    const commentIndex = findUnquotedHash(remainder);
    let tail = '';
    if (commentIndex !== -1) {
      tail = remainder.slice(commentIndex);
      remainder = remainder.slice(0, commentIndex);
    }
    // Strings (single + double).
    const segments = splitOutStrings(remainder);
    for (const segment of segments) {
      if (segment.kind === 'string') {
        tokens.push({ type: 'string', value: segment.value });
        continue;
      }
      // Split the non-string segment into word/non-word tokens.
      for (const piece of segment.value.split(/(\b\w+\b)/)) {
        if (!piece) continue;
        if (PYTHON_KEYWORDS.has(piece)) {
          tokens.push({ type: 'keyword', value: piece });
        } else if (/^\d+(?:\.\d+)?$/.test(piece)) {
          tokens.push({ type: 'number', value: piece });
        } else {
          tokens.push({ type: 'text', value: piece });
        }
      }
    }
    if (tail) tokens.push({ type: 'comment', value: tail });
    if (lineIndex < lines.length - 1) tokens.push({ type: 'text', value: '\n' });
  });
  return tokens;
}

function tokenizeJsLike(source: string): Token[] {
  const tokens: Token[] = [];
  const lines = source.split('\n');
  lines.forEach((line, lineIndex) => {
    let remainder = line;
    // Double-slash comment.
    const commentIndex = remainder.indexOf('//');
    let tail = '';
    if (commentIndex !== -1) {
      tail = remainder.slice(commentIndex);
      remainder = remainder.slice(0, commentIndex);
    }
    const segments = splitOutStrings(remainder);
    for (const segment of segments) {
      if (segment.kind === 'string') {
        tokens.push({ type: 'string', value: segment.value });
        continue;
      }
      for (const piece of segment.value.split(/(\b\w+\b)/)) {
        if (!piece) continue;
        if (JS_KEYWORDS.has(piece)) {
          tokens.push({ type: 'keyword', value: piece });
        } else if (/^\d+(?:\.\d+)?$/.test(piece)) {
          tokens.push({ type: 'number', value: piece });
        } else {
          tokens.push({ type: 'text', value: piece });
        }
      }
    }
    if (tail) tokens.push({ type: 'comment', value: tail });
    if (lineIndex < lines.length - 1) tokens.push({ type: 'text', value: '\n' });
  });
  return tokens;
}

function tokenizeJson(source: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;
  while (index < source.length) {
    const char = source[index];
    if (char === '"') {
      let end = index + 1;
      while (end < source.length && source[end] !== '"') {
        if (source[end] === '\\') end += 2;
        else end += 1;
      }
      tokens.push({ type: 'string', value: source.slice(index, end + 1) });
      index = end + 1;
      continue;
    }
    if (/[0-9-]/.test(char)) {
      let end = index;
      while (end < source.length && /[0-9.eE+-]/.test(source[end])) end += 1;
      tokens.push({ type: 'number', value: source.slice(index, end) });
      index = end;
      continue;
    }
    if (/[a-zA-Z]/.test(char)) {
      let end = index;
      while (end < source.length && /[a-zA-Z]/.test(source[end])) end += 1;
      const word = source.slice(index, end);
      if (word === 'true' || word === 'false' || word === 'null') {
        tokens.push({ type: 'keyword', value: word });
      } else {
        tokens.push({ type: 'text', value: word });
      }
      index = end;
      continue;
    }
    tokens.push({ type: 'text', value: char });
    index += 1;
  }
  return tokens;
}

function tokenizeYaml(source: string): Token[] {
  const tokens: Token[] = [];
  const lines = source.split('\n');
  lines.forEach((line, lineIndex) => {
    const commentIndex = line.indexOf('#');
    let head = line;
    let tail = '';
    if (commentIndex !== -1) {
      tail = line.slice(commentIndex);
      head = line.slice(0, commentIndex);
    }
    const match = head.match(/^(\s*-?\s*)([A-Za-z0-9_.-]+)(\s*:\s*)(.*)$/);
    if (match) {
      tokens.push({ type: 'text', value: match[1] });
      tokens.push({ type: 'keyword', value: match[2] });
      tokens.push({ type: 'text', value: match[3] });
      if (match[4]) tokens.push({ type: 'string', value: match[4] });
    } else {
      tokens.push({ type: 'text', value: head });
    }
    if (tail) tokens.push({ type: 'comment', value: tail });
    if (lineIndex < lines.length - 1) tokens.push({ type: 'text', value: '\n' });
  });
  return tokens;
}

function tokenizeMarkdown(source: string): Token[] {
  const tokens: Token[] = [];
  const lines = source.split('\n');
  lines.forEach((line, lineIndex) => {
    if (/^#{1,6}\s/.test(line)) {
      tokens.push({ type: 'keyword', value: line });
    } else if (/^[-*]\s/.test(line)) {
      const match = line.match(/^([-*]\s)(.*)$/)!;
      tokens.push({ type: 'number', value: match[1] });
      tokens.push({ type: 'text', value: match[2] });
    } else {
      tokens.push({ type: 'text', value: line });
    }
    if (lineIndex < lines.length - 1) tokens.push({ type: 'text', value: '\n' });
  });
  return tokens;
}

function splitOutStrings(text: string): Array<{ kind: 'text' | 'string'; value: string }> {
  const segments: Array<{ kind: 'text' | 'string'; value: string }> = [];
  let index = 0;
  let buffer = '';
  while (index < text.length) {
    const char = text[index];
    if (char === '"' || char === "'") {
      if (buffer) {
        segments.push({ kind: 'text', value: buffer });
        buffer = '';
      }
      const quote = char;
      let end = index + 1;
      while (end < text.length && text[end] !== quote) {
        if (text[end] === '\\') end += 2;
        else end += 1;
      }
      segments.push({ kind: 'string', value: text.slice(index, end + 1) });
      index = end + 1;
      continue;
    }
    buffer += char;
    index += 1;
  }
  if (buffer) segments.push({ kind: 'text', value: buffer });
  return segments;
}

function findUnquotedHash(line: string): number {
  let inString: '"' | "'" | null = null;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (inString) {
      if (char === '\\') {
        i += 1;
        continue;
      }
      if (char === inString) inString = null;
      continue;
    }
    if (char === '"' || char === "'") {
      inString = char;
      continue;
    }
    if (char === '#') return i;
  }
  return -1;
}

function tokenize(source: string, language: string): Token[] {
  switch (language) {
    case 'python':
      return tokenizePython(source);
    case 'javascript':
    case 'typescript':
    case 'tsx':
    case 'jsx':
      return tokenizeJsLike(source);
    case 'json':
      return tokenizeJson(source);
    case 'yaml':
    case 'yml':
      return tokenizeYaml(source);
    case 'markdown':
    case 'md':
      return tokenizeMarkdown(source);
    default:
      return [{ type: 'text', value: source }];
  }
}

const TOKEN_CLASSES: Record<Token['type'], string> = {
  text: 'text-neutral-200',
  keyword: 'text-[#c586c0]',
  string: 'text-[#ce9178]',
  comment: 'text-neutral-500 italic',
  number: 'text-[#b5cea8]',
};

export function SourceCodeView({ source, language, filename }: SourceCodeViewProps) {
  const tokens = useMemo(() => tokenize(source, language), [source, language]);
  const lines = useMemo(() => source.split('\n'), [source]);

  return (
    <div className="relative h-full overflow-hidden rounded-md border border-[color:var(--wb-border)] bg-[#0f0f13]">
      {filename && (
        <div className="flex items-center justify-between border-b border-[color:var(--wb-border)] px-3 py-1.5 text-[11px] text-neutral-500">
          <span className="font-mono">{filename}</span>
          <span className="uppercase tracking-wider">{language}</span>
        </div>
      )}
      <div className="grid grid-cols-[auto_1fr] overflow-auto">
        <pre className="select-none border-r border-[color:var(--wb-border)] px-3 py-3 text-right font-mono text-[11px] leading-5 text-neutral-600">
          {lines.map((_, index) => `${index + 1}`).join('\n')}
        </pre>
        <pre className="overflow-x-auto px-4 py-3 font-mono text-[12px] leading-5">
          {tokens.map((token, index) => (
            <span key={index} className={classNames(TOKEN_CLASSES[token.type])}>
              {token.value}
            </span>
          ))}
        </pre>
      </div>
    </div>
  );
}
