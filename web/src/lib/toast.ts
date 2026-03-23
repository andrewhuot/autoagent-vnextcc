import { create } from 'zustand';

export type ToastTone = 'success' | 'error' | 'warning' | 'info';

export interface ToastItem {
  id: string;
  title: string;
  description?: string;
  tone: ToastTone;
  createdAt: number;
}

interface ToastStore {
  toasts: ToastItem[];
  pushToast: (toast: Omit<ToastItem, 'id' | 'createdAt'>) => string;
  dismissToast: (id: string) => void;
  clearToasts: () => void;
}

const TOAST_TTL_MS = 4500;

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  pushToast: (toast) => {
    const id = `toast-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const item: ToastItem = {
      id,
      title: toast.title,
      description: toast.description,
      tone: toast.tone,
      createdAt: Date.now(),
    };

    set((state) => ({
      toasts: [...state.toasts, item],
    }));

    window.setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((entry) => entry.id !== id),
      }));
    }, TOAST_TTL_MS);

    return id;
  },
  dismissToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((entry) => entry.id !== id),
    }));
  },
  clearToasts: () => {
    set({ toasts: [] });
  },
}));

export function toastSuccess(title: string, description?: string) {
  return useToastStore.getState().pushToast({ title, description, tone: 'success' });
}

export function toastError(title: string, description?: string) {
  return useToastStore.getState().pushToast({ title, description, tone: 'error' });
}

export function toastInfo(title: string, description?: string) {
  return useToastStore.getState().pushToast({ title, description, tone: 'info' });
}

export function toastWarning(title: string, description?: string) {
  return useToastStore.getState().pushToast({ title, description, tone: 'warning' });
}
