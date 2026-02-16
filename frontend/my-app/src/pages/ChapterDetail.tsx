import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { 
  ArrowLeft, 
  Save, 
  Loader2, 
  Play,
  FileText,
  Image as ImageIcon,
  Film,
  CheckCircle,
  AlertCircle,
  Trash2,
  X,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';
import type { Chapter, Novel } from '../types';
import { toast } from '../stores/toastStore';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function ChapterDetail() {
  const { id, cid } = useParams<{ id: string; cid: string }>();
  const navigate = useNavigate();
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [novel, setNovel] = useState<Novel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [content, setContent] = useState('');
  const [title, setTitle] = useState('');
  
  // 图片预览状态
  const [previewImage, setPreviewImage] = useState<{
    isOpen: boolean;
    url: string | null;
    index: number;
    images: string[];
  }>({ isOpen: false, url: null, index: 0, images: [] });

  useEffect(() => {
    if (id && cid) {
      fetchData();
    }
  }, [id, cid]);

  const fetchData = async () => {
    setIsLoading(true);
    try {
      // 获取小说信息
      const novelRes = await fetch(`${API_BASE}/novels/${id}/`);
      const novelData = await novelRes.json();
      if (novelData.success) {
        setNovel(novelData.data);
      }

      // 获取章节信息
      const chapterRes = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/`);
      const chapterData = await chapterRes.json();
      if (chapterData.success) {
        setChapter(chapterData.data);
        setTitle(chapterData.data.title);
        setContent(chapterData.data.content || '');
      }
    } catch (error) {
      console.error('获取数据失败:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const res = await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content }),
      });
      const data = await res.json();
      if (data.success) {
        setChapter(data.data);
        toast.success('保存成功');
      }
    } catch (error) {
      console.error('保存失败:', error);
      toast.error('保存失败');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm('确定要删除这个章节吗？')) return;
    
    try {
      await fetch(`${API_BASE}/novels/${id}/chapters/${cid}/`, {
        method: 'DELETE',
      });
      navigate(`/novels/${id}`);
    } catch (error) {
      console.error('删除失败:', error);
      toast.error('删除失败');
    }
  };

  const handleGenerate = () => {
    if (!content.trim()) {
      toast.warning('请先编辑章节内容');
      return;
    }
    
    navigate(`/novels/${id}/chapters/${cid}/generate`);
  };
  
  // 打开图片预览
  const openImagePreview = (url: string, index: number, images: string[]) => {
    setPreviewImage({ isOpen: true, url, index, images });
  };
  
  // 关闭图片预览
  const closeImagePreview = () => {
    setPreviewImage({ isOpen: false, url: null, index: 0, images: [] });
  };
  
  // 切换图片
  const navigatePreview = (direction: 'prev' | 'next') => {
    if (!previewImage.images.length) return;
    
    let newIndex: number;
    if (direction === 'prev') {
      newIndex = previewImage.index === 0 ? previewImage.images.length - 1 : previewImage.index - 1;
    } else {
      newIndex = previewImage.index === previewImage.images.length - 1 ? 0 : previewImage.index + 1;
    }
    
    setPreviewImage({
      ...previewImage,
      url: previewImage.images[newIndex],
      index: newIndex
    });
  };
  
  // 监听键盘事件
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!previewImage.isOpen) return;
      
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        navigatePreview('prev');
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        navigatePreview('next');
      } else if (e.key === 'Escape') {
        e.preventDefault();
        closeImagePreview();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [previewImage.isOpen, previewImage.index, previewImage.images]);

  const getStatusInfo = (status: Chapter['status']) => {
    switch (status) {
      case 'completed':
        return { icon: CheckCircle, color: 'text-green-600', bg: 'bg-green-50', text: '已完成' };
      case 'failed':
        return { icon: AlertCircle, color: 'text-red-600', bg: 'bg-red-50', text: '失败' };
      case 'parsing':
        return { icon: Loader2, color: 'text-blue-600', bg: 'bg-blue-50', text: '解析中' };
      case 'generating_characters':
        return { icon: Loader2, color: 'text-purple-600', bg: 'bg-purple-50', text: '生成人设' };
      case 'generating_shots':
        return { icon: ImageIcon, color: 'text-orange-600', bg: 'bg-orange-50', text: '生成分镜' };
      case 'generating_videos':
        return { icon: Film, color: 'text-pink-600', bg: 'bg-pink-50', text: '生成视频' };
      case 'compositing':
        return { icon: Film, color: 'text-indigo-600', bg: 'bg-indigo-50', text: '合成中' };
      default:
        return { icon: FileText, color: 'text-gray-600', bg: 'bg-gray-50', text: '待处理' };
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
      </div>
    );
  }

  if (!chapter || !novel) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">章节不存在</p>
        <Link to={`/novels/${id}`} className="text-primary-600 hover:underline mt-2 inline-block">
          返回小说详情
        </Link>
      </div>
    );
  }

  const statusInfo = getStatusInfo(chapter.status);
  const StatusIcon = statusInfo.icon;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link 
            to={`/novels/${id}`}
            className="p-2 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              第{chapter.number}章：{chapter.title}
            </h1>
            <p className="text-sm text-gray-500">{novel.title}</p>
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={handleDelete}
            className="btn-secondary text-red-600 hover:text-red-700 border-red-200 hover:border-red-300"
          >
            <Trash2 className="h-4 w-4 mr-2" />
            删除
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="btn-primary"
          >
            {isSaving ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            保存
          </button>
          <button
            onClick={handleGenerate}
            className="btn-primary bg-green-600 hover:bg-green-700"
            disabled={chapter.status !== 'pending' && chapter.status !== 'failed'}
          >
            <Play className="h-4 w-4 mr-2" />
            生成视频
          </button>
        </div>
      </div>

      {/* Status Bar */}
      <div className={`card ${statusInfo.bg}`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <StatusIcon className={`h-6 w-6 ${statusInfo.color} ${chapter.status !== 'completed' && chapter.status !== 'failed' && chapter.status !== 'pending' ? 'animate-spin' : ''}`} />
            <div>
              <p className={`font-medium ${statusInfo.color}`}>{statusInfo.text}</p>
              {chapter.progress > 0 && (
                <p className="text-sm text-gray-500">进度: {chapter.progress}%</p>
              )}
            </div>
          </div>
          {chapter.status === 'completed' && chapter.finalVideo && (
            <a 
              href={chapter.finalVideo} 
              target="_blank" 
              rel="noopener noreferrer"
              className="btn-primary"
            >
              <Film className="h-4 w-4 mr-2" />
              查看视频
            </a>
          )}
        </div>
      </div>

      {/* Content Editor */}
      <div className="card">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              章节标题
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input-field"
              placeholder="章节标题"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              章节内容
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={20}
              className="input-field font-mono text-sm"
              placeholder="在此输入章节内容..."
            />
            <p className="text-xs text-gray-500 mt-2">
              字数: {content.length} | 建议字数: 1000-5000字
            </p>
          </div>
        </div>
      </div>

      {/* Generated Assets */}
      {Boolean(chapter.characterImages?.length || chapter.shotImages?.length || chapter.shotVideos?.length) && (
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">生成资源</h3>
          
          {/* Character Images */}
          {chapter.characterImages && chapter.characterImages.length > 0 && (
            <div className="mb-6">
              <h4 className="text-sm font-medium text-gray-700 mb-2">人设图</h4>
              <div className="grid grid-cols-4 gap-4">
                {chapter.characterImages.map((img, idx) => (
                  <img 
                    key={idx} 
                    src={img} 
                    alt={`人设${idx + 1}`} 
                    className="rounded-lg cursor-pointer hover:opacity-90 transition-opacity"
                    onClick={() => openImagePreview(img, idx, chapter.characterImages || [])}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Shot Images */}
          {chapter.shotImages && chapter.shotImages.length > 0 && (
            <div className="mb-6">
              <h4 className="text-sm font-medium text-gray-700 mb-2">分镜图</h4>
              <div className="grid grid-cols-4 gap-4">
                {chapter.shotImages.map((img, idx) => (
                  <img 
                    key={idx} 
                    src={img} 
                    alt={`分镜${idx + 1}`} 
                    className="rounded-lg cursor-pointer hover:opacity-90 transition-opacity"
                    onClick={() => openImagePreview(img, idx, chapter.shotImages || [])}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Shot Videos */}
          {chapter.shotVideos && chapter.shotVideos.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">分镜视频</h4>
              <div className="grid grid-cols-2 gap-4">
                {chapter.shotVideos.map((video, idx) => (
                  <video key={idx} src={video} controls className="rounded-lg" />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      
      {/* 图片预览弹窗 */}
      {previewImage.isOpen && previewImage.url && (
        <div 
          className="fixed inset-0 bg-black bg-opacity-90 flex items-center justify-center z-50 p-4"
          onClick={closeImagePreview}
        >
          <div className="relative max-w-5xl max-h-[90vh] w-full flex items-center">
            {/* 左箭头 */}
            <button
              onClick={(e) => { e.stopPropagation(); navigatePreview('prev'); }}
              className="absolute -left-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all"
              title="上一个 (←)"
            >
              <ChevronLeft className="h-10 w-10" />
            </button>
            
            <div className="flex-1">
              {/* 关闭按钮 */}
              <button
                onClick={closeImagePreview}
                className="absolute -top-12 right-0 p-2 text-white hover:text-gray-300 transition-colors"
              >
                <X className="h-8 w-8" />
              </button>
              
              {/* 图片 */}
              <img
                src={previewImage.url}
                alt="预览"
                className="w-full h-full object-contain max-h-[80vh] rounded-lg"
                onClick={(e) => e.stopPropagation()}
              />
              
              {/* 底部提示 */}
              <div className="mt-4 text-center text-gray-400 text-sm">
                <span className="inline-flex items-center gap-2">
                  <kbd className="px-2 py-1 bg-gray-700 rounded text-xs">←</kbd>
                  <kbd className="px-2 py-1 bg-gray-700 rounded text-xs">→</kbd>
                  <span>键盘左右键切换</span>
                  <span className="mx-2">|</span>
                  <span>{previewImage.index + 1} / {previewImage.images.length}</span>
                </span>
              </div>
            </div>
            
            {/* 右箭头 */}
            <button
              onClick={(e) => { e.stopPropagation(); navigatePreview('next'); }}
              className="absolute -right-16 top-1/2 -translate-y-1/2 p-3 text-white hover:text-gray-300 hover:bg-white/10 rounded-full transition-all"
              title="下一个 (→)"
            >
              <ChevronRight className="h-10 w-10" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
