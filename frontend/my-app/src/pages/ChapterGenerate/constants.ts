import { 
  FileText,
  Sparkles,
  FileJson,
  Users,
  Image as ImageIcon,
  Video,
  Film,
  CheckCircle
} from 'lucide-react';

// 步骤定义 - 每个步骤有独特的颜色主题
export const STEPS_CONFIG = [
  { key: 'content', icon: FileText, color: 'from-blue-500 to-cyan-500' },
  { key: 'ai-parse', icon: Sparkles, color: 'from-purple-500 to-pink-500' },
  { key: 'json', icon: FileJson, color: 'from-emerald-500 to-teal-500' },
  { key: 'character', icon: Users, color: 'from-orange-500 to-amber-500' },
  { key: 'shots', icon: ImageIcon, color: 'from-rose-500 to-pink-500' },
  { key: 'videos', icon: Video, color: 'from-indigo-500 to-violet-500' },
  { key: 'transitions', icon: Film, color: 'from-cyan-500 to-blue-500' },
  { key: 'compose', icon: CheckCircle, color: 'from-green-500 to-emerald-500' }
];

// API 基础路径
export const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 默认转场时长（秒）
export const DEFAULT_TRANSITION_DURATION = 2;

// 视频帧率
export const VIDEO_FPS = 25;

// 帧数计算基数（需要是8的倍数+1）
export const FRAME_BASE = 8;
