import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  AssistantMessage,
  AssistantHistoryEntry,
  AssistantCard,
  UploadedFile,
} from './types';

const API_BASE = '/api';

// SSE Event types from the backend
interface SSEThinkingEvent {
  step: string;
  progress: number;
  details?: unknown;
}

interface SSECardEvent {
  type: string;
  data: unknown;
}

interface SSETextEvent {
  content: string;
}

interface SSESuggestionsEvent {
  actions: string[];
}

/**
 * Hook for streaming assistant messages via SSE
 */
export function useAssistantMessage() {
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentMessage, setCurrentMessage] = useState<AssistantMessage | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const queryClient = useQueryClient();

  const sendMessage = useCallback(
    (message: string, files?: UploadedFile[]) => {
      // Close any existing connection
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      setIsStreaming(true);
      const messageId = crypto.randomUUID();

      // Initialize the assistant message
      setCurrentMessage({
        id: messageId,
        role: 'assistant',
        timestamp: Date.now(),
        thinking_steps: [],
        cards: [],
        suggestions: [],
      });

      // Build query params
      const params = new URLSearchParams({ message });
      if (files && files.length > 0) {
        params.append('files', JSON.stringify(files.map((f) => ({ name: f.name, url: f.url }))));
      }

      // Open SSE connection
      const eventSource = new EventSource(`${API_BASE}/assistant/message?${params.toString()}`);
      eventSourceRef.current = eventSource;

      eventSource.addEventListener('thinking', (event) => {
        const data: SSEThinkingEvent = JSON.parse(event.data);
        setCurrentMessage((prev) => {
          if (!prev) return prev;
          const steps = [...(prev.thinking_steps || [])];
          const existingIndex = steps.findIndex((s) => s.step === data.step);

          if (existingIndex >= 0) {
            steps[existingIndex] = {
              ...steps[existingIndex],
              progress: data.progress,
              details: data.details,
              completed: data.progress >= 1.0,
            };
          } else {
            steps.push({
              step: data.step,
              progress: data.progress,
              details: data.details,
              completed: data.progress >= 1.0,
            });
          }

          return { ...prev, thinking_steps: steps };
        });
      });

      eventSource.addEventListener('card', (event) => {
        const data: SSECardEvent = JSON.parse(event.data);
        setCurrentMessage((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            cards: [...(prev.cards || []), { type: data.type as AssistantCard['type'], data: data.data }],
          };
        });
      });

      eventSource.addEventListener('text', (event) => {
        const data: SSETextEvent = JSON.parse(event.data);
        setCurrentMessage((prev) => {
          if (!prev) return prev;
          const existingContent = prev.content || '';
          return {
            ...prev,
            content: existingContent + (existingContent ? '\n\n' : '') + data.content,
          };
        });
      });

      eventSource.addEventListener('suggestions', (event) => {
        const data: SSESuggestionsEvent = JSON.parse(event.data);
        setCurrentMessage((prev) => {
          if (!prev) return prev;
          return { ...prev, suggestions: data.actions };
        });
      });

      eventSource.addEventListener('complete', () => {
        setIsStreaming(false);
        eventSource.close();
        queryClient.invalidateQueries({ queryKey: ['assistant-history'] });
      });

      eventSource.onerror = (error) => {
        console.error('SSE Error:', error);
        setIsStreaming(false);
        eventSource.close();
        setCurrentMessage((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            content: (prev.content || '') + '\n\nError: Failed to complete the request.',
          };
        });
      };
    },
    [queryClient]
  );

  const cancel = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setIsStreaming(false);
  }, []);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  return {
    sendMessage,
    cancel,
    isStreaming,
    currentMessage,
  };
}

/**
 * Hook for fetching conversation history
 */
export function useAssistantHistory() {
  return useQuery<AssistantHistoryEntry[]>({
    queryKey: ['assistant-history'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/assistant/history`);
      if (!response.ok) {
        throw new Error('Failed to fetch history');
      }
      return response.json();
    },
    staleTime: 30000,
  });
}

/**
 * Hook for clearing conversation history
 */
export function useClearHistory() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const response = await fetch(`${API_BASE}/assistant/history`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error('Failed to clear history');
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assistant-history'] });
    },
  });
}

/**
 * Hook for executing card actions
 */
export function useExecuteAction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ actionId, params }: { actionId: string; params?: Record<string, unknown> }) => {
      const response = await fetch(`${API_BASE}/assistant/action/${actionId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(params || {}),
      });
      if (!response.ok) {
        throw new Error('Failed to execute action');
      }
      return response.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assistant-history'] });
    },
  });
}

/**
 * Hook for uploading files
 */
export function useUploadFile() {
  return useMutation({
    mutationFn: async (file: File): Promise<UploadedFile> => {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${API_BASE}/assistant/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Failed to upload file');
      }

      const result = await response.json();
      return {
        name: file.name,
        size: file.size,
        type: file.type,
        url: result.url,
      };
    },
  });
}

/**
 * Hook for fetching contextual suggestions
 */
export function useAssistantSuggestions() {
  return useQuery<string[]>({
    queryKey: ['assistant-suggestions'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/assistant/suggestions`);
      if (!response.ok) {
        throw new Error('Failed to fetch suggestions');
      }
      const data = await response.json();
      return data.suggestions || [];
    },
    staleTime: 60000,
  });
}
