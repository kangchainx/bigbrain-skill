<div align="center">
  <h1>Bigbrain</h1>
  <p><a href="README.md">English</a> · <strong>简体中文</strong> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a> · <a href="README.pt-BR.md">Português (Brasil)</a></p>
  <p>
    <a href="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-64748b.svg"></a>
    <a href="https://www.python.org/"><img alt="Python standard library" src="https://img.shields.io/badge/Python-stdlib_only-3776ab.svg"></a>
  </p>
</div>

在 Codex 聊天中请 Claude 参与规划和诊断。Codex 编写代码、运行检查并审查结果；需要第二个意见时，由你决定邀请。

![Codex 负责落地，Claude 帮你想清楚。](docs/assets/hero.zh-CN.png)

**每个聊天默认关闭，由你主动开启。** 开启后，难题可以触发 Claude 规划或诊断。**Claude 代码二次审查是可选项，需要明确请求。**

## 什么时候用 Bigbrain

| 你遇到的情况 | Bigbrain 怎么帮忙 |
|---|---|
| 改动代价高，想先把方案想清楚 | 把模糊需求拆成里程碑，每一步都有可检查的验收标准。 |
| 反复尝试，仍然卡在同一个问题 | 把失败尝试和证据交给 Claude，诊断下一步该怎么走。 |
| 希望上下文能延续，也想掌握调用情况 | 每个任务绑定 Claude 会话，保留本地经验，并显示顾问费用估算。 |

## 开始使用

需要 Codex、Python 3，以及已登录且支持 `--safe-mode` 的 Claude Code CLI（已测试版本：2.1.310）。Bigbrain 本身只使用 Python 标准库。以下命令都在克隆的仓库中执行。

```bash
git clone https://github.com/kangchainx/bigbrain-skill.git
cd bigbrain-skill
./install.sh --no-setup
python3 scripts/bigbrain_cli.py setup --claude-code
python3 scripts/check_config.py --no-call --json
```

如果 Claude Code 尚未登录，先运行 `claude auth login`。配置会选择后端；无调用检查只验证登录，不验证模型权限。首次实际顾问调用才会验证生成能力。

然后在 Codex 聊天中说：

> 这个聊天启用 Bigbrain。先帮我规划这次改动，再开始实现。

想停止时，说 **“关闭这个聊天的 Bigbrain。”** 同一聊天恢复后保留开关；新建或分叉的聊天默认关闭。安装 skill 不等于启用。

<details>
<summary>其他安装方式</summary>

使用 skills CLI 时，选择 Codex 作为安装目标。之后请 Codex 用 Claude Code 配置 Bigbrain；它应使用实际安装的 skill 路径，不假设存在仓库目录。

```bash
npx skills add kangchainx/bigbrain-skill
```

在仓库中运行 `./install.sh --copy` 可复制安装，默认使用符号链接；`--claude` 同时安装给 Claude Code；`--dir PATH` 指定目标目录。默认位置是 `${CODEX_HOME:-$HOME/.codex}/skills/bigbrain`。使用符号链接时，请保留仓库目录。

</details>

## 一个任务，清晰分工

![一眼看懂协作分工 · 流程示意](docs/assets/flow.zh-CN.png)

<p align="center"><a href="docs/assets/demo.zh-CN.mp4"><img src="docs/assets/demo.zh-CN.gif" alt="播放 24 秒双 Agent 对话（带音乐 MP4）。脚本化协作示意。" width="960"></a></p>

[播放 24 秒双 Agent 对话（带音乐 MP4）。脚本化协作示意。](docs/assets/demo.zh-CN.mp4)

*一眼看懂协作分工 · 流程示意*

1. **你主动开启。** 任务复杂本身不会激活关闭状态的 Bigbrain。
2. **需要时请 Claude 出主意。** 在已开启的聊天中，规划任务评分超过 `0.6` 会升级给顾问；明确请求顾问也可以触发升级。简单任务仍由 Codex 完成。
3. **Codex 实现并首审。** 编辑文件、运行检查和首轮代码审查都由 Codex 执行。Claude 二次审查需要你的明确请求。
4. **让证据延续。** 用户反馈可以重新打开任务，先诊断，再提供新的验证证据。顾问运行会记录 token 和费用估算。

## 选择顾问后端

|  | Claude Code · 推荐 | Messages API · 可选 |
|---|---|---|
| 认证 | Claude Code 自己的登录状态 | 服务商 API 密钥 |
| 模型 | `BIGBRAIN_CLAUDE_MODEL`（默认 `opus`） | `BIGBRAIN_MODEL`（默认 `claude-opus-5-5`） |
| 上下文 | 每个任务持久绑定原生会话；仅 Read/Glob/Grep | 由 Codex 提供上下文 |
| 费用 | Claude Code 返回的估算 | 返回用量 × 配置的 token 单价 |

已有任务保留创建时的后端和模型。未配置后端的旧配置为兼容起见继续使用 `api`。后端之间**不会静默切换**；模型可用性取决于你的账号或接口。

<details>
<summary>配置 Messages API 服务商</summary>

在仓库中运行下面的命令打开本地配置表单。在表单中填写 HTTPS 接口、API 密钥并选择模型，不要把密钥发到聊天里。表单读取服务商模型列表，并在真实生成检查通过后才保存。

```bash
python3 scripts/bigbrain_cli.py setup --web
```

流式响应和临时错误重试只适用于 API 后端。服务商还必须支持所选模型及请求的 thinking/effort 参数；仅兼容 Anthropic JSON 格式不代表一定可用。`BIGBRAIN_BASE_URL` 不带末尾 `/v1`。环境变量优先于保存的配置。详见[配置参考](references/config.md)。

</details>

## 由你掌控的会话

- **职责分开。** Claude Code 顾问只能使用 Read/Glob/Grep，以 `--safe-mode`、严格的空 MCP 配置及禁用斜杠命令的方式启动；编辑和测试由 Codex 执行。
- **状态保存在本地。** 经验位于 `~/.bigbrain/experience/`，任务记录位于工作区的 `.bigbrain/`。相关上下文和附件图片会发给所选顾问；本地存储不等于离线推理。
- **不改全局指令。** Bigbrain 不修改 `AGENTS.md`、`CLAUDE.md` 或 Codex/Claude 全局配置，配置向导只写 Bigbrain 自己的配置。
- **用量可见。** 顾问费用是估算，不是服务商账单，也不能证明订阅实际扣费；缺失用量会明确标注。节省比例还包含对执行器 token 的估算，不是性能或成本基准。

## 手动使用

通常由 Codex 替你执行流程。以下命令在仓库中运行，只查看聊天开关或已有任务，不调用顾问：

```bash
python3 scripts/bigbrain_cli.py mode status
python3 scripts/bigbrain_cli.py status --session .bigbrain/my-task
```

<details>
<summary>进阶：顾问里程碑循环</summary>

明确启用后，一个任务始终使用同一个会话目录。以下命令会调用顾问；`m1.md` 应包含真实执行结果和验证证据。

```bash
python3 scripts/bigbrain_cli.py mode on
python3 scripts/bigbrain_cli.py lessons list --limit 10
python3 scripts/bigbrain_cli.py start --task "..." --user-request --effort medium --session .bigbrain/my-task
python3 scripts/bigbrain_cli.py report --session .bigbrain/my-task --result-file m1.md
python3 scripts/bigbrain_cli.py feedback --session .bigbrain/my-task --reason "..."
```

顾问里程碑循环只有在所有验收标准均标记满足后，才接受 `done`。这**不意味着** Codex 独立完成的代码审查必须经过 Claude 批准。默认最多 8 轮；推理强度默认 `medium`，也支持 `high` 和 `xhigh`。循环终止时通常还会调用一次顾问复盘。退出码：`0` 继续或 `DONE`；`10` 阻塞；`11` 轮次耗尽；`12` 修复后 JSON 仍无效；`2`–`6` 配置或服务商错误。

</details>

<details>
<summary>可选：Codex 插件 hooks</summary>

仓库包含本地插件市场。在仓库中运行以下命令注册，再到 Codex 审阅并信任 hooks。使用插件时应禁用独立 skill 入口，避免重复发现；普通 skill 安装器不会注册或信任 hooks。

```bash
codex plugin marketplace add /absolute/path/to/bigbrain-skill
codex plugin add bigbrain@bigbrain-local
```

SessionStart 和 UserPromptSubmit 只在已开启的聊天中提醒协作规则。Hooks 不调用模型，也不能强制模型遵循所有对话规则。详见[协作约定](references/collaboration.md)与[会话恢复](references/native-sessions.md)。

</details>

## 常见问题

**每个任务都会调用 Claude 吗？**

不会。关闭时不发起新的工作流顾问调用；开启后简单任务仍可由 Codex 独立完成。关闭不会中断已经运行中的请求。

**可以不调用模型，先试一下吗？**

在仓库中运行 `bash examples/minimal/run.sh`。它使用预设回复，仅演示流程，不是真实审查。

**怎样检查安装包的代码？**

运行 `bash tests/run_tests.sh`。测试使用临时目录和本地模拟服务，不调用真实服务商。

**怎样卸载？**

在仓库中运行 `./install.sh --uninstall`，经验会保留。只有同时希望删除用户级 Bigbrain 存储时，才加上 `--purge`。

## 进一步了解

[配置与后端](references/config.md) · [升级评分规则](references/triggers.md) · [会话与恢复](references/native-sessions.md) · [本地经验](references/experience.md) · [离线费用审计](references/session-audit.md) · [参与贡献](CONTRIBUTING.md)

---

由 **Chris Kang**（[@kangchainx](https://github.com/kangchainx)）创建。

[MIT](LICENSE) · © 2026 Chris Kang。如果你基于 Bigbrain 构建项目，欢迎链接回本仓库。
