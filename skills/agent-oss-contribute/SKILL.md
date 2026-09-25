---
name: agent-oss-contribute
description: >-
  End-to-end open-source contribution for Agent/LLM projects: discover GitHub
  repos (stars, downloads/usage, recent commits, issue close ratio, PR merge
  speed, release cadence) and rewrite each project description in the user's
  language (what it does, problem, scenarios), analyze an Agent/LLM repo, write
  a scoped PR plan, implement it, open a GitHub PR, then write a PR summary
  from saved artifacts.
  Use when the user wants 搜索可贡献项目, 找开源项目, Agent 开源, MCP/LangChain 仓库,
  star 1000, GitHub 搜仓库; pastes a GitHub URL for 开源贡献分析, PR 方向,
  good first issue, Agent 架构缺陷; asks for 技术方案, 按方案落地, 提交 PR with
  feat/fix/refactor/test/docs; or 产出 PR 总结, summary.md, 已提 PR 复盘,
  pastes a pull request URL / 之前提过的项目.
  Trigger even without the word skill. Do not use for private product feature work
  or non-Agent general OSS drive-bys.
compatibility: Requires Python 3, network access, and GitHub CLI (gh) logged in or GH_TOKEN/GITHUB_TOKEN.
---

# Agent 开源贡献全流程

面向 **Agent / LLM / MCP** 类开源仓库的一条流水线，六个阶段。用户没点名时，从当前对话能判断走到哪一步，就只做那一步；不要搜完项目自动改代码，也不要没方案就提 PR，也不要提完 PR 自动写总结。

回复语言跟随用户；用户未指定时默认中文。技术专有名词保留英文。只输出当前阶段规定的结构。

## 阶段路由

| 用户在做什么 | 进入 | 先读 |
|---|---|---|
| 搜可贡献项目 / 找开源仓库 / 没给 `REPO_URL` 但想贡献 | 阶段 0 发现 | [references/discover.md](references/discover.md) |
| 给了 `REPO_URL` / 找 PR 方向 / Issue 筛选 / 架构缺陷 | 阶段 1 分析 | [references/analysis.md](references/analysis.md) 和 [references/architecture-dimensions.md](references/architecture-dimensions.md) |
| 从 Top 3 里选定一条 / 要技术方案 / 问题边界 / 实现步骤 | 阶段 2 方案 | [references/design.md](references/design.md) |
| 粘贴了选定方案并要落地 / 技术方案实现 / 先定义接口 | 阶段 3 落地 | [references/implementation.md](references/implementation.md) |
| 提交 PR / 开 PR / 按 feat/fix 发 PR | 阶段 4 提 PR | [references/pull-request.md](references/pull-request.md) |
| 产出 PR 总结 / 已提 PR 复盘 / 给了 PR 地址或之前提过的项目 | 阶段 5 总结 | [references/summary.md](references/summary.md) |

一次只跑一个阶段，跑完停下来等用户。用户明确说「一次做完」时：无 `REPO_URL` 先阶段 0 并停下让用户选仓库；有 `REPO_URL` 才从阶段 1 往后走，且阶段 2 的方案仍要先给用户看过。阶段 5 不随「一次做完」自动跑，除非用户同时要求总结。

缺关键输入就问，不要用虚构仓库或虚构方案硬跑。

## 共用输入

| 字段 | 说明 |
|------|------|
| `REPO_URL` | GitHub 仓库 URL；阶段 0 不需要 |
| `PR_URL` | GitHub PR URL（`.../pull/N`）；阶段 5 优先用它定位项目 |
| `LOCAL_PATH` | 本地仓库根；缺省用当前任务工作目录（本仓库 evals 未指定时 clone 到仓库根 `test/`） |
| `ARTIFACT_ROOT` | 中间产物根目录；缺省为 `<当前任务工作目录>/artifacts`（本仓库 evals 时即 `<仓库根>/test/artifacts`） |
| 技术栈 | 未给则用：Python、TypeScript、React、MCP 集成、LangChain.js |
| 目标周期 | 未给则用：2 周 |

**当前任务工作目录**：本阶段开始时进程的工作目录（cwd / workspace root）。不绑定任何特定编辑器或 Agent 产品；用户显式给出 `ARTIFACT_ROOT` 时以用户为准。

本仓库跑 skill 测试 / `evals/` 时：工作目录、fixture、以及未给出 `LOCAL_PATH` 时的 clone 目标，均为技能集合仓库根下的 `test/`（已 gitignore，不要提交其中内容）。日常使用仍以用户 cwd / `LOCAL_PATH` / `ARTIFACT_ROOT` 为准。

阶段 1–4 工作目录必须是目标仓库。阶段 3、4 禁止改别的 repo。阶段 5 不要求切到目标仓库，且禁止改任何仓库代码。

## 中间产物落盘

每个阶段在回复用户的同时，必须把**该阶段完整输出**写入 `ARTIFACT_ROOT`（默认 `<当前任务工作目录>/artifacts`；本仓库 evals 时为 `<仓库根>/test/artifacts`）。聊天输出与落盘内容一致；先写文件再结束本阶段。路径一律相对 `ARTIFACT_ROOT` 书写与落盘；回复用户时可附绝对路径方便打开。

| 阶段 | 相对 `ARTIFACT_ROOT` 的路径 | 规则 |
|------|------|------|
| 0 发现 | `search/<YYYYMMDD-HHMMSS>.md` | 每次搜索新建一个文件，文件名用执行时刻本地时间 |
| 1 分析 | `project/<owner>-<repo>/analysis.md` | 项目目录不存在则创建；已有则覆盖 |
| 2 方案 | `project/<owner>-<repo>/design.md` | 同上 |
| 3 落地 | `project/<owner>-<repo>/implementation.md` | 同上（改动摘要 + 提交计划 + 验证结果） |
| 4 提 PR | `project/<owner>-<repo>/pull-request.md` | 同上（标题、正文草稿、最终 PR URL） |
| 5 总结 | `summary/<owner>-<repo>/<pr名>.md` | 项目目录不存在则创建；同一 PR 再跑则覆盖 |

- `<owner>-<repo>` 取自 `REPO_URL`（如 `https://github.com/langchain-ai/langchainjs` → `langchain-ai-langchainjs`）。
- `<pr名>` 规则见 [references/summary.md](references/summary.md)（优先 `{number}-{slug}`）。
- 阶段 1–4 的产物只写在对应 `project/` 目录下，不要写到别的项目文件夹。
- 阶段 0 只写 `search/`，不要在 `project/` 下建目录。
- 阶段 5 只写 `summary/`，不要覆盖 `project/` 里的中间产物。
- 禁止写死某台机器的绝对路径（如 `/Users/...`）；禁止写死某产品专用目录。
- 落盘失败（权限/路径不存在）时：先建缺的目录再写；仍失败则把错误告诉用户，不要假装已保存。

## 阶段门闩

- **0 → 1**：用户从发现结果里选了一个仓库（或自己给了 `REPO_URL`）。
- **1 → 2**：用户点了分析 Top 3 中的一条，或自己给出等价方向。
- **2 → 3**：方案里的选定方案、问题边界、成功标准、文件清单、实现步骤已经齐，且用户确认可以落地。
- **3 → 4**：代码已按方案落地并验证过；用户明确说提交 / 开 PR。未要求时不要 `git commit` / `push` / `gh pr create`。
- **4 → 5**：用户明确要总结，或给出已提 PR 的项目 / `PR_URL`。阶段 4 结束后不要自动写 summary。阶段 5 可从新会话直接进入，不要求本会话跑过 0–4。

## 硬约束

- 阶段 0 必须跑 `scripts/discover_repos.py`，禁止用记忆编造仓库榜；必须传 `--artifact-root` 与 `--user-language`；用户口头过滤条件必须译成脚本参数。项目描述必须用用户语言，覆盖做什么 / 解决的问题 / 适用场景；下载量、使用分、排名以脚本为准，禁止改排名或编造用量。
- 每阶段结束必须落盘（见「中间产物落盘」），禁止只回复不写文件。
- 先读该仓库的真实文件和 Issue，再用训练记忆。路径用仓库内相对路径。
- 贡献范围必须能在约 2 周内完成，禁止「重写编排层」这类方向。
- 阶段 3、4：最小侵入、向后兼容、风格与仓库一致；新第三方依赖必须先问用户。阶段 5 不改代码。
- 阶段 4 的 commit type 只用：`feat` / `fix` / `refactor` / `test` / `docs`。
- 阶段 4 的 PR body：**禁止**自造 checklist / `Test plan`，**禁止**追加任何 AI/编辑器署名 footer。
- 阶段 5：star 数、PR 正文、中间产物必须来自 `gh` 或 `ARTIFACT_ROOT` 已存文件；禁止编造分析来源与仓库数据。
