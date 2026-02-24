import { Routes, Route, Navigate } from 'react-router-dom';
import { useEffect, Suspense, lazy } from 'react';
import Layout from './components/Layout';
import { ToastContainer } from './components/Toast';
import { useToastStore } from './stores/toastStore';
import { useConfigStore } from './stores/configStore';
import ErrorBoundary from './components/ErrorBoundary';
import { STORAGE_KEYS } from './constants';

// 懒加载页面组件 - 代码分割优化
const Welcome = lazy(() => import('./pages/Welcome'));
const Settings = lazy(() => import('./pages/Settings/index'));
const Novels = lazy(() => import('./pages/Novels'));
const NovelDetail = lazy(() => import('./pages/NovelDetail'));
const ChapterDetail = lazy(() => import('./pages/ChapterDetail'));
const ChapterGenerate = lazy(() => import('./pages/ChapterGenerate'));
const Characters = lazy(() => import('./pages/Characters'));
const Scenes = lazy(() => import('./pages/Scenes'));
const Tasks = lazy(() => import('./pages/Tasks'));
const TestCases = lazy(() => import('./pages/TestCases'));
const PromptConfig = lazy(() => import('./pages/PromptConfig'));
const UIConfig = lazy(() => import('./pages/UIConfig'));
const LLMLogs = lazy(() => import('./pages/LLMLogs'));

/**
 * 加载中占位组件
 */
function LoadingFallback() {
  return (
    <div className="flex items-center justify-center min-h-[400px]">
      <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>
  );
}

/**
 * 懒加载包装器
 */
function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<LoadingFallback />}>
      {children}
    </Suspense>
  );
}

function App() {
  const { toasts, removeToast } = useToastStore();
  const { loadConfig } = useConfigStore();

  // 应用启动时从后端加载配置，并清理旧的 localStorage
  useEffect(() => {
    // 清理旧的 localStorage 数据（配置现在存储在后端）
    localStorage.removeItem(STORAGE_KEYS.CONFIG);
    localStorage.removeItem(STORAGE_KEYS.CONFIG_V2);
    localStorage.removeItem(STORAGE_KEYS.PARSE_CHARACTERS_PROMPT);
    
    loadConfig();
  }, [loadConfig]);

  return (
    <>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/welcome" replace />} />
          <Route path="welcome" element={<LazyPage><Welcome /></LazyPage>} />
          <Route 
            path="settings" 
            element={
              <LazyPage>
                <ErrorBoundary><Settings /></ErrorBoundary>
              </LazyPage>
            } 
          />
          <Route path="novels" element={<LazyPage><Novels /></LazyPage>} />
          <Route path="novels/:id" element={<LazyPage><NovelDetail /></LazyPage>} />
          <Route path="novels/:id/chapters/:cid" element={<LazyPage><ChapterDetail /></LazyPage>} />
          <Route path="novels/:id/chapters/:cid/generate" element={<LazyPage><ChapterGenerate /></LazyPage>} />
          <Route path="characters" element={<LazyPage><Characters /></LazyPage>} />
          <Route path="scenes" element={<LazyPage><Scenes /></LazyPage>} />
          <Route path="tasks" element={<LazyPage><Tasks /></LazyPage>} />
          <Route path="test-cases" element={<LazyPage><TestCases /></LazyPage>} />
          <Route path="prompt-config" element={<LazyPage><PromptConfig /></LazyPage>} />
          <Route path="ui-config" element={<LazyPage><UIConfig /></LazyPage>} />
          <Route path="llm-logs" element={<LazyPage><LLMLogs /></LazyPage>} />
        </Route>
      </Routes>
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </>
  );
}

export default App;
