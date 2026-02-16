import { useEffect, useState } from 'react';
import { 
  Sparkles, 
  CheckCircle, 
  XCircle, 
  Loader2,
  ArrowRight,
  ChevronRight,
  Book,
  Users,
  FileText,
  FileJson,
  Image as ImageIcon,
  Video,
  Film
} from 'lucide-react';
import { useConfigStore, LLM_PROVIDER_PRESETS } from '../stores/configStore';
import { Link } from 'react-router-dom';

export default function Welcome() {
  const { checkConnection, llmProvider, llmModel, llmApiKey, comfyUIHost } = useConfigStore();
  const [status, setStatus] = useState<{ llm: boolean; comfyui: boolean } | null>(null);
  const [checking, setChecking] = useState(false);
  
  // 获取当前厂商的显示名称
  const currentProvider = LLM_PROVIDER_PRESETS.find(p => p.id === llmProvider);
  const providerName = currentProvider?.name || llmProvider;
  const modelName = llmModel;

  const handleCheck = async () => {
    setChecking(true);
    const result = await checkConnection();
    setStatus(result);
    setChecking(false);
  };

  useEffect(() => {
    handleCheck();
  }, []);

  const isConfigured = llmApiKey && comfyUIHost;

  return (
    <div className="space-y-8">
      {/* Hero Section */}
      <div className="text-center py-12">
        <div className="flex justify-center mb-6">
          <div className="p-4 bg-primary-100 rounded-2xl">
            <Sparkles className="h-16 w-16 text-primary-600" />
          </div>
        </div>
        <h1 className="text-4xl font-bold text-gray-900 mb-4">
          欢迎使用 NovelFlow
        </h1>
        <p className="text-xl text-gray-600 max-w-2xl mx-auto">
          AI 驱动的小说转视频平台。将您的小说自动转换为精彩的视觉作品。
        </p>
      </div>

      {/* Workflow Overview */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 mb-6">工作流程</h2>
        <div className="flex items-center justify-between overflow-x-auto pb-2">
          {[
            { icon: Book, title: '小说', color: 'from-sky-500 to-blue-500' },
            { icon: Sparkles, title: 'AI解析角色', color: 'from-violet-500 to-purple-500' },
            { icon: Users, title: '生成角色图', color: 'from-fuchsia-500 to-pink-500' },
            { icon: FileText, title: '原文内容', color: 'from-blue-500 to-cyan-500' },
            { icon: Sparkles, title: 'AI拆分分镜头', color: 'from-purple-500 to-pink-500' },
            { icon: FileJson, title: 'JSON结构', color: 'from-emerald-500 to-teal-500' },
            { icon: Users, title: '生成合并角色图', color: 'from-orange-500 to-amber-500' },
            { icon: ImageIcon, title: '生成分镜图片', color: 'from-rose-500 to-pink-500' },
            { icon: Video, title: '生成分镜视频', color: 'from-indigo-500 to-violet-500' },
            { icon: Film, title: '生成分镜转场视频', color: 'from-cyan-500 to-blue-500' },
            { icon: CheckCircle, title: '合并视频', color: 'from-green-500 to-emerald-500' },
          ].map((step, index) => (
            <div key={step.title} className="flex items-center flex-shrink-0">
              <div className="flex flex-col items-center">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center mb-2 bg-gradient-to-br ${step.color} text-white shadow-md`}>
                  <step.icon className="h-5 w-5" />
                </div>
                <span className="text-xs font-medium text-gray-700 text-center whitespace-nowrap">
                  {step.title}
                </span>
              </div>
              {index < 10 && (
                <div className="flex items-center flex-1 justify-center mx-1 mb-6">
                  <ChevronRight className="h-5 w-5 text-gray-300" />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* System Status */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold text-gray-900">系统状态</h2>
          <button
            onClick={handleCheck}
            disabled={checking}
            className="btn-secondary text-sm"
          >
            {checking ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                检查中...
              </>
            ) : (
              '重新检查'
            )}
          </button>
        </div>

        <div className="space-y-4">
          {/* AI 服务配置 */}
          <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg ${status?.llm ? 'bg-green-100' : 'bg-red-100'}`}>
                {status?.llm ? (
                  <CheckCircle className="h-5 w-5 text-green-600" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-600" />
                )}
              </div>
              <div>
                <p className="font-medium text-gray-900">{providerName} ({modelName})</p>
                <p className="text-sm text-gray-500">
                  {status?.llm ? '连接正常' : llmApiKey ? '连接失败' : '未配置 API Key'}
                </p>
              </div>
            </div>
            <Link to="/settings" className="text-primary-600 hover:text-primary-700 text-sm font-medium">
              配置
            </Link>
          </div>

          {/* ComfyUI */}
          <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg ${status?.comfyui ? 'bg-green-100' : 'bg-red-100'}`}>
                {status?.comfyui ? (
                  <CheckCircle className="h-5 w-5 text-green-600" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-600" />
                )}
              </div>
              <div>
                <p className="font-medium text-gray-900">ComfyUI</p>
                <p className="text-sm text-gray-500">
                  {status?.comfyui ? '连接正常' : comfyUIHost ? '连接失败' : '未配置地址'}
                </p>
              </div>
            </div>
            <Link to="/settings" className="text-primary-600 hover:text-primary-700 text-sm font-medium">
              配置
            </Link>
          </div>
        </div>

        {!isConfigured && (
          <div className="mt-6 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
            <p className="text-sm text-yellow-800">
              <strong>提示：</strong> 请先完成系统配置，才能开始使用 NovelFlow。
            </p>
          </div>
        )}
      </div>

      {/* Quick Actions */}
      <div className="flex justify-center gap-4">
        <Link
          to="/novels"
          className={`btn-primary ${!isConfigured ? 'opacity-50 cursor-not-allowed' : ''}`}
          onClick={(e) => !isConfigured && e.preventDefault()}
        >
          开始创作
          <ArrowRight className="ml-2 h-4 w-4" />
        </Link>
        <Link to="/settings" className="btn-secondary">
          系统配置
        </Link>
      </div>
    </div>
  );
}
