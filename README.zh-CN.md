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

或一行命令：

```bash
curl -fsSL https://raw.githubusercontent.com/kangchainx/bigbrain-skill/main/install.sh \
  | BIGBRAIN_SRC=https://github.com/kangchainx/bigbrain-skill/archive/refs/heads/main.tar.gz bash
```

## 配置

最简单的方式是运行配置向导。在终端中执行 `install.sh` 时会询问 `Configure now? [Y/n]`；
之后也可以随时运行：

```bash
python3 ~/.codex/skills/bigbrain/scripts/bigbrain_cli.py setup    # 或 scripts/setup.py
```

向导会先（只读地）查找已有配置：`BIGBRAIN_*` 与 `ANTHROPIC_*` 环境变量、`~/.bigbrain/config.json`、
`~/.claude/settings.json` 中的 `env` 段，找到后显示脱敏摘要并询问 `Use this? [Y/n]`；否则依次询问
服务商（Anthropic 官方、OpenRouter 或自定义 URL）、API Key（输入不回显）和模型。随后发送一次极小的
真实请求进行验证，失败时说明原因（Key 被拒、URL 错误、模型不存在、网络问题），并可选择重试 / 修改 /
仍然保存 / 放弃。向导只写入 `~/.bigbrain/config.json`（权限 600，目录 700）。未配置时运行
`check_config.py` 或 CLI，会打印上述完整命令。

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
