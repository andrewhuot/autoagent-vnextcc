import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { builderApi } from '../lib/builder-api';
import { sendBuilderMessage } from '../lib/workbench-api';
import { useWorkbenchStore } from '../lib/workbench-store';
import { TopBar, type BuilderEnvironment } from '../components/builder/TopBar';
import { LeftRail } from '../components/builder/LeftRail';
import { ConversationPane } from '../components/builder/ConversationPane';
import type { ConversationEntry } from '../components/builder/ConversationPane';
import { Composer } from '../components/builder/Composer';
import { TaskDrawer } from '../components/builder/TaskDrawer';
import { WorkbenchInspector } from '../components/builder/WorkbenchInspector';
import type { BuilderConfigDraft, BuilderTask } from '../lib/builder-types';

const MODEL_OPTIONS = [
  'claude-sonnet-4-6',
  'claude-opus-4-5',
  'claude-haiku-4-5',
];

export function Workbench() {
  const queryClient = useQueryClient();
  const [composerValue, setComposerValue] = useState('');
  const [leftRailCollapsed, setLeftRailCollapsed] = useState(false);
  const [taskDrawerOpen, setTaskDrawerOpen] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [localEntries, setLocalEntries] = useState<ConversationEntry[]>([]);

  const {
    activeProjectId,
    activeSessionId,
    mode,
    model,
    environment,
    paused,
    inspectorTab,
    setActiveProjectId,
    setActiveSessionId,
    setMode,
    setModel,
    setEnvironment,
    setPaused,
    setInspectorTab,
    setInspectorCollapsed,
    inspectorCollapsed,
  } = useWorkbenchStore();

  // Coerce stored environment string to BuilderEnvironment for TopBar
  const safeEnvironment: BuilderEnvironment =
    environment === 'dev' || environment === 'staging' || environment === 'prod'
      ? (environment as BuilderEnvironment)
      : 'dev';

  // ── Server state ──────────────────────────────────────────────────────────

  const { data: projects = [] } = useQuery({
    queryKey: ['workbench', 'projects'],
    queryFn: () => builderApi.projects.list(),
  });

  const activeProject = projects.find((p) => p.project_id === activeProjectId) ?? null;

  const { data: sessions = [] } = useQuery({
    queryKey: ['workbench', 'sessions', activeProjectId],
    queryFn: () => builderApi.sessions.list(activeProjectId ?? undefined),
    enabled: true,
  });

  const { data: sessionPayload } = useQuery({
    queryKey: ['workbench', 'session', activeSessionId],
    queryFn: () => {
      if (!activeSessionId) return null;
      // Use builder-chat-api getBuilderSession via workbench-api re-export
      return import('../lib/workbench-api').then(({ getBuilderSession }) =>
        getBuilderSession(activeSessionId)
      );
    },
    enabled: !!activeSessionId,
  });

  const { data: tasks = [] } = useQuery({
    queryKey: ['workbench', 'tasks', activeSessionId],
    queryFn: () =>
      activeSessionId
        ? builderApi.tasks.list({ sessionId: activeSessionId })
        : Promise.resolve([]),
    enabled: !!activeSessionId,
  });

  const runningTasks = tasks.filter(
    (t: BuilderTask) => t.status === 'running' || t.status === 'paused'
  );
  const completedTasks = tasks.filter(
    (t: BuilderTask) => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled'
  );

  // ── Send message mutation ─────────────────────────────────────────────────

  const sendMutation = useMutation({
    mutationFn: (message: string) =>
      sendBuilderMessage({ message, session_id: activeSessionId ?? null }),
    onMutate: (message: string) => {
      const userEntry: ConversationEntry = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: message,
      };
      setLocalEntries((prev) => [...prev, userEntry]);
    },
    onSuccess: (result) => {
      // Capture session id from first message
      if (!activeSessionId && result.session_id) {
        setActiveSessionId(result.session_id);
      }

      const assistantEntry: ConversationEntry = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content:
          result.messages.length > 0
            ? (result.messages[result.messages.length - 1]?.content ?? '')
            : '',
      };
      setLocalEntries((prev) => [...prev, assistantEntry]);

      // Invalidate session query so inspector picks up updated config
      void queryClient.invalidateQueries({
        queryKey: ['workbench', 'session', result.session_id],
      });
    },
  });

  const handleSubmit = () => {
    const trimmed = composerValue.trim();
    if (!trimmed || sendMutation.isPending) return;
    setComposerValue('');
    sendMutation.mutate(trimmed);
  };

  // ── Conversation entries ──────────────────────────────────────────────────
  // Merge server-side messages with local optimistic entries.
  const serverEntries: ConversationEntry[] =
    sessionPayload?.messages.map((msg) => ({
      id: msg.message_id,
      role: msg.role,
      content: msg.content,
    })) ?? [];

  // Use server entries when available, fall back to local optimistic ones
  const conversationEntries =
    serverEntries.length > 0 ? serverEntries : localEntries;

  // Adapt BuilderConfig (builder-chat-api) → BuilderConfigDraft (builder-types) for inspector
  const configDraft: BuilderConfigDraft | null = sessionPayload
    ? {
        agent_name: sessionPayload.config.agent_name,
        model: sessionPayload.config.model,
        system_prompt: sessionPayload.config.system_prompt,
        tools: sessionPayload.config.tools.map((t, i) => ({
          id: `tool-${i}`,
          name: t.name,
          description: t.description,
        })),
        routing_rules: sessionPayload.config.routing_rules as unknown as Array<Record<string, unknown>>,
        policies: sessionPayload.config.policies.map((p, i) => ({
          id: `policy-${i}`,
          name: p.name,
          description: p.description,
        })),
        eval_criteria: sessionPayload.config.eval_criteria as unknown as Array<Record<string, unknown>>,
        metadata: sessionPayload.config.metadata,
      }
    : null;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-[calc(100vh-65px)] w-full flex-col bg-slate-950 text-slate-100">
      <TopBar
        project={activeProject}
        projects={projects}
        mode={mode}
        model={model}
        modelOptions={MODEL_OPTIONS}
        environment={safeEnvironment}
        paused={paused}
        permissionCount={0}
        onProjectChange={(projectId) => setActiveProjectId(projectId)}
        onEnvironmentChange={(env) => setEnvironment(env)}
        onModelChange={setModel}
        onModeChange={setMode}
        onTogglePaused={() => setPaused(!paused)}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[auto_minmax(0,1fr)_420px]">
        {/* Left rail */}
        <LeftRail
          collapsed={leftRailCollapsed}
          projects={projects}
          sessions={sessions}
          tasks={tasks}
          selectedProjectId={activeProjectId}
          selectedSessionId={activeSessionId}
          selectedTaskId={selectedTaskId}
          onToggle={() => setLeftRailCollapsed((prev) => !prev)}
          onSelectProject={(id) => setActiveProjectId(id)}
          onSelectSession={(id) => setActiveSessionId(id)}
          onSelectTask={(id) => setSelectedTaskId(id)}
        />

        {/* Centre: conversation + composer */}
        <div className="relative flex min-h-0 flex-col">
          <div className="min-h-0 flex-1 overflow-hidden">
            <ConversationPane
              entries={conversationEntries}
              loading={sendMutation.isPending}
            />
          </div>
          <Composer
            mode={mode}
            value={composerValue}
            disabled={sendMutation.isPending}
            onModeChange={setMode}
            onChange={setComposerValue}
            onSubmit={handleSubmit}
          />

          {/* Task drawer anchored inside centre column */}
          <TaskDrawer
            open={taskDrawerOpen}
            runningTasks={runningTasks}
            completedTasks={completedTasks}
            approvals={[]}
            onClose={() => setTaskDrawerOpen(false)}
          />
        </div>

        {/* Right inspector — created by Track B */}
        <WorkbenchInspector
          activeTab={inspectorTab}
          onTabChange={setInspectorTab}
          sessionId={activeSessionId}
          draft={configDraft}
          collapsed={inspectorCollapsed}
          onToggleCollapsed={() => setInspectorCollapsed(!inspectorCollapsed)}
        />
      </div>
    </div>
  );
}
