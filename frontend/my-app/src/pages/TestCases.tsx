import { useState, useEffect } from 'react';
import { 
  FlaskConical, 
  Plus, 
  Loader2, 
  Play, 
  Trash2, 
  Edit2,
  CheckCircle,
  BookOpen,
  Users,
  FileText,
  Sparkles,
  ChevronDown,
  ChevronUp,
  AlertCircle
} from 'lucide-react';
import type { TestCase } from '../types';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function TestCases() {
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, any>>({});

  useEffect(() => {
    fetchTestCases();
  }, []);

  const fetchTestCases = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/test-cases`);
      const data = await res.json();
      if (data.success) {
        setTestCases(data.data || []);
      }
    } catch (error) {
      console.error('获取测试用例失败:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchTestCaseDetail = async (id: string) => {
    if (details[id]) {
      setExpandedId(expandedId === id ? null : id);
      return;
    }
    
    try {
      const res = await fetch(`${API_BASE}/test-cases/${id}`);
      const data = await res.json();
      if (data.success) {
        setDetails({ ...details, [id]: data.data });
        setExpandedId(id);
      }
    } catch (error) {
      console.error('获取详情失败:', error);
    }
  };

  const runTestCase = async (testCase: TestCase) => {
    setRunningId(testCase.id);
    try {
      const res = await fetch(`${API_BASE}/test-cases/${testCase.id}/run`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        alert(`测试用例 "${testCase.name}" 已启动！\n\n请前往任务队列查看进度。`);
        window.location.href = '/tasks';
      } else {
        alert('启动失败: ' + data.message);
      }
    } catch (error) {
      console.error('运行测试用例失败:', error);
      alert('运行失败');
    } finally {
      setRunningId(null);
    }
  };

  const handleDelete = async (testCase: TestCase) => {
    if (testCase.isPreset) {
      alert('预设测试用例不能删除');
      return;
    }
    if (!confirm('确定要删除这个测试用例吗？')) return;
    
    try {
      await fetch(`${API_BASE}/test-cases/${testCase.id}`, { method: 'DELETE' });
      setTestCases(testCases.filter(t => t.id !== testCase.id));
    } catch (error) {
      console.error('删除失败:', error);
    }
  };

  const getTypeName = (type: string) => {
    const names: Record<string, string> = {
      'full': '完整流程',
      'character': '仅角色',
      'shot': '仅分镜',
      'video': '仅视频',
    };
    return names[type] || type;
  };

  const getTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      'full': 'bg-purple-100 text-purple-800',
      'character': 'bg-blue-100 text-blue-800',
      'shot': 'bg-green-100 text-green-800',
      'video': 'bg-orange-100 text-orange-800',
    };
    return colors[type] || 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">测试用例</h1>
          <p className="mt-1 text-sm text-gray-500">
            管理测试用例，一键运行AI生成流程测试
          </p>
        </div>
      </div>

      {/* Preset Test Case Highlight */}
      {testCases.filter(t => t.isPreset).map(preset => (
        <div key={preset.id} className="card bg-gradient-to-r from-primary-50 to-purple-50 border-primary-200">
          <div className="flex items-start gap-4">
            <div className="p-3 bg-primary-100 rounded-lg">
              <Sparkles className="h-6 w-6 text-primary-600" />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-gray-900">{preset.name}</h2>
                <span className="px-2 py-0.5 bg-primary-100 text-primary-700 text-xs rounded-full">
                  内置测试
                </span>
              </div>
              <p className="text-sm text-gray-600 mt-1">{preset.description}</p>
              
              <div className="flex items-center gap-6 mt-3 text-sm">
                <span className="flex items-center gap-1 text-gray-600">
                  <BookOpen className="h-4 w-4" />
                  {preset.chapterCount} 章节
                </span>
                <span className="flex items-center gap-1 text-gray-600">
                  <Users className="h-4 w-4" />
                  {preset.characterCount} 角色
                </span>
                <span className={`px-2 py-0.5 rounded text-xs ${getTypeColor(preset.type)}`}>
                  {getTypeName(preset.type)}
                </span>
              </div>

              {preset.notes && (
                <div className="mt-3 p-2 bg-white/50 rounded text-sm text-gray-600">
                  <strong>备注：</strong>{preset.notes}
                </div>
              )}

              <div className="mt-4">
                <button
                  onClick={() => runTestCase(preset)}
                  disabled={runningId === preset.id}
                  className="btn-primary"
                >
                  {runningId === preset.id ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      运行中...
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 mr-2" />
                      运行测试
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      ))}

      {/* All Test Cases */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">所有测试用例</h2>
        
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          </div>
        ) : testCases.length === 0 ? (
          <div className="text-center py-12">
            <FlaskConical className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">暂无测试用例</h3>
          </div>
        ) : (
          <div className="space-y-3">
            {testCases.map((testCase) => (
              <div
                key={testCase.id}
                className="border border-gray-200 rounded-lg overflow-hidden"
              >
                {/* Summary Row */}
                <div 
                  className="p-4 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
                  onClick={() => fetchTestCaseDetail(testCase.id)}
                >
                  <div className="flex items-center gap-4">
                    {expandedId === testCase.id ? (
                      <ChevronUp className="h-5 w-5 text-gray-400" />
                    ) : (
                      <ChevronDown className="h-5 w-5 text-gray-400" />
                    )}
                    
                    {testCase.isPreset ? (
                      <Sparkles className="h-5 w-5 text-primary-500" />
                    ) : (
                      <FlaskConical className="h-5 w-5 text-gray-400" />
                    )}
                    
                    <div>
                      <h3 className="font-medium text-gray-900">{testCase.name}</h3>
                      <p className="text-xs text-gray-500">{testCase.novelTitle}</p>
                    </div>
                    
                    <span className={`px-2 py-0.5 rounded text-xs ${getTypeColor(testCase.type)}`}>
                      {getTypeName(testCase.type)}
                    </span>
                    
                    {testCase.isPreset && (
                      <span className="px-2 py-0.5 bg-primary-100 text-primary-700 text-xs rounded-full">
                        预设
                      </span>
                    )}
                  </div>
                  
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-4 text-sm text-gray-500">
                      <span className="flex items-center gap-1">
                        <BookOpen className="h-4 w-4" />
                        {testCase.chapterCount}
                      </span>
                      <span className="flex items-center gap-1">
                        <Users className="h-4 w-4" />
                        {testCase.characterCount}
                      </span>
                    </div>
                    
                    <div className="flex gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          runTestCase(testCase);
                        }}
                        disabled={runningId === testCase.id}
                        className="p-2 text-gray-400 hover:text-primary-600 transition-colors"
                        title="运行测试"
                      >
                        {runningId === testCase.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                      </button>
                      
                      {!testCase.isPreset && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(testCase);
                          }}
                          className="p-2 text-gray-400 hover:text-red-600 transition-colors"
                          title="删除"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
                
                {/* Expanded Detail */}
                {expandedId === testCase.id && details[testCase.id] && (
                  <div className="border-t border-gray-200 p-4 bg-gray-50">
                    <div className="grid grid-cols-3 gap-4">
                      {/* Novel Info */}
                      <div className="col-span-2">
                        <h4 className="font-medium text-gray-900 mb-2">小说信息</h4>
                        <div className="bg-white rounded p-3">
                          <p><strong>标题：</strong>{details[testCase.id].novel.title}</p>
                          <p><strong>作者：</strong>{details[testCase.id].novel.author || '未知'}</p>
                          <p className="text-sm text-gray-600 mt-1">
                            {details[testCase.id].novel.description}
                          </p>
                        </div>
                        
                        {/* Chapters */}
                        <h4 className="font-medium text-gray-900 mt-4 mb-2">
                          章节列表 ({details[testCase.id].chapters.length})
                        </h4>
                        <div className="bg-white rounded p-3 max-h-40 overflow-y-auto">
                          {details[testCase.id].chapters.map((ch: any) => (
                            <div key={ch.id} className="py-1 border-b border-gray-100 last:border-0">
                              <span className="text-sm text-gray-500">第{ch.number}章</span>
                              <span className="ml-2">{ch.title}</span>
                              <span className="text-xs text-gray-400 ml-2">({ch.contentLength} 字)</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      
                      {/* Characters */}
                      <div>
                        <h4 className="font-medium text-gray-900 mb-2">
                          角色列表 ({details[testCase.id].characters.length})
                        </h4>
                        <div className="bg-white rounded p-3">
                          {details[testCase.id].characters.map((char: any) => (
                            <div key={char.id} className="flex items-center gap-2 py-1">
                              <span className="text-sm">{char.name}</span>
                              {char.hasImage && (
                                <CheckCircle className="h-3 w-3 text-green-500" />
                              )}
                            </div>
                          ))}
                          {details[testCase.id].characters.length === 0 && (
                            <p className="text-sm text-gray-400">暂无角色，请先运行测试</p>
                          )}
                        </div>
                        
                        {testCase.expectedCharacterCount && (
                          <div className="mt-3 p-2 bg-blue-50 rounded text-sm">
                            <strong>预期角色数：</strong>{testCase.expectedCharacterCount}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Usage Guide */}
      <div className="card bg-yellow-50 border-yellow-200">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-yellow-600" />
          使用说明
        </h3>
        <ul className="mt-2 text-sm text-gray-600 space-y-1 list-disc list-inside">
          <li><strong>内置测试</strong>：《小马过河》是系统内置的经典测试用例，包含8个章节和4个主要角色</li>
          <li><strong>运行测试</strong>：点击"运行测试"按钮，系统会自动解析角色、生成形象、制作分镜和视频</li>
          <li><strong>查看进度</strong>：运行后请前往"任务队列"查看实时进度</li>
          <li><strong>查看结果</strong>：完成后可在"角色库"和"小说管理"中查看生成的内容</li>
        </ul>
      </div>
    </div>
  );
}
