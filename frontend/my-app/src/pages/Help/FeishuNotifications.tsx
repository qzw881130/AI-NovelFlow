import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight, BellRing, Clock3, ExternalLink } from 'lucide-react';
import { CodeBlock, Note, StepCard, recommendedEvents } from './components';

const examplePayload = '{"shot_index":4,"clip_index":2,"status":"completed"}';
const exampleSimulation = `✅ NovelFlow｜Shot 4 · C2 视频生成完成

🧪 开发模拟事件`;

export default function FeishuNotificationsHelp() {
  return <main className="min-h-screen bg-gray-50 px-4 py-8 sm:px-6 sm:py-12">
    <div className="mx-auto max-w-3xl">
      <Link to="/settings#notifications" className="mb-6 inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:underline"><ArrowLeft className="h-4 w-4" />返回消息通知设置</Link>

      <header className="rounded-xl border border-blue-100 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700"><BellRing className="h-3.5 w-3.5" />NovelFlow 使用帮助</div>
        <h1 className="text-2xl font-bold text-gray-900 sm:text-3xl">飞书通知配置教程</h1>
        <p className="mt-3 text-sm leading-7 text-gray-600 sm:text-base">通过飞书群聊中的自定义机器人，将 NovelFlow 的任务完成、失败及其他事件推送到飞书。</p>
        <p className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-gray-700"><Clock3 className="h-4 w-4 text-blue-600" />预计配置时间：3～5 分钟</p>
      </header>

      <nav aria-label="配置流程" className="my-6 rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-900">配置流程</h2>
        <ol className="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm text-gray-700">
          {['创建飞书群聊', '添加自定义机器人', '获取 Webhook', '配置签名校验', '填写 NovelFlow', '发送测试消息', '选择通知事件'].map((item, index) => <li key={item} className="inline-flex items-center gap-2"><span className="rounded-full bg-blue-50 px-3 py-1 text-blue-800">{item}</span>{index < 6 && <ArrowRight aria-hidden="true" className="h-4 w-4 text-gray-400" />}</li>)}
        </ol>
      </nav>

      <div className="space-y-5">
        <StepCard number={1} title="创建通知群聊">
          <p>飞书自定义机器人向所在群聊发送消息。建议创建专门接收 NovelFlow 通知的群，例如 <strong>AI NovelFlow Notification</strong>；已有合适的群聊也可以直接使用。</p>
          <ol className="list-decimal space-y-1 pl-5"><li>打开飞书客户端并登录。</li><li>创建群聊，为群聊设置名称。</li><li>进入要接收通知的群聊。</li></ol>
          <a href="https://www.feishu.cn/" target="_blank" rel="noopener noreferrer" className="btn-secondary gap-2"><ExternalLink className="h-4 w-4" />打开飞书官网</a>
        </StepCard>

        <StepCard number={2} title="添加自定义机器人">
          <p>在目标群聊中，点击右上角「···」进入群设置，找到<strong>群机器人</strong>或<strong>机器人</strong>，选择<strong>添加机器人 → 自定义机器人</strong>，设置名称并确认添加。</p>
          <CodeBlock label="机器人名称示例" value="NovelFlow 通知助手" />
          <Note>不同飞书客户端版本的菜单位置可能不同。如果找不到入口，请检查群管理权限及所在组织是否允许添加自定义机器人。</Note>
        </StepCard>

        <StepCard number={3} title="复制机器人 Webhook">
          <p>创建自定义机器人后，飞书会提供专用 Webhook 地址。NovelFlow 会通过该地址向群聊发送通知。复制<strong>你自己的</strong>完整地址。</p>
          <CodeBlock label="Webhook 格式示例（不可用于配置）" value="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx" />
          <Note warning>Webhook 是发送消息的凭证。不要公开真实 Webhook，也不要提交到 Git 仓库；本教程不需要输入或保存你的真实 Webhook。</Note>
        </StepCard>

        <StepCard number={4} title="配置机器人安全设置">
          <p>飞书自定义机器人可使用自定义关键词、IP 白名单或签名校验。本教程建议使用<strong>签名校验</strong>。</p>
          <ol className="list-decimal space-y-1 pl-5"><li>打开自定义机器人的安全设置，启用「签名校验」。</li><li>复制飞书生成的签名密钥，并保存机器人配置。</li><li>在 NovelFlow 的<strong>系统配置 → 消息通知 → 飞书通知 → 签名密钥</strong>中填写该密钥。</li></ol>
          <Note>NovelFlow 的签名密钥字段可留空。如果飞书机器人启用了签名校验，必须填写对应密钥；NovelFlow 发送消息时会按飞书要求附带时间戳和签名。</Note>
          <Note warning>不要把真实签名密钥填写到本教程或其他网站。如果还启用了关键词或 IP 白名单，也需要确保消息内容或 NovelFlow 服务端出口 IP 符合相应规则。</Note>
        </StepCard>

        <StepCard number={5} title="配置 NovelFlow 飞书通知">
          <ol className="list-decimal space-y-1 pl-5"><li>打开 <strong>系统配置 → 消息通知</strong>，找到<strong>飞书通知</strong>。</li><li>勾选<strong>开启</strong>，填写<strong>自定义机器人 Webhook</strong>。</li><li>如果已在飞书启用签名校验，填写对应<strong>签名密钥</strong>。</li><li>点击<strong>保存并发送测试</strong>。</li></ol>
          <p>发送成功后，飞书群聊会收到类似消息：</p>
          <CodeBlock label="通道测试消息示例" value={'[NovelFlow 通道测试] 此消息仅验证飞书通知配置。'} />
          <Note>收到测试消息，即表示飞书通知通道已经配置成功。</Note>
        </StepCard>

        <StepCard number={6} title="验证事件通知">
          <p>通道测试成功后，可在<strong>事件通知配置</strong>中开启要测试的事件。开发环境还可展开页面底部的<strong>开发测试 · 模拟通知事件</strong>，选择 <strong>Clip 生成完成</strong>（<code>clip.generation.completed</code>），填写 JSON Payload，再点击<strong>发送模拟事件</strong>。</p>
          <CodeBlock label="模拟事件 Payload 示例" value={examplePayload} />
          <p>若事件订阅和飞书通道均已开启，群聊会收到类似消息：</p>
          <CodeBlock label="模拟事件消息示例" value={exampleSimulation} />
          <Note warning>这是模拟事件示例，不代表真实视频生成任务已经完成。模拟入口仅在允许的开发环境中可用，也不会改变任务或 Clip 状态。</Note>
        </StepCard>

        <StepCard number={7} title="选择需要接收的通知">
          <p>在<strong>系统配置 → 消息通知 → 事件通知配置</strong>中按需订阅事件。建议优先考虑：</p>
          <ul className="grid list-disc gap-x-5 pl-5 sm:grid-cols-2">{recommendedEvents.map(event => <li key={event}>{event}</li>)}</ul>
          <Note>事件订阅只影响消息推送，不会改变任务状态，也不会启动、取消任务或影响 ComfyUI 视频生成。</Note>
        </StepCard>
      </div>

      <section className="mt-8 rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="feishu-faq">
        <h2 id="feishu-faq" className="text-lg font-semibold text-gray-900">常见问题</h2>
        <div className="mt-4 divide-y divide-gray-200 text-sm text-gray-700">
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">点击“保存并发送测试”，但飞书没有收到消息</summary><p className="mt-2 leading-6">检查飞书通知是否开启、Webhook 是否正确、自定义机器人及群聊是否有效、NovelFlow 后端能否访问飞书 API，以及机器人安全验证是否通过。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">Webhook 无效</summary><p className="mt-2 leading-6">重新打开飞书自定义机器人配置，复制完整 Webhook，并确认没有多余空格。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">签名校验失败</summary><p className="mt-2 leading-6">确认飞书是否启用签名校验；如果已启用，检查 NovelFlow 中的密钥是否完整、是否仍是飞书当前使用的密钥。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">飞书提示关键词不匹配</summary><p className="mt-2 leading-6">机器人启用了自定义关键词，但 NovelFlow 消息没有匹配。检查安全设置，使关键词规则与实际消息内容匹配。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">飞书提示 IP 不在白名单</summary><p className="mt-2 leading-6">检查 NovelFlow 服务端的实际出口 IP，并按飞书安全要求调整白名单。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">通道测试成功，但任务完成后没有通知</summary><p className="mt-2 leading-6">检查对应事件是否开启订阅、飞书通道是否仍然开启、事件中心是否记录了对应事件，以及通知发送日志是否有错误。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">Telegram 和飞书能否同时开启？</summary><p className="mt-2 leading-6">可以。页面声音提醒、Telegram 通知和飞书通知是独立通道，可以同时开启。</p></details>
        </div>
      </section>

      <div className="py-8 text-center"><Link to="/settings#notifications" className="btn-primary gap-2"><ArrowLeft className="h-4 w-4" />返回消息通知设置</Link></div>
    </div>
  </main>;
}
