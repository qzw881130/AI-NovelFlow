import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Welcome from './pages/Welcome';
import Settings from './pages/Settings';
import Novels from './pages/Novels';
import NovelDetail from './pages/NovelDetail';
import ChapterDetail from './pages/ChapterDetail';
import Characters from './pages/Characters';
import Tasks from './pages/Tasks';

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/welcome" replace />} />
        <Route path="welcome" element={<Welcome />} />
        <Route path="settings" element={<Settings />} />
        <Route path="novels" element={<Novels />} />
        <Route path="novels/:id" element={<NovelDetail />} />
        <Route path="novels/:id/chapters/:cid" element={<ChapterDetail />} />
        <Route path="characters" element={<Characters />} />
        <Route path="tasks" element={<Tasks />} />
      </Route>
    </Routes>
  );
}

export default App;
