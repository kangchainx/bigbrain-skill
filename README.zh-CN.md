# Bigbrain

**Claude 协助计划，Codex 执行并默认审查；Claude 复审由用户选择。** 一个 agent skill：日常工作由 Codex 完成，只有任务足够复杂时才请 Opus
顾问出场；之后按里程碑推进，直到验收标准真正全部满足。

[English](README.md) · 简体中文

## 为什么

强模型最值钱的是**判断**：澄清需求、选方案、拆成可验证的步骤、发现"测了但没测到点子上"的测试。
而编码过程中大部分 token 花在读文件、写代码、跑测试上。Bigbrain 把两者分开：Codex 负责执行；
任务评分超过阈值时，升级给 Claude Code CLI（也保留 Messages API 后端），由它规划里程碑、
审查 Codex 的真实产出并推动任务完成。简单任务完全不调用顾问。

## 工作方式

1. **评分**：根据改动文件数、需求模糊度、连续失败次数、风险标签和用户明确要求计算 0–1 分，
   与阈值（默认 `0.6`）比较。
2. **规划**：skill 按任务复杂度自行选择推理强度，默认中（`medium`），复杂任务用高（`high`），
   特别困难的任务用超高（`xhigh`）；最高超高，不允许 `max`。第一轮返回全局验收标准和若干里程碑。
3. **循环**：Codex 逐个完成里程碑并提交审查；顾问给出 approve / revise / reject。卡住时用
   `stuck` 交出失败信息，换一种思路。
4. **结束**：只有顾问判定 `done` **且**每条验收标准都标记为满足才会结束。随后自动复盘、保存经验，
   并生成包含 token、成本和节省估算的报告。每次任务结束都会简短告知 Claude 顾问成本（美元估算），
   包含已记录的评审、JSON 修复重试和复盘用量；用量缺失时明确说明总额未知。

推理档位通过 `--effort medium|high|xhigh` 显式传给 CLI/API，后续轮次保留所选档位。
CLI 后端使用 Claude Code 返回的费用估算；API 后端按返回用量和配置单价估算，都不等同于实际账单。

介入依据是同一目标的调试过程与验证证据，不是用户措辞：反复修改仍无进展时，Claude 尚未参与就用 `start --force`；已有会话用 `stuck`，用户纠正验收结果用 `feedback`。
即使此前已完成，也会清除旧验收结论，请 Claude 先分析原因，再由 Codex 执行修正并重新送审。
聊天中用 **Claude｜计划/审查/验收**、**Codex｜执行** 展示真实交接、结论和验证证据；
不展示内部逐步思考，不编造双方对话。

## 安装

```bash
npx skills add kangchainx/bigbrain-skill
```

或：

```bash
git clone https://github.com/kangchainx/bigbrain-skill.git && cd bigbrain-skill && ./install.sh
```

安装脚本默认只安装到 `${CODEX_HOME:-$HOME/.codex}/skills/bigbrain`，不再向
`~/.agents/skills` 安装第二份，避免 Codex 显示重复条目。指定其他目录可用 `--dir PATH`。

或一行命令：

```bash
curl -fsSL https://raw.githubusercontent.com/kangchainx/bigbrain-skill/main/install.sh \
  | BIGBRAIN_SRC=https://github.com/kangchainx/bigbrain-skill/archive/refs/heads/main.tar.gz bash
```

## 配置

推荐选择 Claude Code CLI：

```bash
claude auth login  # 已登录可跳过
python3 scripts/bigbrain_cli.py setup --claude-code
python3 scripts/check_config.py --no-call --json
```

需要支持 `--safe-mode` 的新版 Claude Code，已在 2.1.310 上验证。配置只检查登录，
真实顾问调用才验证模型权限。CLI 默认模型别名为 `opus`，用 `BIGBRAIN_CLAUDE_MODEL` 指定其他模型。
Claude 只能读取和搜索仓库；Codex 负责修改、运行测试和提交差异。每个任务绑定一个持久 Claude session；
后续用明确 ID 恢复，只发送新增证据和任务约束，不使用“最新会话”。
已捕获的结果可通过 `recover --session DIR` 本地恢复，结果未知时禁止盲目重发。
详见[会话管理与恢复](references/native-sessions.md)。已有任务固定原来的后端、模型和工作目录。
Bigbrain 不把旧 API 密钥转交给 CLI；CLI 自身的认证环境变量仍按其规则生效。
CLI 失败时不会偷偷切回 API。

旧配置未指定后端时仍使用 `api`，原 API 配置会保留；也可用 `BIGBRAIN_BACKEND=api` 显式选择。
以下表单说明仅适用于 API 后端。

安装或重装后首次启用时，先说明已有配置的服务商、模型和来源，并让用户选择复用或重新配置。
不会自动沿用旧模型；已明确选择的配置不需要每轮确认。
日常使用只显示简短进度和任务结果，不自动打开或提供审查报告。详细记录仅在明确要求时展示。

在 Codex 中让 Bigbrain 配置 API，skill 会在内置浏览器打开本机配置表单，**一次只填一项**：
HTTPS 地址 → 密码框输入 API Key → 模型选择。无需把 Key 发到聊天里。

接口返回 `claude-opus-5-5` 时首推 **Claude Opus 5.5**，其余模型放在「其他模型」中展开选择；
不会猜测或替换模型。选定后发送一次极小的真实请求，成功才保存，失败不覆盖已有配置。

```bash
python3 ~/.codex/skills/bigbrain/scripts/bigbrain_cli.py setup --web
```

打开输出的链接，填写期间保持进程运行；保存、取消或 15 分钟后进程退出。
详见[配置流程](references/config.md#configuration-in-codex)。需要终端向导时去掉 `--web`。
配置只写入 `~/.bigbrain/config.json`（权限 600，目录 700），不会修改 Codex/Claude 配置。

也可以直接设置环境变量（环境变量优先于 `config.json`）：

```bash
export BIGBRAIN_BASE_URL=https://api.anthropic.com   # 不要带 /v1
export BIGBRAIN_API_KEY=sk-...
python3 scripts/check_config.py                       # 输出 OK 后才会升级
```

其他可选变量（`BIGBRAIN_MODEL`、`BIGBRAIN_THRESHOLD`、`BIGBRAIN_MAX_ROUNDS`、价格等）见
[`references/config.md`](references/config.md)。

## 安全保证

- **绝不创建或修改 `AGENTS.md`、`CLAUDE.md` 或全局 Codex/Claude 配置**，由代码中的守卫强制执行，
  并有测试覆盖。
- **经验只保存在本地** `~/.bigbrain/experience/`；放在 skill 目录或 git 仓库内会被拒绝。
- **API Key 从不明文输出**，只显示为 `****` 加末 4 位。
- 仅依赖 Python 3 标准库，无需 pip 安装。

## 节省示例（来自一次真实运行）

> Opus 顾问花费 **$0.85**，**2 轮**，与全部使用高价模型相比估算节省 **约 58.6%**。

这只是一次运行的结果，不是基准测试；实际节省取决于任务和价格。

## 作者

**Chris Kang**（[@kangchainx](https://github.com/kangchainx)，"Chris不上班"）。
如果你基于本项目进行二次开发，请注明出处并附上
[kangchainx/bigbrain-skill](https://github.com/kangchainx/bigbrain-skill) 链接，谢谢！

[MIT](LICENSE) © 2026 Chris Kang (kangchainx)

## 可选的 Codex plugin hooks

仓库已提供 `.codex-plugin/plugin.json` 和 `hooks/hooks.json`。仓库的 `.agents/plugins/marketplace.json` 提供本地来源：
先运行 `codex plugin marketplace add /absolute/path/to/bigbrain-skill`，
再运行 `codex plugin add bigbrain@bigbrain-local`，最后在 Codex 中审阅、信任 hook。普通 `install.sh` 只安装 skill，
不会注册或自动信任 hook；使用插件时应停用独立 skill 条目，避免重复加载。

SessionStart 与 UserPromptSubmit 仅在当前聊天已启用时注入简短的协作规则，不调用模型、不查找“最新任务”、
不写状态。Codex 根据当前对话判断用户反馈，运行：

```bash
python3 scripts/bigbrain_cli.py feedback --session /path/to/task-session \
  --reason "用户的原话" --failure-file /path/to/evidence.txt
```

诊断这一轮不能直接结束任务。Codex 按新计划执行，再用 `report` 交给 Claude 验收。
反馈会保留在后续上下文中。Hook 是提醒机制，不能保证模型必然遵守；完成判定由 CLI
校验验收条件。存在 `CODEX_THREAD_ID` 时还会拒绝跨聊天使用任务。

内部费用与质量审计：`python3 scripts/audit_sessions.py <会话目录或根目录>`，离线只读。每周复盘流程见 [审计说明](references/session-audit.md)；定时执行由宿主自动化负责。

## 按聊天启用（默认关闭）

在 Codex 中，只有明确要求“本次启用 Bigbrain”才打开当前聊天的开关；
讨论插件、任务复杂或反复调试不会自动启用。说“本次关闭 Bigbrain”会关闭。
开关绑定 Codex 聊天 ID，与工作目录和 Claude 原生 session ID 无关。
同一聊天恢复/压缩后保留，新建或 fork 的聊天默认关闭，其他聊天不受影响。

```bash
python3 scripts/bigbrain_cli.py mode on
python3 scripts/bigbrain_cli.py mode off
python3 scripts/bigbrain_cli.py mode status
```

这些命令只改本地聊天开关，不调用模型。关闭时两个 hook 都不输出上下文，
实际工作流命令也会拒绝新的顾问调用。不会删除历史或中断已在运行的进程。
