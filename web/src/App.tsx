import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
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
            <Route path="/evals" element={<EvalRuns />} />
            <Route path="/evals/:id" element={<EvalDetail />} />
            <Route path="/optimize" element={<Optimize />} />
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
            <Route path="/registry" element={<Registry />} />
            <Route path="/blame" element={<BlameMap />} />
            <Route path="/scorer-studio" element={<ScorerStudio />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
