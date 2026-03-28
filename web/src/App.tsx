import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import { Demo } from './pages/Demo';
import { EvalRuns } from './pages/EvalRuns';
import { EvalDetail } from './pages/EvalDetail';
import { Optimize } from './pages/Optimize';
import { Configs } from './pages/Configs';
import { Conversations } from './pages/Conversations';
import { Deploy } from './pages/Deploy';
import { LoopMonitor } from './pages/LoopMonitor';
import { Settings } from './pages/Settings';
import { Opportunities } from './pages/Opportunities';
import { Experiments } from './pages/Experiments';
import { Traces } from './pages/Traces';
import { EventLogPage } from './pages/EventLog';
import { AutoFix } from './pages/AutoFix';
import { JudgeOps } from './pages/JudgeOps';
import { ContextWorkbench } from './pages/ContextWorkbench';
import { Registry } from './pages/Registry';
import { BlameMap } from './pages/BlameMap';
import { ScorerStudio } from './pages/ScorerStudio';
import { ChangeReview } from './pages/ChangeReview';
import { Runbooks } from './pages/Runbooks';
import { Skills } from './pages/Skills';
import { ProjectMemory } from './pages/ProjectMemory';
import { IntelligenceStudio } from './pages/IntelligenceStudio';
import { CxImport } from './pages/CxImport';
import { CxDeploy } from './pages/CxDeploy';
import { LiveOptimize } from './pages/LiveOptimize';
import { AdkImport } from './pages/AdkImport';
import { AdkDeploy } from './pages/AdkDeploy';
import { AgentSkills } from './pages/AgentSkills';
import { AgentStudio } from './pages/AgentStudio';
import { Assistant } from './pages/Assistant';
import { Notifications } from './pages/Notifications';
import { Sandbox } from './pages/Sandbox';
import { Knowledge } from './pages/Knowledge';
import { WhatIf } from './pages/WhatIf';
import { Reviews } from './pages/Reviews';
import { RewardStudio } from './pages/RewardStudio';
import { PreferenceInbox } from './pages/PreferenceInbox';
import { PolicyCandidates } from './pages/PolicyCandidates';
import { RewardAudit } from './pages/RewardAudit';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 30000,
      staleTime: 10000,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/demo" element={<Demo />} />
            <Route path="/evals" element={<EvalRuns />} />
            <Route path="/evals/:id" element={<EvalDetail />} />
            <Route path="/optimize" element={<Optimize />} />
            <Route path="/live-optimize" element={<LiveOptimize />} />
            <Route path="/configs" element={<Configs />} />
            <Route path="/conversations" element={<Conversations />} />
            <Route path="/deploy" element={<Deploy />} />
            <Route path="/loop" element={<LoopMonitor />} />
            <Route path="/opportunities" element={<Opportunities />} />
            <Route path="/experiments" element={<Experiments />} />
            <Route path="/traces" element={<Traces />} />
            <Route path="/events" element={<EventLogPage />} />
            <Route path="/autofix" element={<AutoFix />} />
            <Route path="/judge-ops" element={<JudgeOps />} />
            <Route path="/context" element={<ContextWorkbench />} />
            <Route path="/changes" element={<ChangeReview />} />
            <Route path="/runbooks" element={<Runbooks />} />
            <Route path="/skills" element={<Skills />} />
            <Route path="/intelligence" element={<IntelligenceStudio />} />
            <Route path="/memory" element={<ProjectMemory />} />
            <Route path="/registry" element={<Registry />} />
            <Route path="/blame" element={<BlameMap />} />
            <Route path="/scorer-studio" element={<ScorerStudio />} />
            <Route path="/cx/import" element={<CxImport />} />
            <Route path="/cx/deploy" element={<CxDeploy />} />
            <Route path="/adk/import" element={<AdkImport />} />
            <Route path="/adk/deploy" element={<AdkDeploy />} />
            <Route path="/agent-skills" element={<AgentSkills />} />
            <Route path="/agent-studio" element={<AgentStudio />} />
            <Route path="/assistant" element={<Assistant />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/sandbox" element={<Sandbox />} />
            <Route path="/knowledge" element={<Knowledge />} />
            <Route path="/what-if" element={<WhatIf />} />
            <Route path="/reviews" element={<Reviews />} />
            <Route path="/reward-studio" element={<RewardStudio />} />
            <Route path="/preference-inbox" element={<PreferenceInbox />} />
            <Route path="/policy-candidates" element={<PolicyCandidates />} />
            <Route path="/reward-audit" element={<RewardAudit />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
