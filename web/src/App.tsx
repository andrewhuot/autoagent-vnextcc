import { BrowserRouter, Navigate, Routes, Route, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import { Demo } from './pages/Demo';
import { EvalRuns } from './pages/EvalRuns';
import { Compare } from './pages/Compare';
import { EvalDetail } from './pages/EvalDetail';
import { ResultsExplorer } from './pages/ResultsExplorer';
import { Optimize } from './pages/Optimize';
import { Configs } from './pages/Configs';
import { Conversations } from './pages/Conversations';
import { Deploy } from './pages/Deploy';
import { LoopMonitor } from './pages/LoopMonitor';
import { Setup } from './pages/Setup';
import { Settings } from './pages/Settings';
import { Traces } from './pages/Traces';
import { EventLogPage } from './pages/EventLog';
import { JudgeOps } from './pages/JudgeOps';
import { ContextWorkbench } from './pages/ContextWorkbench';
import { Registry } from './pages/Registry';
import { BlameMap } from './pages/BlameMap';
import { ScorerStudio } from './pages/ScorerStudio';
import { Runbooks } from './pages/Runbooks';
import { Skills } from './pages/Skills';
import { ProjectMemory } from './pages/ProjectMemory';
import { CxImport } from './pages/CxImport';
import { CxDeploy } from './pages/CxDeploy';
import { CXStudio } from './pages/CXStudio';
import { LiveOptimize } from './pages/LiveOptimize';
import { AdkImport } from './pages/AdkImport';
import { AdkDeploy } from './pages/AdkDeploy';
import { AgentSkills } from './pages/AgentSkills';
import { Notifications } from './pages/Notifications';
import { Sandbox } from './pages/Sandbox';
import { Knowledge } from './pages/Knowledge';
import { WhatIf } from './pages/WhatIf';
import { RewardStudio } from './pages/RewardStudio';
import { PreferenceInbox } from './pages/PreferenceInbox';
import { PolicyCandidates } from './pages/PolicyCandidates';
import { RewardAudit } from './pages/RewardAudit';
import { Build } from './pages/Build';
import { Studio } from './pages/studio/Studio';
import { Improvements } from './pages/Improvements';
import { Connect } from './pages/Connect';
import { CliLauncher } from './pages/CliLauncher';
import { Docs } from './pages/Docs';
import { AgentImprover } from './pages/AgentImprover';
import { ErrorBoundary } from './components/ErrorBoundary';
import { getRouteRedirect } from './lib/navigation';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 30000,
      staleTime: 10000,
    },
  },
});

function LegacyRouteRedirect() {
  const location = useLocation();
  const redirectTo = getRouteRedirect(location.pathname) ?? '/build';

  return <Navigate to={redirectTo} replace />;
}

export default function App() {
  return (
    <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/build" replace />} />
            <Route path="/build" element={<Build />} />
            <Route path="/agent-improver" element={<AgentImprover />} />
            <Route path="/intelligence" element={<LegacyRouteRedirect />} />
            <Route path="/builder" element={<LegacyRouteRedirect />} />
            <Route path="/builder/demo" element={<LegacyRouteRedirect />} />
            <Route path="/builder/*" element={<LegacyRouteRedirect />} />
            <Route path="/agent-studio" element={<LegacyRouteRedirect />} />
            <Route path="/assistant" element={<LegacyRouteRedirect />} />

            {/* Dashboard moved to /dashboard */}
            <Route path="/dashboard" element={<Dashboard />} />

            <Route path="/demo" element={<Demo />} />
            <Route path="/eval" element={<LegacyRouteRedirect />} />
            <Route path="/evals" element={<EvalRuns />} />
            <Route path="/results" element={<ResultsExplorer />} />
            <Route path="/results/:runId" element={<ResultsExplorer />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/evals/:id" element={<EvalDetail />} />
            <Route path="/optimize" element={<Optimize />} />
            <Route path="/studio" element={<Studio />} />
            <Route path="/live-optimize" element={<LiveOptimize />} />
            <Route path="/improvements" element={<Improvements />} />
            <Route path="/configs" element={<Configs />} />
            <Route path="/conversations" element={<Conversations />} />
            <Route path="/deploy" element={<Deploy />} />
            <Route path="/loop" element={<LoopMonitor />} />
            <Route path="/setup" element={<Setup />} />
            <Route path="/opportunities" element={<LegacyRouteRedirect />} />
            <Route path="/experiments" element={<LegacyRouteRedirect />} />
            <Route path="/traces" element={<Traces />} />
            <Route path="/events" element={<EventLogPage />} />
            <Route path="/autofix" element={<LegacyRouteRedirect />} />
            <Route path="/judge-ops" element={<JudgeOps />} />
            <Route path="/context" element={<ContextWorkbench />} />
            <Route path="/changes" element={<LegacyRouteRedirect />} />
            <Route path="/runbooks" element={<Runbooks />} />
            <Route path="/skills" element={<Skills />} />
            <Route path="/memory" element={<ProjectMemory />} />
            <Route path="/registry" element={<Registry />} />
            <Route path="/blame" element={<BlameMap />} />
            <Route path="/scorer-studio" element={<ScorerStudio />} />
            <Route path="/connect" element={<Connect />} />
            <Route path="/cx/studio" element={<CXStudio />} />
            <Route path="/cx/import" element={<CxImport />} />
            <Route path="/cx/deploy" element={<CxDeploy />} />
            <Route path="/adk/import" element={<AdkImport />} />
            <Route path="/adk/deploy" element={<AdkDeploy />} />
            <Route path="/agent-skills" element={<AgentSkills />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/sandbox" element={<Sandbox />} />
            <Route path="/knowledge" element={<Knowledge />} />
            <Route path="/cli" element={<CliLauncher />} />
            <Route path="/docs" element={<Docs />} />
            <Route path="/what-if" element={<WhatIf />} />
            <Route path="/review" element={<LegacyRouteRedirect />} />
            <Route path="/reviews" element={<LegacyRouteRedirect />} />
            <Route path="/reward-studio" element={<RewardStudio />} />
            <Route path="/preference-inbox" element={<PreferenceInbox />} />
            <Route path="/policy-candidates" element={<PolicyCandidates />} />
            <Route path="/reward-audit" element={<RewardAudit />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
    </ErrorBoundary>
  );
}
