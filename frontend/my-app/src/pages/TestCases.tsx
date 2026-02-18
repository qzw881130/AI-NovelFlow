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
import { toast } from '../stores/toastStore';
import { useTranslation } from '../stores/i18nStore';

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export default function TestCases() {
  const { t } = useTranslation();
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
      const res = await fetch(`${API_BASE}/test-cases/`);
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
      const res = await fetch(`${API_BASE}/test-cases/${id}/`);
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
      const res = await fetch(`${API_BASE}/test-cases/${testCase.id}/run/`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        toast.success(t('testCases.testStarted', { name: getTestCaseName(testCase) }));
        window.location.href = '/tasks';
      } else {
        toast.error('启动失败: ' + data.message);
      }
    } catch (error) {
      console.error('运行测试用例失败:', error);
      toast.error('运行失败');
    } finally {
      setRunningId(null);
    }
  };

  const handleDelete = async (testCase: TestCase) => {
    if (testCase.isPreset) {
      toast.warning(t('testCases.cannotDeletePreset'));
      return;
    }
    if (!confirm(t('testCases.confirmDelete'))) return;
    
    try {
      await fetch(`${API_BASE}/test-cases/${testCase.id}/`, { method: 'DELETE' });
      setTestCases(testCases.filter(t => t.id !== testCase.id));
    } catch (error) {
      console.error('删除失败:', error);
    }
  };

  const getTypeName = (type: string) => {
    return t(`testCases.types.${type}`, { defaultValue: type });
  };

  // 获取测试用例显示名称（预设的使用翻译键）
  const getTestCaseName = (testCase: TestCase): string => {
    if (testCase.isPreset && testCase.nameKey) {
      return t(testCase.nameKey, { defaultValue: testCase.name });
    }
    return testCase.name;
  };

  // 获取测试用例显示描述（预设的使用翻译键）
  const getTestCaseDescription = (testCase: TestCase): string => {
    if (testCase.isPreset && testCase.descriptionKey) {
      return t(testCase.descriptionKey, { defaultValue: testCase.description || '' });
    }
    return testCase.description || '';
  };

  // 获取测试用例备注（预设的使用翻译键）
  const getTestCaseNotes = (testCase: TestCase): string => {
    if (testCase.isPreset && testCase.notesKey) {
      return t(testCase.notesKey, { defaultValue: testCase.notes || '' });
    }
    return testCase.notes || '';
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
          <h1 className="text-2xl font-bold text-gray-900">{t('testCases.title')}</h1>
          <p className="mt-1 text-sm text-gray-500">
            {t('testCases.subtitle')}
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
                <h2 className="text-lg font-semibold text-gray-900">{getTestCaseName(preset)}</h2>
                <span className="px-2 py-0.5 bg-primary-100 text-primary-700 text-xs rounded-full">
                  {t('testCases.presetTest')}
                </span>
              </div>
              <p className="text-sm text-gray-600 mt-1">{getTestCaseDescription(preset)}</p>
              
              <div className="flex items-center gap-6 mt-3 text-sm">
                <span className="flex items-center gap-1 text-gray-600">
                  <BookOpen className="h-4 w-4" />
                  {t('testCases.chapterCount', { count: preset.chapterCount })}
                </span>
                <span className="flex items-center gap-1 text-gray-600">
                  <Users className="h-4 w-4" />
                  {t('testCases.characterCount', { count: preset.characterCount })}
                </span>
                <span className={`px-2 py-0.5 rounded text-xs ${getTypeColor(preset.type)}`}>
                  {getTypeName(preset.type)}
                </span>
              </div>

              {preset.notes && (
                <div className="mt-3 p-2 bg-white/50 rounded text-sm text-gray-600">
                  <strong>{t('testCases.notes')}</strong>{getTestCaseNotes(preset)}
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
                      {t('testCases.running')}
                    </>
                  ) : (
                    <>
                      <Play className="h-4 w-4 mr-2" />
                      {t('testCases.runTest')}
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
        <h2 className="text-lg font-semibold text-gray-900 mb-4">{t('testCases.allTestCases')}</h2>
        
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          </div>
        ) : testCases.length === 0 ? (
          <div className="text-center py-12">
            <FlaskConical className="mx-auto h-12 w-12 text-gray-300" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">{t('testCases.noTestCases')}</h3>
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
                      <h3 className="font-medium text-gray-900">{getTestCaseName(testCase)}</h3>
                      <p className="text-xs text-gray-500">{testCase.novelTitle}</p>
                    </div>
                    
                    <span className={`px-2 py-0.5 rounded text-xs ${getTypeColor(testCase.type)}`}>
                      {getTypeName(testCase.type)}
                    </span>
                    
                    {testCase.isPreset && (
                      <span className="px-2 py-0.5 bg-primary-100 text-primary-700 text-xs rounded-full">
                        {t('testCases.preset')}
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
                        title={t('testCases.runTest')}
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
                          title={t('common.delete')}
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
                        <h4 className="font-medium text-gray-900 mb-2">{t('testCases.novelInfo')}</h4>
                        <div className="bg-white rounded p-3">
                          <p><strong>{t('testCases.novelTitle')}</strong>{details[testCase.id].novel.title}</p>
                          <p><strong>{t('testCases.novelAuthor')}</strong>{details[testCase.id].novel.author || t('testCases.unknown')}</p>
                          <p className="text-sm text-gray-600 mt-1">
                            {details[testCase.id].novel.description}
                          </p>
                        </div>
                        
                        {/* Chapters */}
                        <h4 className="font-medium text-gray-900 mt-4 mb-2">
                          {t('testCases.chapterList')} ({details[testCase.id].chapters.length})
                        </h4>
                        <div className="bg-white rounded p-3 max-h-40 overflow-y-auto">
                          {details[testCase.id].chapters.map((ch: any) => (
                            <div key={ch.id} className="py-1 border-b border-gray-100 last:border-0">
                              <span className="text-sm text-gray-500">{t('testCases.chapterNumber', { number: ch.number })}</span>
                              <span className="ml-2">{ch.title}</span>
                              <span className="text-xs text-gray-400 ml-2">({ch.contentLength} {t('testCases.words')})</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      
                      {/* Characters */}
                      <div>
                        <h4 className="font-medium text-gray-900 mb-2">
                          {t('testCases.characterList')} ({details[testCase.id].characters.length})
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
                            <p className="text-sm text-gray-400">{t('testCases.noCharacters')}</p>
                          )}
                        </div>
                        
                        {testCase.expectedCharacterCount && (
                          <div className="mt-3 p-2 bg-blue-50 rounded text-sm">
                            <strong>{t('testCases.expectedCharacterCount')}</strong>{testCase.expectedCharacterCount}
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
          {t('testCases.usageGuide')}
        </h3>
        <ul className="mt-2 text-sm text-gray-600 space-y-1 list-disc list-inside">
          <li dangerouslySetInnerHTML={{ __html: t('testCases.guide.presetTest') }} />
          <li dangerouslySetInnerHTML={{ __html: t('testCases.guide.runTest') }} />
          <li dangerouslySetInnerHTML={{ __html: t('testCases.guide.checkProgress') }} />
          <li dangerouslySetInnerHTML={{ __html: t('testCases.guide.viewResults') }} />
        </ul>
      </div>
    </div>
  );
}
