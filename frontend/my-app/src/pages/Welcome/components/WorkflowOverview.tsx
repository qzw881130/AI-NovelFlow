import { CheckCircle, ChevronRight, Book, Users, FileText, Image as ImageIcon, Video, Sparkles, Mic, Package } from 'lucide-react';
import { useTranslation } from '../../../stores/i18nStore';

const workflowSteps = [
  { icon: Book, color: 'from-sky-500 to-blue-500' },           // 导入小说
  { icon: Sparkles, color: 'from-violet-500 to-purple-500' },  // AI解析角色
  { icon: Sparkles, color: 'from-fuchsia-500 to-pink-500' },   // AI解析场景
  { icon: Sparkles, color: 'from-amber-500 to-yellow-500' },   // AI解析道具
  { icon: Users, color: 'from-orange-500 to-amber-500' },      // 生成角色图
  { icon: ImageIcon, color: 'from-teal-500 to-cyan-500' },     // 生成场景图
  { icon: Package, color: 'from-rose-500 to-pink-500' },       // 生成道具图
  { icon: FileText, color: 'from-blue-500 to-cyan-500' },      // 编辑章节
  { icon: Sparkles, color: 'from-purple-500 to-pink-500' },    // AI拆分分镜
  { icon: ImageIcon, color: 'from-emerald-500 to-teal-500' },  // 生成分镜图
  { icon: Mic, color: 'from-indigo-500 to-violet-500' },       // 生成音频
  { icon: Video, color: 'from-red-500 to-orange-500' },        // 生成视频
  { icon: CheckCircle, color: 'from-green-500 to-emerald-500' }, // 成功
];

export function WorkflowOverview() {
  const { t } = useTranslation();
  const titles = [
    t('welcome.workflow.importNovel'),
    t('welcome.workflow.parseCharacters'),
    t('welcome.workflow.parseScenes'),
    t('welcome.workflow.parseProps'),
    t('welcome.workflow.generateCharacters'),
    t('welcome.workflow.generateScenes'),
    t('welcome.workflow.generateProps'),
    t('welcome.workflow.editChapter'),
    t('welcome.workflow.splitShots'),
    t('welcome.workflow.generateShotImages'),
    t('welcome.workflow.generateAudio'),
    t('welcome.workflow.generateVideo'),
    t('common.success'),
  ];

  return (
    <ol className="grid grid-cols-2 gap-x-3 gap-y-6 sm:grid-cols-3 md:grid-cols-4 lg:flex lg:items-center lg:justify-between lg:gap-0 lg:overflow-x-auto lg:pb-2">
      {workflowSteps.map((step, index) => (
        <li key={index} className="flex min-w-0 items-center lg:shrink-0">
          <div className="flex min-w-0 w-full flex-col items-center lg:w-auto">
            <div className={`w-14 h-14 rounded-xl flex items-center justify-center mb-2 bg-gradient-to-br ${step.color} text-white shadow-md`}>
              <step.icon aria-hidden="true" className="h-7 w-7" />
            </div>
            <span className="max-w-full break-words text-xs font-medium text-gray-700 text-center lg:whitespace-nowrap">
              <span className="text-gray-500 lg:hidden">{index + 1}. </span>{titles[index]}
            </span>
          </div>
          {index < workflowSteps.length - 1 && <div aria-hidden="true" className="hidden lg:flex items-center flex-1 justify-center mx-1 mb-6"><ChevronRight className="h-5 w-5 text-gray-300" /></div>}
        </li>
      ))}
    </ol>
  );
}
