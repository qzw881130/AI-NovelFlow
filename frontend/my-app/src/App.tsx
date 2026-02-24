import { Routes, Route, Navigate } from 'react-router-dom';
import { useEffect } from 'react';
import Layout from './components/Layout';
import Welcome from './pages/Welcome';
import Settings from './pages/Settings';
import Novels from './pages/Novels';
import NovelDetail from './pages/NovelDetail';
import ChapterDetail from './pages/ChapterDetail';
import ChapterGenerate from './pages/ChapterGenerate';
import Characters from './pages/Characters';
import Scenes from './pages/Scenes';
import Tasks from './pages/Tasks';
import TestCases from './pages/TestCases';
import PromptConfig from './pages/PromptConfig';
import UIConfig from './pages/UIConfig';
import LLMLogs from './pages/LLMLogs';
import { ToastContainer } from './components/Toast';
import { useToastStore } from './stores/toastStore';
import { useConfigStore } from './stores/configStore';
import ErrorBoundary from './components/ErrorBoundary';

function App() {
  const { toasts, removeToast } = useToastStore();
  const { loadConfig } = useConfigStore();

  // 应用启动时从后端加载配置，并清理旧的 localStorage
  useEffect(() => {
    // 清理旧的 localStorage 数据（配置现在存储在后端）
    localStorage.removeItem('novelflow-config');
    localStorage.removeItem('novelflow-config-v2');
    localStorage.removeItem('novelfow_parse_characters_prompt');
    
    loadConfig();
  }, [loadConfig]);

  return (
    <>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/welcome" replace />} />
          <Route path="welcome" element={<Welcome />} />
          <Route path="settings" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
          <Route path="novels" element={<Novels />} />
          <Route path="novels/:id" element={<NovelDetail />} />
          <Route path="novels/:id/chapters/:cid" element={<ChapterDetail />} />
          <Route path="novels/:id/chapters/:cid/generate" element={<ChapterGenerate />} />
          <Route path="characters" element={<Characters />} />
          <Route path="scenes" element={<Scenes />} />
          <Route path="tasks" element={<Tasks />} />
          <Route path="test-cases" element={<TestCases />} />
          <Route path="prompt-config" element={<PromptConfig />} />
          <Route path="ui-config" element={<UIConfig />} />
          <Route path="llm-logs" element={<LLMLogs />} />
        </Route>
      </Routes>
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </>
  );
}

export default App;
