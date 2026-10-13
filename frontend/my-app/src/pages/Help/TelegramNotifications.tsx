import { Link } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Clock3, ExternalLink, Send } from 'lucide-react';
import { CodeBlock, Note, StepCard, recommendedEvents } from './components';

const exampleUpdates = `{
  "ok": true,
  "result": [
    {
      "message": {
        "chat": {
          "id": 987654321,
          "type": "private"
        },
        "text": "hello"
      }
    }
  ]
}`;

export default function TelegramNotificationsHelp() {
  return <main className="min-h-screen bg-gray-50 px-4 py-8 sm:px-6 sm:py-12">
    <div className="mx-auto max-w-3xl">
      <Link to="/settings#notifications" className="mb-6 inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:underline"><ArrowLeft className="h-4 w-4" />返回消息通知设置</Link>

      <header className="rounded-xl border border-blue-100 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700"><Send className="h-3.5 w-3.5" />NovelFlow 使用帮助</div>
        <h1 className="text-2xl font-bold text-gray-900 sm:text-3xl">Telegram 通知配置教程</h1>
        <p className="mt-3 text-sm leading-7 text-gray-600 sm:text-base">按照以下步骤创建 Telegram 机器人，获取 Bot Token 和 Chat ID，即可接收 NovelFlow 的任务通知。</p>
        <p className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-gray-700"><Clock3 className="h-4 w-4 text-blue-600" />预计操作时间：3～5 分钟</p>
      </header>

      <nav aria-label="配置流程" className="my-6 rounded-xl border border-gray-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-gray-900">配置流程</h2>
        <ol className="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm text-gray-700">
          {['创建机器人', '获取 Bot Token', '获取 Chat ID', '填写 NovelFlow', '发送测试消息'].map((item, index) => <li key={item} className="inline-flex items-center gap-2"><span className="rounded-full bg-blue-50 px-3 py-1 text-blue-800">{item}</span>{index < 4 && <ArrowRight aria-hidden="true" className="h-4 w-4 text-gray-400" />}</li>)}
        </ol>
      </nav>

      <div className="space-y-5">
        <StepCard number={1} title="打开 BotFather">
          <p>BotFather 是 Telegram 官方提供的机器人管理工具。确认用户名为 <strong>@BotFather</strong>，打开后点击 <strong>Start（开始）</strong>，然后发送以下命令。</p>
          <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer" className="btn-secondary gap-2"><ExternalLink className="h-4 w-4" />打开 BotFather</a>
          <CodeBlock label="创建机器人命令" value="/newbot" />
        </StepCard>

        <StepCard number={2} title="创建机器人">
          <p>BotFather 会先要求输入机器人名称，再要求输入机器人用户名。例如：</p>
          <CodeBlock label="机器人名称示例" value="NovelFlow Notifications" />
          <CodeBlock label="机器人用户名示例" value="NovelFlow_Notify_2026_bot" />
          <Note>名称可以自由填写；用户名必须以 <code>bot</code> 结尾且唯一。如果提示已存在，请换一个用户名。</Note>
          <p>创建成功后，BotFather 会返回 Bot Token。下面仅为示例，<strong>不是真实 Token</strong>：</p>
          <CodeBlock label="Bot Token 示例（不可用于配置）" value="1234567890:AAExampleTokenxxxxxxxxxxxx" />
          <Note warning>Bot Token 相当于机器人密码。不要将真实 Token 分享给他人，也不要提交到 Git 仓库。</Note>
        </StepCard>

        <StepCard number={3} title="打开自己的机器人">
          <p>BotFather 会提供新机器人的 Telegram 地址，例如 <code className="break-all">https://t.me/NovelFlow_Notify_2026_bot</code>。打开<strong>自己的</strong>机器人，点击 <strong>Start</strong> 或发送 <code>/start</code>，再发送一条普通消息，例如 <code>hello</code>。</p>
          <div className="grid gap-3 sm:grid-cols-2"><CodeBlock label="启动命令" value="/start" /><CodeBlock label="普通消息示例" value="hello" /></div>
          <Note>必须先与机器人建立聊天，机器人才能向当前用户发送私聊通知。</Note>
        </StepCard>

        <StepCard number={4} title="获取 Chat ID">
          <p>Chat ID 是 Telegram 用于确定消息接收目标的数字标识。复制刚才获得的 Bot Token，在<strong>浏览器地址栏</strong>输入下方地址，将 <code>&lt;BOT_TOKEN&gt;</code> 替换成真实 Token 后打开。</p>
          <CodeBlock label="getUpdates 地址模板" value="https://api.telegram.org/bot<BOT_TOKEN>/getUpdates" />
          <p>在返回的 JSON 中找到 <code>message.chat.id</code>：</p>
          <CodeBlock label="getUpdates 响应示例" value={exampleUpdates} />
          <p>示例中的 <code>987654321</code> 是 Chat ID。请复制<strong>你自己的</strong> Chat ID。</p>
          <Note warning>包含真实 Bot Token 的完整 API 地址不要分享给他人。本教程不需要输入、读取或保存你的 Token。</Note>
        </StepCard>

        <StepCard number={5} title="填写 NovelFlow 通知配置">
          <ol className="list-decimal space-y-1 pl-5">
            <li>返回 NovelFlow，打开 <strong>系统配置 → 消息通知</strong>。</li>
            <li>找到 <strong>Telegram 通知</strong>，勾选 <strong>开启</strong>。</li>
            <li>填写自己的 <strong>Bot Token</strong> 和 <strong>Chat ID</strong>。</li>
            <li>点击 <strong>保存并发送测试</strong>。</li>
          </ol>
          <p>发送成功后，Telegram 会收到类似消息：</p>
          <CodeBlock label="测试消息示例" value={'[NovelFlow 通道测试]\n此消息仅验证 Telegram 通知配置。'} />
          <Note>收到测试消息，即表示 Telegram 通知通道已经配置成功。</Note>
        </StepCard>

        <StepCard number={6} title="选择需要接收的事件">
          <p>通道配置成功后，可以在<strong>事件通知配置</strong>中选择需要发送通知的事件。建议按需开启：</p>
          <ul className="grid list-disc gap-x-5 pl-5 sm:grid-cols-2">{recommendedEvents.map(event => <li key={event}>{event}</li>)}</ul>
          <Note>事件通知配置只控制消息发送。关闭某个事件的订阅，不会影响对应任务的正常执行。</Note>
        </StepCard>
      </div>

      <section className="mt-8 rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="telegram-faq">
        <h2 id="telegram-faq" className="text-lg font-semibold text-gray-900">常见问题</h2>
        <div className="mt-4 divide-y divide-gray-200 text-sm text-gray-700">
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">getUpdates 返回 "result": []</summary><p className="mt-2 leading-6">机器人可能尚未收到消息，或更新已被其他消费者获取。先打开机器人，发送 <code>/start</code> 和 <code>hello</code>，再重新查询。如果配置了 Webhook，getUpdates 可能无法正常使用。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">401 Unauthorized</summary><p className="mt-2 leading-6">Bot Token 无效。检查 Token 是否完整，以及是否复制了多余空格。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">400 Bad Request: chat not found</summary><p className="mt-2 leading-6">Chat ID 可能不正确，或者机器人无法访问该聊天。确认 Chat ID，并确认已打开自己的机器人、发送 <code>/start</code>。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">403 Forbidden</summary><p className="mt-2 leading-6">机器人可能被屏蔽，或无权向目标聊天发送消息。取消屏蔽，重新打开机器人并发送 <code>/start</code>。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">点击“保存并发送测试”，但没有收到消息</summary><p className="mt-2 leading-6">检查 Telegram 通知是否开启、Bot Token 和 Chat ID 是否正确、是否已启动机器人，以及 NovelFlow 后端能否访问 Telegram API（包括代理或网络连接问题）。</p></details>
          <details className="py-3"><summary className="cursor-pointer font-medium text-gray-900">Telegram 测试成功，但任务完成后没有通知</summary><p className="mt-2 leading-6">检查对应事件是否开启订阅、Telegram 通道是否仍然开启、事件中心是否记录了对应事件，以及通知发送是否出现错误。</p></details>
        </div>
      </section>

      <div className="py-8 text-center"><Link to="/settings#notifications" className="btn-primary gap-2"><ArrowLeft className="h-4 w-4" />返回消息通知设置</Link></div>
    </div>
  </main>;
}
