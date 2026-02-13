import { useState } from 'react';
import { Save, Loader2, Eye, EyeOff, Upload, Edit2, Play, Server, User, Image as ImageIcon, Film, CheckCircle } from 'lucide-react';
import { useConfigStore } from '../stores/configStore';

export default function Settings() {
  const config = useConfigStore();
  const [formData, setFormData] = useState({
    deepseekApiKey: config.deepseekApiKey,
    deepseekApiUrl: config.deepseekApiUrl,
    comfyUIHost: config.comfyUIHost,
    outputResolution: config.outputResolution,
    outputFrameRate: config.outputFrameRate,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    
    // 模拟保存延迟
    await new Promise(resolve => setTimeout(resolve, 500));
    
    config.setConfig(formData);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const resolutions = [
    { value: '1920x1080', label: '1920x1080 (1080p)' },
    { value: '1280x720', label: '1280x720 (720p)' },
    { value: '3840x2160', label: '3840x2160 (4K)' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">系统配置</h1>
        <p className="mt-1 text-sm text-gray-500">
          配置 AI 服务和输出参数
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* AI 配置 */}
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">AI 服务配置</h2>
          <div className="space-y-4">
            <div>
              <label htmlFor="deepseekApiUrl" className="block text-sm font-medium text-gray-700">
                DeepSeek API 地址
              </label>
              <input
                type="url"
                id="deepseekApiUrl"
                value={formData.deepseekApiUrl}
                onChange={(e) => setFormData({ ...formData, deepseekApiUrl: e.target.value })}
                className="input-field mt-1"
                placeholder="https://api.deepseek.com"
              />
            </div>

            <div>
              <label htmlFor="deepseekApiKey" className="block text-sm font-medium text-gray-700">
                DeepSeek API Key
              </label>
              <div className="relative mt-1">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  id="deepseekApiKey"
                  value={formData.deepseekApiKey}
                  onChange={(e) => setFormData({ ...formData, deepseekApiKey: e.target.value })}
                  className="input-field pr-10"
                  placeholder="sk-..."
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-500"
                >
                  {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p className="mt-1 text-xs text-gray-500">
                您的 API Key 仅存储在本地浏览器中
              </p>
            </div>

          </div>
        </div>

        {/* 输出配置 */}
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">输出配置</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label htmlFor="resolution" className="block text-sm font-medium text-gray-700">
                输出分辨率
              </label>
              <select
                id="resolution"
                value={formData.outputResolution}
                onChange={(e) => setFormData({ ...formData, outputResolution: e.target.value })}
                className="input-field mt-1"
              >
                {resolutions.map((res) => (
                  <option key={res.value} value={res.value}>
                    {res.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="frameRate" className="block text-sm font-medium text-gray-700">
                帧率 (FPS)
              </label>
              <input
                type="number"
                id="frameRate"
                min="1"
                max="60"
                value={formData.outputFrameRate}
                onChange={(e) => setFormData({ ...formData, outputFrameRate: parseInt(e.target.value) })}
                className="input-field mt-1"
              />
            </div>
          </div>
        </div>

        {/* ComfyUI 服务器配置 */}
        <div className="card">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-purple-100 rounded-lg">
                <Server className="h-5 w-5 text-purple-600" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-900">ComfyUI 配置</h2>
                <p className="text-sm text-gray-500">本地AI模型服务配置</p>
              </div>
            </div>
            <button
              type="button"
              className="btn-secondary text-sm"
              onClick={() => alert('测试全部工作流连接')}
            >
              测试全部
            </button>
          </div>

          {/* 服务器地址 */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              服务器地址
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={formData.comfyUIHost}
                onChange={(e) => setFormData({ ...formData, comfyUIHost: e.target.value })}
                className="input-field flex-1"
                placeholder="http://localhost:8188"
              />
              <span className="inline-flex items-center px-3 py-2 rounded-lg text-sm font-medium bg-green-100 text-green-700">
                <CheckCircle className="h-4 w-4 mr-1" />
                已连接
              </span>
            </div>
          </div>

          {/* 工作流列表 */}
          <div className="space-y-4">
            {/* 人设生成工作流 */}
            <div className="p-4 bg-gray-50 rounded-xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-blue-100 rounded-lg">
                    <User className="h-5 w-5 text-blue-600" />
                  </div>
                  <div>
                    <h3 className="font-medium text-gray-900">人设生成工作流</h3>
                    <p className="text-sm text-gray-500">工作流: z-image</p>
                  </div>
                </div>
                <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
                  已配置
                </span>
              </div>
              <div className="flex gap-2 mt-3">
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('上传工作流文件')}
                >
                  <Upload className="h-4 w-4" />
                  重新上传
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('查看/编辑工作流')}
                >
                  <Edit2 className="h-4 w-4" />
                  查看/编辑
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('测试工作流')}
                >
                  <Play className="h-4 w-4" />
                  测试
                </button>
              </div>
            </div>

            {/* 分镜生图工作流 */}
            <div className="p-4 bg-gray-50 rounded-xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-amber-100 rounded-lg">
                    <ImageIcon className="h-5 w-5 text-amber-600" />
                  </div>
                  <div>
                    <h3 className="font-medium text-gray-900">分镜生图工作流</h3>
                    <p className="text-sm text-gray-500">工作流: qwen-edit-2511</p>
                  </div>
                </div>
                <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
                  已配置
                </span>
              </div>
              <div className="flex gap-2 mt-3">
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('上传工作流文件')}
                >
                  <Upload className="h-4 w-4" />
                  重新上传
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('查看/编辑工作流')}
                >
                  <Edit2 className="h-4 w-4" />
                  查看/编辑
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('测试工作流')}
                >
                  <Play className="h-4 w-4" />
                  测试
                </button>
              </div>
            </div>

            {/* 分镜生视频工作流 */}
            <div className="p-4 bg-gray-50 rounded-xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-pink-100 rounded-lg">
                    <Film className="h-5 w-5 text-pink-600" />
                  </div>
                  <div>
                    <h3 className="font-medium text-gray-900">分镜生视频工作流</h3>
                    <p className="text-sm text-gray-500">工作流: ltx-2</p>
                  </div>
                </div>
                <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
                  已配置
                </span>
              </div>
              <div className="flex gap-2 mt-3">
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('上传工作流文件')}
                >
                  <Upload className="h-4 w-4" />
                  重新上传
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('查看/编辑工作流')}
                >
                  <Edit2 className="h-4 w-4" />
                  查看/编辑
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                  onClick={() => alert('测试工作流')}
                >
                  <Play className="h-4 w-4" />
                  测试
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 保存按钮 */}
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={saving}
            className="btn-primary"
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                保存中...
              </>
            ) : saved ? (
              <>
                <Save className="mr-2 h-4 w-4" />
                已保存
              </>
            ) : (
              <>
                <Save className="mr-2 h-4 w-4" />
                保存配置
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
