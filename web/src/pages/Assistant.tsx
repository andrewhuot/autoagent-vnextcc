import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Paperclip, Send, Trash2, Loader2 } from 'lucide-react';
import { ChatMessage } from '../components/assistant/ChatMessage';
import { FileUpload } from '../components/assistant/FileUpload';
import { QuickActions } from '../components/assistant/QuickActions';
import { classNames } from '../lib/utils';
import {
  useAssistantMessage,
  useClearHistory,
  useAssistantSuggestions,
} from '../lib/assistant-api';
import type { AssistantMessage as AssistantMessageType, UploadedFile } from '../lib/types';

const WELCOME_SUGGESTIONS = [
  'Build me a new agent',
  'Optimize my agent',
  'Explore conversations',
  'Why is my agent failing?',
  'Show me recent changes',
];

export function Assistant() {
  const navigate = useNavigate();
  const [inputMessage, setInputMessage] = useState('');
  const [showFileUpload, setShowFileUpload] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [conversationMessages, setConversationMessages] = useState<
    Array<{ id: string; role: 'user' | 'assistant'; message: AssistantMessageType }>
  >([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const { sendMessage, cancel, isStreaming, currentMessage } = useAssistantMessage();
  const clearHistory = useClearHistory();
  const suggestions = useAssistantSuggestions();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversationMessages, currentMessage]);

  const handleSendMessage = async () => {
    const message = inputMessage.trim();
    if (!message && uploadedFiles.length === 0) return;
    if (isStreaming) return;

    // Add user message to conversation
    const userMessage: AssistantMessageType = {
      id: crypto.randomUUID(),
      role: 'user',
      content: message,
      timestamp: Date.now(),
    };

    setConversationMessages((prev) => [
      ...prev,
      { id: userMessage.id, role: 'user', message: userMessage },
    ]);

    // Clear input
    setInputMessage('');
    setUploadedFiles([]);
    setShowFileUpload(false);

    // Send message
    sendMessage(message, uploadedFiles);
  };

  useEffect(() => {
    if (currentMessage && !isStreaming) {
      // Message complete, add to conversation
      setConversationMessages((prev) => [
        ...prev,
        { id: currentMessage.id, role: 'assistant', message: currentMessage },
      ]);
    }
  }, [currentMessage, isStreaming]);

  const handleClearHistory = () => {
    if (confirm('Clear all conversation history?')) {
      clearHistory.mutate();
      setConversationMessages([]);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setInputMessage(suggestion);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const activeSuggestions =
    currentMessage?.suggestions ||
    (conversationMessages.length === 0 ? WELCOME_SUGGESTIONS : suggestions.data || []);

  const hasMessages = conversationMessages.length > 0 || currentMessage;

  return (
    <div className="flex h-[calc(100vh-120px)] flex-col">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">AutoAgent Assistant</h1>
          <p className="mt-1 text-sm text-gray-600">
            Build, optimize, and debug AI agents through natural language
          </p>
          <div className="mt-3 inline-flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900">
            Recommended builder:
            <button
              onClick={() => navigate('/intelligence')}
              className="font-semibold text-sky-800 underline decoration-sky-400 underline-offset-2 hover:text-sky-900"
            >
              Intelligence Studio
            </button>
          </div>
        </div>

        {hasMessages && (
          <button
            onClick={handleClearHistory}
            disabled={clearHistory.isPending}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            Clear History
          </button>
        )}
      </div>

      {/* Messages Container */}
      <div className="mb-4 flex-1 overflow-y-auto rounded-lg border border-gray-200 bg-white">
        <div className="p-6">
          {!hasMessages && (
            <div className="flex h-full items-center justify-center py-12">
              <div className="max-w-md text-center">
                <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-100">
                  <span className="text-3xl">🤖</span>
                </div>
                <h2 className="mb-2 text-xl font-semibold text-gray-900">Welcome!</h2>
                <p className="mb-6 text-gray-600">
                  I can help you build, optimize, and debug AI agents. What would you like to do?
                </p>
                <QuickActions
                  suggestions={WELCOME_SUGGESTIONS}
                  onActionClick={handleSuggestionClick}
                  disabled={isStreaming}
                />
              </div>
            </div>
          )}

          {hasMessages && (
            <div className="space-y-6">
              {conversationMessages.map((msg) => (
                <ChatMessage key={msg.id} message={msg.message} isUser={msg.role === 'user'} />
              ))}

              {isStreaming && currentMessage && (
                <ChatMessage message={currentMessage} isUser={false} isStreaming={true} />
              )}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Suggestions */}
      {activeSuggestions.length > 0 && hasMessages && (
        <div className="mb-3">
          <QuickActions
            suggestions={activeSuggestions}
            onActionClick={handleSuggestionClick}
            disabled={isStreaming}
          />
        </div>
      )}

      {/* File Upload */}
      {showFileUpload && (
        <div className="mb-3">
          <FileUpload
            onFilesUploaded={(files) => {
              setUploadedFiles(files);
            }}
            maxFiles={5}
          />
        </div>
      )}

      {/* Uploaded Files Preview */}
      {uploadedFiles.length > 0 && !showFileUpload && (
        <div className="mb-3 flex flex-wrap gap-2">
          {uploadedFiles.map((file, index) => (
            <div
              key={index}
              className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1 text-sm text-blue-900"
            >
              <Paperclip className="h-4 w-4" />
              <span>{file.name}</span>
              <button
                onClick={() => setUploadedFiles((files) => files.filter((_, i) => i !== index))}
                className="text-blue-700 hover:text-blue-900"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input Area */}
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-end gap-3">
          <button
            onClick={() => setShowFileUpload(!showFileUpload)}
            className={classNames(
              'rounded-lg p-2 transition',
              showFileUpload
                ? 'bg-blue-100 text-blue-600'
                : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600'
            )}
            title="Upload files"
          >
            <Paperclip className="h-5 w-5" />
          </button>

          <textarea
            ref={inputRef}
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Shift+Enter for new line)"
            disabled={isStreaming}
            className="flex-1 resize-none rounded-lg border-0 bg-transparent px-3 py-2 text-sm text-gray-900 placeholder-gray-500 focus:outline-none focus:ring-0 disabled:opacity-50"
            rows={Math.min(Math.max(inputMessage.split('\n').length, 1), 5)}
          />

          {isStreaming ? (
            <button
              onClick={cancel}
              className="rounded-lg bg-red-600 p-2 text-white transition hover:bg-red-700"
              title="Stop generating"
            >
              <Loader2 className="h-5 w-5 animate-spin" />
            </button>
          ) : (
            <button
              onClick={handleSendMessage}
              disabled={!inputMessage.trim() && uploadedFiles.length === 0}
              className="rounded-lg bg-blue-600 p-2 text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              title="Send message"
            >
              <Send className="h-5 w-5" />
            </button>
          )}
        </div>

        <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
          <span>Press Enter to send, Shift+Enter for new line</span>
          {inputMessage.length > 0 && <span>{inputMessage.length} characters</span>}
        </div>
      </div>
    </div>
  );
}
