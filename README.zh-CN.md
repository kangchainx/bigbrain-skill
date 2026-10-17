# Bigbrain

**Codex 主驾，Claude 副驾。** 一个 agent skill：日常工作由 Codex 完成，只有任务足够复杂时才请 Opus
顾问出场；之后按里程碑推进，直到验收标准真正全部满足。

[English](README.md) · 简体中文

## 为什么

强模型最值钱的是**判断**：澄清需求、选方案、拆成可验证的步骤、发现"测了但没测到点子上"的测试。
而编码过程中大部分 token 花在读文件、写代码、跑测试上。Bigbrain 把两者分开：Codex 负责执行；
任务评分超过阈值时，才通过任意 Anthropic 兼容的 Messages API 升级给顾问模型，由它规划里程碑、
审查 Codex 的真实产出并推动任务完成。简单任务完全不调用顾问。

## 工作方式

1. **评分**：根据改动文件数、需求模糊度、连续失败次数、风险标签和用户明确要求计算 0–1 分，
   与阈值（默认 `0.6`）比较。
2. **规划**：第一轮返回全局验收标准和若干里程碑。
3. **循环**：Codex 逐个完成里程碑并提交审查；顾问给出 approve / revise / reject。卡住时用
   `stuck` 交出失败信息，换一种思路。
4. **结束**：只有顾问判定 `done` **且**每条验收标准都标记为满足才会结束。随后自动复盘、保存经验，
   并生成包含 token、成本和节省估算的报告。

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
