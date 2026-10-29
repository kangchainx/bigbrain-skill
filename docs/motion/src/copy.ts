export type Lang = 'en' | 'zh';
const en = {
  note: 'Illustrative script, not a real transcript.',
  open: ['Two agents.', 'One task.'],
  you: 'You', codexRole: 'builds, tests, reviews first', claudeRole: 'plans and diagnoses',
  prompt: 'Use Bigbrain for this chat.', on: 'Bigbrain is on for this chat',
  task: 'Stop duplicate orders',
  ask: 'The spec is fuzzy. I want a plan before I touch checkout.',
  plan: 'My plan: one idempotency key per order.',
  steps: ['Create one key per checkout', 'The server rejects a repeated key', 'Done when a double click makes one order'],
  stuck: 'Built it. My test double-clicks… still two orders.',
  orders: 'orders', orderTag: 'order',
  diag: 'The key is made too late. Create it when the form opens.',
  marks: ['form opens', 'submit'], key: 'key',
  fix: 'Fixed. The test passes and my first review is clean.',
  offer: 'A second review from Claude? Only if you ask.',
  one: '1 order',
  end: 'Codex builds. Claude helps you think it through.',
};
export type Copy = typeof en;
const zh: Copy = {
  note: '示意脚本，并非真实对话记录。',
  open: ['两个 Agent。', '一个任务。'],
  you: '你', codexRole: '实现、测试、首轮审查', claudeRole: '规划与诊断',
  prompt: '这个聊天启用 Bigbrain。', on: '本聊天已开启 Bigbrain',
  task: '杜绝重复下单',
  ask: '需求有点模糊。动结账代码前，我想先要一份计划。',
  plan: '我的计划：每笔订单一个幂等 key。',
  steps: ['每次结账生成一个 key', '服务端拒绝重复的 key', '验收：连点两下只生成一笔订单'],
  stuck: '做好了。但测试连点两下，还是两笔订单。',
  orders: '笔订单', orderTag: '订单',
  diag: 'key 生成得太晚了。表单一打开就生成。',
  marks: ['表单打开', '提交'], key: 'key',
  fix: '修好了。测试通过，我的首轮审查也没问题。',
  offer: '要 Claude 再审一遍吗？你开口才做。',
  one: '1 笔订单',
  end: 'Codex 负责落地，Claude 帮你想清楚。',
};
export const COPY: Record<Lang, Copy> = { en, zh };
