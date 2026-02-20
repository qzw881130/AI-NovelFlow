import { useState, useEffect } from 'react';
import { 
  Plus, 
  Edit2, 
  Trash2, 
  Loader2,
  Save,
  X,
  Eye,
  FileText,
  BookOpen,
  Copy
} from 'lucide-react';
import { toast } from '../stores/toastStore';
import { useTranslation } from '../stores/i18nStore';

interface PromptTemplate {
  id: string;
  name: string;
  nameKey?: string;
  description: string;
  descriptionKey?: string;
  template: string;
  type: string;
  isSystem: boolean;
  isActive: boolean;
  createdAt: string;
}

const API_BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

// 获取模板显示名称（系统预设的使用翻译键）
const getTemplateDisplayName = (template: PromptTemplate, t: any): string => {
  if (template.isSystem && template.nameKey) {
    return t(template.nameKey, { defaultValue: template.name });
  }
  return template.name;
};

// 获取模板显示描述（系统预设的使用翻译键）
const getTemplateDisplayDescription = (template: PromptTemplate, t: any): string => {
  if (template.isSystem && template.descriptionKey) {
    return t(template.descriptionKey, { defaultValue: template.description });
  }
  return template.description;
};

// 默认AI解析角色系统提示词
const DEFAULT_PARSE_CHARACTERS_PROMPT = `你是一个专业的小说解析助手。请分析我提供的小说文本，提取以下信息并以 JSON 格式返回：

1) characters：角色列表。每个角色必须包含：
- name（姓名）
- description（描述）
- appearance（外貌特征：必须是一段完整自然语言描述的"单段文字"，禁止使用结构化字段/键值对/列表/分段标题）

【角色命名唯一性与一致性（必须严格执行）】
- 所有角色 name 必须在首次解析时确定为唯一标准名称，并在后续所有步骤中严格复用该名称。
- 若同类型角色存在多个且无真实姓名，必须按首次出场顺序使用阿拉伯数字编号命名（如"骗子1""骗子2""士兵1""士兵2"）。
- 禁止使用"甲/乙""A/B""其中一人""另一人""某官员"等非唯一或会变化的称呼。
- 一旦 name 确定，后续输出不得更改、简化或替换；所有角色引用必须完全一致。

【群体称谓抽取规则（必须执行）】
当正文出现以下群体称谓：众人/群臣/士兵/百姓/侍从/随从/围观者/人群（含同义词，如"大家""围观的人""侍卫""兵丁""宫人""下人""臣子们"等），必须将其作为可出镜角色类型提取进 characters。
规则：
1) 不允许直接输出未编号的群体名称（禁止：众人、群臣、士兵、百姓、侍从、随从、围观者、人群）。
2) 必须按首次出场顺序拆分并编号命名为具体角色（默认 2 个；若文本明确人数更多，可输出到 3–5 个，最多不超过 5 个）：
   - 群臣1、群臣2…
   - 士兵1、士兵2…
   - 百姓1、百姓2…
   - 侍从1、侍从2…
   - 随从1、随从2…
   - 围观者1、围观者2…
3) 若同一段落同时出现多个群体称谓，必须分别建立编号角色（例如既有群臣又有侍从，则输出 群臣1/2 + 侍从1/2）。
4) 每个群体编号角色也必须给出 description 与 appearance；可以共享基础外观模板，但必须用细节区分（年龄/体型/服饰配色/站位/表情/动作/配饰等），确保可用于 AI 绘图。
5) 这些编号角色一旦生成，后续输出必须始终复用同名，不得改名、合并或替换。

【appearance（外貌特征）写作硬性约束 | 必须遵守】
- appearance 必须是"一段话"（单段自然语言），禁止输出 JSON 子对象、字段分组、项目符号列表、编号小节、冒号键值对。
- 每个角色的 appearance 必须描述"只包含 1 个主体"的外貌，身份必须稳定一致，禁止漂移或换脸。
- appearance 必须明确为"全身照/全身构图"（full-body shot）：从头到脚完整可见，站姿或自然姿态，四肢完整，不裁切，不缺手缺脚；同时写清鞋子/脚部外观或动物爪部细节；服装需覆盖上装/下装/鞋袜（或动物全身毛色/四肢/尾巴）。
- appearance 这段话必须覆盖并明确以下要点（必须全部写进同一段文字里）：
  A) 物种与身份：物种（人类/动物物种+品种）、性别/气质、年龄段（含大约年龄）、体型与身高/大小、2–6 个独特身份标记（必须可视化且可复现，如痣的位置、疤痕、条纹/色块分布、异色瞳、独特配饰的固定位置等）。
  B) 头部与脸型：脸型/头型、面部比例（如中庭偏长/下颌偏宽等）、额头/颧骨/下颌线/下巴特征；动物需补充口鼻长度、头骨宽窄、耳根位置。
  C) 眼睛：眼型、大小、虹膜颜色、眼角走向、眼皮类型；动物补充瞳孔形态；强调"眼型与眼睛颜色不得改变"。
  D) 鼻子/口鼻部：鼻梁/鼻尖/鼻翼宽度/鼻孔大小与角度；动物补充鼻镜颜色、胡须垫是否明显。
  E) 嘴/喙/下颌：嘴唇厚薄、嘴角走向、是否露齿；动物补充喙/尖牙可见度等。
  F) 皮肤/毛发/羽毛/鳞片：表面类型、基础颜色（皮肤含冷暖底调）、质感细节、花纹/色块"精确位置映射"（必须可复现）。
  G) 头发/鬃毛/冠羽/耳朵：发质、长度、发色、分发与发际线；动物补充耳形与耳毛簇、鬃毛/冠羽长度等。
  H) 胡须/面部毛：胡子/胡茬/胡须长度与颜色（如适用）。
  I) 与身份绑定的配饰：如眼镜/项圈/吊牌/头饰等，必须写清"类型 + 固定位置"，如指定则必须保留。
  J) 比例与解剖规则：明确"保持面部比例、头身比、耳朵大小、口鼻长度、花纹位置与所有独特标记一致；禁止改物种/品种；禁止改变年龄段与性别气质呈现"。

【负面约束（必须体现在输出约束中）】
- 禁止改变：眼睛颜色、眼型、脸型、口鼻长度、毛皮/皮肤花纹的精确位置、独特标记、发型轮廓。
- 禁止：额外主体、换脸、身份漂移、左右不对称 bug、畸形解剖、随机疤痕/纹身、无故新增配饰或标记。
- 禁止裁切：不许半身照、特写、缺腿缺脚、脚部出画、手部残缺或被遮挡导致不可见。

【输出格式要求（必须严格执行）】
- 只返回合法 JSON，不得输出任何解释性文字。
- JSON 顶层结构必须为：
{
  "characters": [
    {
      "name": "...",
      "description": "...",
      "appearance": "..."
    }
  ]
}
- appearance 必须是纯字符串的一段话（一个 string），不得是对象、数组、或多段分行结构。`;

// 默认人设提示词模板
const DEFAULT_CHARACTER_TEMPLATE = "character portrait, anime style, high quality, detailed, {appearance}, {description}, single character, centered, clean background, professional artwork, 8k";

// 默认章节拆分提示词模板
const DEFAULT_CHAPTER_SPLIT_TEMPLATE = `你是一名资深影视导演、分镜设计师、动画脚本结构专家。

任务：
将用户提供的小说章节内容，拆分为适用于AI动画制作的分镜数据结构。

核心要求：

1. 严格按照影视镜头语言拆分
2. 每个分镜必须是"可直接用于AI生图/生视频"的结构化画面描述
3. 每个镜头 description 必须包含：
   - Scene（场景环境 + 光线 + 摄影机）
   - Characters（逐个角色锁定形象 + 服装关键词 + 当前动作）
   - Action（一句话总结镜头主行为）
4. description 总长度控制在 80-140 字之间（必须包含完整结构）
5. 所有视觉描述必须符合：{图像风格}
6. 不允许普通叙事句
7. 不允许心理描写
8. 不允许解释性文字
9. 输出必须是纯 JSON
10. 不允许 Markdown

强制镜头结构模板（description 必须严格使用）：

Scene: {中文场景环境句子}, {光线描述}, {镜头类型与机位描述}, {图像风格}。
Characters:
- {角色名1}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; {宋代服饰关键词}; {当前镜头动作}.
- {角色名2}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; {宋代服饰关键词}; {当前镜头动作}.
Action: {一句话概括主要角色正在发生的动作行为}。

分镜规则：

- id：从1递增
- characters：当前镜头出现角色
- scene：当前镜头所在场景
- duration：3-10秒，根据动作复杂度自动判断

时长规则：

- 静态画面：3-5秒
- 对话画面：5-8秒
- 动作冲突：6-10秒

禁止：
- 不得输出 image_path、image_url 等字段
- 不得添加额外键
- 不得改变剧情
- 不得合并多个剧情行为到一个镜头
- 不得省略 Scene / Characters / Action 任意一部分


输出格式必须严格如下：

{
    "chapter": "第3章 客人",
    "characters": [
        "萧炎",
        "萧战",
        "葛叶"
    ],
    "scenes": [
        "萧家门口",
        "萧家大厅",
        "练武场"
    ],
    "shots": [
        {
            "id": 1,
            "description": "萧炎站在萧家门口，仰望牌匾",
            "characters": [
                "萧炎"
            ],
            "scene": "萧家门口",
            "duration": 5
        },
        {
            "id": 2,
            "description": "萧战从大厅走出，面带忧色",
            "characters": [
                "萧战"
            ],
            "scene": "萧家大厅",
            "duration": 8
        }
    ]
}`;

export default function PromptConfig() {
  const { t } = useTranslation();
  
  // AI解析角色系统提示词
  const [parsePrompt, setParsePrompt] = useState(DEFAULT_PARSE_CHARACTERS_PROMPT);
  const [savingParsePrompt, setSavingParsePrompt] = useState(false);
  
  // 人设提示词状态
  const [characterTemplates, setCharacterTemplates] = useState<PromptTemplate[]>([]);
  const [loadingCharacter, setLoadingCharacter] = useState(true);
  
  // 章节拆分提示词状态
  const [chapterSplitTemplates, setChapterSplitTemplates] = useState<PromptTemplate[]>([]);
  const [loadingChapterSplit, setLoadingChapterSplit] = useState(true);
  
  // 模态框状态
  const [showModal, setShowModal] = useState(false);
  const [showViewModal, setShowViewModal] = useState(false);
  const [modalType, setModalType] = useState<'character' | 'chapter_split'>('character');
  const [editingPrompt, setEditingPrompt] = useState<PromptTemplate | null>(null);
  const [viewingPrompt, setViewingPrompt] = useState<PromptTemplate | null>(null);
  const [form, setForm] = useState({ 
    name: '', 
    description: '', 
    template: DEFAULT_CHARACTER_TEMPLATE,
    wordCount: 50  // 每个分镜对应拆分故事字数
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetchCharacterTemplates();
    fetchChapterSplitTemplates();
  }, []);

  // 从后端加载保存的提示词
  useEffect(() => {
    const fetchParsePrompt = async () => {
      try {
        const res = await fetch(`${API_BASE}/config/`);
        const data = await res.json();
        if (data.success && data.data) {
          if (data.data.parseCharactersPrompt) {
            setParsePrompt(data.data.parseCharactersPrompt);
          }
        }
      } catch (error) {
        console.error('加载配置失败:', error);
      }
    };
    fetchParsePrompt();
  }, []);

  const fetchCharacterTemplates = async () => {
    setLoadingCharacter(true);
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/?type=character`);
      const data = await res.json();
      if (data.success) {
        setCharacterTemplates(data.data);
      }
    } catch (error) {
      console.error('加载人设提示词模板失败:', error);
    } finally {
      setLoadingCharacter(false);
    }
  };

  const fetchChapterSplitTemplates = async () => {
    setLoadingChapterSplit(true);
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/?type=chapter_split`);
      const data = await res.json();
      if (data.success) {
        setChapterSplitTemplates(data.data);
      }
    } catch (error) {
      console.error('加载章节拆分提示词模板失败:', error);
    } finally {
      setLoadingChapterSplit(false);
    }
  };

  const handleOpenModal = (type: 'character' | 'chapter_split', template?: PromptTemplate) => {
    setModalType(type);
    if (template) {
      setEditingPrompt(template);
      // 从模板内容中提取字数设置（如果是章节拆分类型）
      let wordCount = 50;
      if (type === 'chapter_split') {
        const match = template.template.match(/必须控制\s*{?每个分镜对应拆分故事字数}?\s*左右/);
        if (match) {
          // 尝试从模板中提取已设置的字数
          const numMatch = template.template.match(/必须控制\s*(\d+)\s*字/);
          if (numMatch) {
            wordCount = parseInt(numMatch[1]);
          }
        }
      }
      setForm({
        name: template.name,
        description: template.description,
        template: template.template,
        wordCount
      });
    } else {
      setEditingPrompt(null);
      setForm({ 
        name: '', 
        description: '', 
        template: type === 'character' ? DEFAULT_CHARACTER_TEMPLATE : DEFAULT_CHAPTER_SPLIT_TEMPLATE,
        wordCount: 50
      });
    }
    setShowModal(true);
  };

  const handleOpenViewModal = (template: PromptTemplate) => {
    setViewingPrompt(template);
    setShowViewModal(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      // 处理章节拆分提示词中的字数占位符
      let templateContent = form.template;
      if (modalType === 'chapter_split') {
        // 替换或插入字数设置
        templateContent = templateContent.replace(
          /每个分镜的剧情字数必须控制\s*{?每个分镜对应拆分故事字数}?\s*左右/,
          `每个分镜的剧情字数必须控制 ${form.wordCount} 字左右`
        );
        // 同时更新占位符的默认值
        templateContent = templateContent.replace(
          /{每个分镜对应拆分故事字数}/g,
          `${form.wordCount}`
        );
      }

      const url = editingPrompt 
        ? `${API_BASE}/prompt-templates/${editingPrompt.id}/`
        : `${API_BASE}/prompt-templates/`;
      
      const method = editingPrompt ? 'PUT' : 'POST';
      
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name,
          description: form.description,
          template: templateContent,
          type: modalType
        })
      });
      
      const data = await res.json();
      
      if (data.success) {
        toast.success(editingPrompt ? t('common.success') : t('common.success'));
        setShowModal(false);
        if (modalType === 'character') {
          fetchCharacterTemplates();
        } else {
          fetchChapterSplitTemplates();
        }
      } else {
        toast.error(data.message || t('common.saveFailed'));
      }
    } catch (error) {
      console.error('保存提示词模板失败:', error);
      toast.error(t('common.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = async (template: PromptTemplate) => {
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/${template.id}/copy`, {
        method: 'POST'
      });
      const data = await res.json();
      
      if (data.success) {
        toast.success(t('promptConfig.copySuccess'));
        if (template.type === 'character') {
          fetchCharacterTemplates();
        } else {
          fetchChapterSplitTemplates();
        }
      } else {
        toast.error(data.message || t('common.copyFailed'));
      }
    } catch (error) {
      console.error('复制提示词模板失败:', error);
      toast.error(t('common.copyFailed'));
    }
  };

  const handleDelete = async (template: PromptTemplate) => {
    if (!confirm(`${t('promptConfig.confirmDelete')} "${template.name}" ?`)) return;
    
    try {
      const res = await fetch(`${API_BASE}/prompt-templates/${template.id}/`, {
        method: 'DELETE'
      });
      const data = await res.json();
      if (data.success) {
        if (template.type === 'character') {
          fetchCharacterTemplates();
        } else {
          fetchChapterSplitTemplates();
        }
      } else {
        toast.error(data.message || t('common.deleteFailed'));
      }
    } catch (error) {
      console.error('删除提示词模板失败:', error);
      toast.error(t('common.deleteFailed'));
    }
  };

  const handleSaveParsePrompt = async () => {
    setSavingParsePrompt(true);
    try {
      // 保存到后端数据库
      const res = await fetch(`${API_BASE}/config/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parseCharactersPrompt: parsePrompt
        })
      });
      
      if (res.ok) {
        toast.success(t('promptConfig.systemPromptSaved'));
      } else {
        toast.error(t('common.saveFailed'));
      }
    } catch (error) {
      console.error('保存提示词失败:', error);
      toast.error('保存失败');
    } finally {
      setSavingParsePrompt(false);
    }
  };

  const handleResetParsePrompt = async () => {
    setParsePrompt(DEFAULT_PARSE_CHARACTERS_PROMPT);
    // 同时重置后端的提示词
    try {
      await fetch(`${API_BASE}/config/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parseCharactersPrompt: DEFAULT_PARSE_CHARACTERS_PROMPT
        })
      });
      toast.success(t('promptConfig.resetSuccess'));
    } catch (error) {
      toast.success(t('promptConfig.resetSuccessFrontend'));
    }
  };

  // 渲染提示词列表
  const renderTemplateList = (templates: PromptTemplate[], loading: boolean, type: 'character' | 'chapter_split') => {
    if (loading) {
      return (
        <div className="flex justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
        </div>
      );
    }

    if (templates.length === 0) {
      return <p className="text-sm text-gray-500 py-4">{t('promptConfig.noTemplates')}</p>;
    }

    return (
      <div className="space-y-3">
        {templates.map((template) => (
          <div 
            key={template.id} 
            className="flex items-center justify-between p-4 rounded-lg border border-gray-200 hover:border-gray-300 bg-white transition-colors"
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <h4 className="font-medium text-gray-900">{getTemplateDisplayName(template, t)}</h4>
                {template.isSystem ? (
                  <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-600 rounded-full">{t('promptConfig.systemDefault')}</span>
                ) : (
                  <span className="text-xs px-2 py-0.5 bg-green-100 text-green-600 rounded-full">{t('promptConfig.userCustom')}</span>
                )}
              </div>
              <p className="text-sm text-gray-500 truncate">{getTemplateDisplayDescription(template, t)}</p>
              <p className="text-xs text-gray-400 mt-1 truncate font-mono">
                {template.template.substring(0, type === 'chapter_split' ? 120 : 80)}...
              </p>
            </div>
            <div className="flex items-center gap-1 ml-4">
              {template.isSystem ? (
                <>
                  <button
                    type="button"
                    onClick={() => handleOpenViewModal(template)}
                    className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
                    title={t('common.view')}
                  >
                    <Eye className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleCopy(template)}
                    className="p-1.5 text-gray-400 hover:text-green-600 hover:bg-green-100 rounded transition-colors"
                    title={t('promptConfig.copyAsUser')}
                  >
                    <Copy className="h-4 w-4" />
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => handleOpenViewModal(template)}
                    className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
                    title={t('common.view')}
                  >
                    <Eye className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleOpenModal(type, template)}
                    className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
                    title={t('common.edit')}
                  >
                    <Edit2 className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(template)}
                    className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-100 rounded transition-colors"
                    title={t('common.delete')}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">{t('promptConfig.title')}</h1>
        <p className="mt-1 text-sm text-gray-500">
          {t('promptConfig.subtitle')}
        </p>
      </div>

      {/* AI解析角色系统提示词 */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <svg className="h-5 w-5 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <h2 className="text-lg font-semibold text-gray-900">{t('promptConfig.parseCharactersPrompt')}</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleResetParsePrompt}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
            >
              <X className="h-4 w-4" />
              {t('promptConfig.resetToDefault')}
            </button>
            <button
              type="button"
              onClick={handleSaveParsePrompt}
              disabled={savingParsePrompt}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors disabled:opacity-50"
            >
              <Save className="h-4 w-4" />
              {savingParsePrompt ? t('common.saving') : t('common.save')}
            </button>
          </div>
        </div>
        <textarea
          rows={12}
          value={parsePrompt}
          onChange={(e) => setParsePrompt(e.target.value)}
          className="input-field font-mono text-sm w-full"
          placeholder="输入 AI 解析角色时的系统提示词..."
        />
        <p className="text-xs text-gray-500 mt-2">
          {t('promptConfig.promptTip')}
        </p>
      </div>

      {/* AI角色提示词管理 */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-purple-600" />
            <h2 className="text-lg font-semibold text-gray-900">{t('promptConfig.characterPrompts')}</h2>
          </div>
          <button
            type="button"
            onClick={() => handleOpenModal('character')}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors"
          >
            <Plus className="h-4 w-4" />
            {t('promptConfig.newPrompt')}
          </button>
        </div>
        {renderTemplateList(characterTemplates, loadingCharacter, 'character')}
      </div>

      {/* AI拆分分镜提示词管理 */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-orange-600" />
            <h2 className="text-lg font-semibold text-gray-900">{t('promptConfig.chapterSplitPrompts')}</h2>
          </div>
          <button
            type="button"
            onClick={() => handleOpenModal('chapter_split')}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-primary-600 hover:text-primary-700 hover:bg-primary-50 rounded-md transition-colors"
          >
            <Plus className="h-4 w-4" />
            {t('promptConfig.newPrompt')}
          </button>
        </div>
        {renderTemplateList(chapterSplitTemplates, loadingChapterSplit, 'chapter_split')}
      </div>

      {/* 编辑/创建模态框 */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">
                {editingPrompt ? (editingPrompt.isSystem ? t('promptConfig.viewPrompt') : t('promptConfig.editPrompt')) : t('promptConfig.createPrompt')}
                {editingPrompt?.isSystem && (
                  <span className="ml-2 text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">{t('promptConfig.systemPresetReadonly')}</span>
                )}
              </h3>
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('common.name')}</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('promptConfig.namePlaceholder')}
                  readOnly={editingPrompt?.isSystem}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700">{t('common.description')}</label>
                <textarea
                  rows={2}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="input-field mt-1"
                  placeholder={t('promptConfig.descPlaceholder')}
                  readOnly={editingPrompt?.isSystem}
                />
              </div>

              {/* 章节拆分特有：字数设置 */}
              {modalType === 'chapter_split' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700">
                    {t('promptConfig.wordCountPerShot')}
                  </label>
                  <div className="flex items-center gap-2 mt-1">
                    <input
                      type="number"
                      min={10}
                      max={500}
                      value={form.wordCount}
                      onChange={(e) => setForm({ ...form, wordCount: parseInt(e.target.value) || 50 })}
                      className="input-field w-24"
                      readOnly={editingPrompt?.isSystem}
                    />
                    <span className="text-sm text-gray-500">{t('promptConfig.wordUnit')}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    {t('promptConfig.wordCountTip')}
                  </p>
                </div>
              )}
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('promptConfig.promptTemplate')}
                  <span className="text-xs text-gray-500 ml-2">
                    {modalType === 'character' 
                      ? t('promptConfig.placeholderTip')
                      : t('promptConfig.placeholderTipChapter')
                    }
                  </span>
                </label>
                <div className="mb-2 p-2 bg-red-50 border border-red-200 rounded-md">
                  <p className="text-xs text-red-600 font-medium flex items-center gap-1">
                    <svg className="h-4 w-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                    </svg>
                    {t('promptConfig.jsonStructureWarning')}
                  </p>
                </div>
                <textarea
                  rows={modalType === 'chapter_split' ? 12 : 6}
                  required
                  value={form.template}
                  onChange={(e) => setForm({ ...form, template: e.target.value })}
                  className="input-field font-mono text-sm"
                  placeholder={modalType === 'character' ? t('promptConfig.templatePlaceholderCharacter') : t('promptConfig.templatePlaceholderChapter')}
                  readOnly={editingPrompt?.isSystem}
                />
                <p className="text-xs text-gray-500 mt-1">
                  {modalType === 'character' 
                    ? t('promptConfig.tipCharacter')
                    : t('promptConfig.tipChapter')
                  }
                </p>
              </div>
              
              <div className="flex justify-end gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="btn-secondary"
                >
                  {t('common.cancel')}
                </button>
                {!editingPrompt?.isSystem && (
                  <button
                    type="submit"
                    disabled={saving}
                    className="btn-primary"
                  >
                    {saving ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        {t('common.saving')}
                      </>
                    ) : (
                      t('common.save')
                    )}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 查看模态框 */}
      {showViewModal && viewingPrompt && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg p-6 w-full max-w-3xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">{getTemplateDisplayName(viewingPrompt, t)}</h3>
                <p className="text-sm text-gray-500">{getTemplateDisplayDescription(viewingPrompt, t)}</p>
              </div>
              <button
                type="button"
                onClick={() => setShowViewModal(false)}
                className="p-1 text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            <div className="bg-gray-50 rounded-lg p-4 overflow-x-auto">
              <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono">
                {viewingPrompt.template}
              </pre>
            </div>
            
            <div className="flex justify-end gap-3 mt-4">
              <button
                type="button"
                onClick={() => setShowViewModal(false)}
                className="btn-secondary"
              >
                {t('common.close')}
              </button>
              {viewingPrompt.isSystem && (
                <button
                  type="button"
                  onClick={() => {
                    setShowViewModal(false);
                    handleCopy(viewingPrompt);
                  }}
                  className="btn-primary"
                >
                  <Copy className="mr-2 h-4 w-4" />
                  {t('promptConfig.copyAsUser')}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
