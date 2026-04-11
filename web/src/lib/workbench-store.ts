import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ExecutionMode } from './builder-types';

// ExecutionMode = 'ask' | 'draft' | 'apply' | 'delegate'

export type WorkbenchInspectorTab =
  | 'preview'
  | 'agent_card'
  | 'source_code'
  | 'tools'
  | 'callbacks'
  | 'guardrails'
  | 'evals'
  | 'trace'
  | 'test_live'
  | 'deploy'
  | 'activity';

interface WorkbenchState {
  activeProjectId: string | null;
  activeSessionId: string | null;
  mode: ExecutionMode;
  model: string;
  environment: string;
  paused: boolean;
  inspectorTab: WorkbenchInspectorTab;
  inspectorCollapsed: boolean;
  setActiveProjectId: (id: string | null) => void;
  setActiveSessionId: (id: string | null) => void;
  setMode: (mode: ExecutionMode) => void;
  setModel: (model: string) => void;
  setEnvironment: (env: string) => void;
  setPaused: (paused: boolean) => void;
  setInspectorTab: (tab: WorkbenchInspectorTab) => void;
  setInspectorCollapsed: (collapsed: boolean) => void;
}

export const useWorkbenchStore = create<WorkbenchState>()(
  persist(
    (set) => ({
      activeProjectId: null,
      activeSessionId: null,
      mode: 'ask',
      model: 'claude-sonnet-4-6',
      environment: 'sandbox',
      paused: false,
      inspectorTab: 'agent_card',
      inspectorCollapsed: false,
      setActiveProjectId: (id) => set({ activeProjectId: id }),
      setActiveSessionId: (id) => set({ activeSessionId: id }),
      setMode: (mode) => set({ mode }),
      setModel: (model) => set({ model }),
      setEnvironment: (environment) => set({ environment }),
      setPaused: (paused) => set({ paused }),
      setInspectorTab: (inspectorTab) => set({ inspectorTab }),
      setInspectorCollapsed: (inspectorCollapsed) => set({ inspectorCollapsed }),
    }),
    { name: 'agentlab-workbench-state' }
  )
);
