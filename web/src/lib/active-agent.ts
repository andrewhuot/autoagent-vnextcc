import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { AgentLibraryItem } from './types';

export interface ActiveAgentState {
  activeAgent: AgentLibraryItem | null;
  setActiveAgent: (agent: AgentLibraryItem) => void;
  clearActiveAgent: () => void;
}

const noopStorage = {
  getItem: () => null,
  setItem: () => undefined,
  removeItem: () => undefined,
};

export const useActiveAgentStore = create<ActiveAgentState>()(
  persist(
    (set) => ({
      activeAgent: null,
      setActiveAgent: (agent) => set({ activeAgent: agent }),
      clearActiveAgent: () => set({ activeAgent: null }),
    }),
    {
      name: 'agentlab.active-agent.v1',
      storage: createJSONStorage(() => (
        typeof window === 'undefined' ? noopStorage : window.sessionStorage
      )),
      partialize: (state) => ({ activeAgent: state.activeAgent }),
    }
  )
);

export function useActiveAgent() {
  const activeAgent = useActiveAgentStore((state) => state.activeAgent);
  const setActiveAgent = useActiveAgentStore((state) => state.setActiveAgent);
  const clearActiveAgent = useActiveAgentStore((state) => state.clearActiveAgent);

  return {
    activeAgent,
    setActiveAgent,
    clearActiveAgent,
  };
}
