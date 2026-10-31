import type { GridGenerationCheck } from '../../../api/config';

const stages: Array<{ id: GridGenerationCheck['stage']; title: string }> = [
  { id: 'before_queue', title: '批量启动前' },
  { id: 'planning', title: '章回解析与宫格规划' },
  { id: 'image', title: '宫格生图与 AI 初审' },
  { id: 'video', title: 'Clip 规划与 H3 生视频' },
  { id: 'assembly', title: '视频文件与合并' },
];

export default function GridGenerationQualityConfig({ checks, policy, onPolicyChange }: {
  checks: GridGenerationCheck[];
  policy: Record<string, boolean>;
  onPolicyChange: (id: string, enabled: boolean) => void;
}) {
  return <div className="rounded-lg border border-gray-200 p-4 text-sm">
    <h4 className="font-medium text-gray-800">宫格批量预检</h4>
    <p className="mt-1 text-gray-500">适用于宫格模式的批量生图、生视频；画外声子格和单独提交“批量 AI 审图”始终会审图。新任务会保存提交时的设置，运行中修改不会改变已排队任务。</p>
    <p className="mt-1 text-gray-500">有图片且状态不是 FAIL 的子格可以继续规划 Clip，WARNING 和 PENDING 保留原状态。固定检查保护台词、画外声、图片引用和视频文件。</p>
    <p className="mt-1 text-gray-500">此处展示检查规则与开关；每次审核的结果和抽帧请到对应章回的“本章生成任务 → 批量审核记录”查看。</p>
    <div className="mt-4 space-y-4">
      {stages.map(stage => {
        const items = checks.filter(check => check.stage === stage.id);
        if (!items.length) return null;
        return <div key={stage.id}>
          <h5 className="border-b border-gray-100 pb-2 font-medium text-gray-800">{stage.title}</h5>
          <div className="grid gap-x-5 sm:grid-cols-2">
            {items.map(check => <label key={check.id} className="flex items-start gap-2 border-b border-gray-50 py-2.5">
              <input type="checkbox" className="mt-0.5" disabled={!check.configurable}
                checked={check.configurable ? (policy[check.id] ?? check.enabled) : true}
                onChange={event => onPolicyChange(check.id, event.target.checked)} />
              <span className="min-w-0">
                <span className="font-medium text-gray-800">{check.label}</span>
                <span className="ml-2 text-xs text-gray-500">{check.configurable
                  ? ((policy[check.id] ?? check.enabled) ? '开启' : '关闭') : '始终检查'}</span>
                <span className="block text-xs leading-5 text-gray-500">{check.description}</span>
              </span>
            </label>)}
          </div>
        </div>;
      })}
    </div>
  </div>;
}
