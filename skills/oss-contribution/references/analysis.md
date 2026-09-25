# 阶段 1：开源项目贡献分析

为目标仓库找出 **1~3 个可在约 2 周内完成、且能对外讲清贡献价值** 的 PR 方向。每个结论必须落到 Issue 号或具体文件/函数。

## 输入

| 字段 | 默认 |
|------|------|
| `REPO_URL` | 必填 |
| 技术栈 | 未给则用流水线默认栈（Python、TypeScript、Go、Rust） |
| 目标周期 | 未给则用：2 周 |
| 目标数量 | 1~3 个 PR 方向 |

当前工作区若已是该仓库，直接读本地源码。否则用 `gh` 拉 Issue / 文件，必要时浅克隆后再读。

## 工作流

```
- [ ] 1. 准备工作：读介绍文档、Agent 规范、常规配置 + 目录树 + 描述核心执行路径
- [ ] 2. 维度一：Issue 筛选
- [ ] 3. 维度二：七维贡献缺口（先读 contribution-dimensions.md）
- [ ] 4. 综合 Top 3 贡献建议
```

不要跳过维度二。Issue 筛不出合格项时，明确写「无符合条件的 Issue」，Top 3 仍必须从源码缺口给出。

不要改用 Agent 七层。即使用户给的是 Agent 仓库，本阶段仍按通用七维取证；Agent 架构层分析属于 `agent-oss-contribute`。

---

## 1. 准备工作

先读完下面三类文件，再画目录树、再写核心路径。禁止只读 `README.md` 就进入维度分析。不存在的路径跳过，并在报告里列「未找到」。报告只写已读/未找到清单和从中得到的约束，不要粘贴文件全文。

**项目介绍**（仓库根与 `docs/`）：

- `README.md` 及 `README.*`；`docs/` 下的概述、getting-started、architecture
- `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md`、`GOVERNANCE.md`
- `CHANGELOG.md` / `HISTORY.md` / `CHANGES.md`
- `ARCHITECTURE.md`、`DESIGN.md`，以及根目录或 `docs/` 里的 SPEC / RFC

**Agent 规范**（写给 coding agent 或贡献者的指令；在仓库根、`.github/`、`.cursor/`、`docs/` 查找）：

- `AGENTS.md`、`AGENT.md`、`CLAUDE.md`、`GEMINI.md`、`COPILOT.md`
- `.github/copilot-instructions.md`、`.github/instructions/`
- `.cursorrules`、`.cursor/rules/`
- 文件名含 agent / copilot / claude / cursor rules 的其他规范

**常规配置**（用来确认语言、入口、脚本和约束；锁文件只看存在与否，不要逐行读）：

- 清单与构建：`package.json`、`pyproject.toml`、`setup.cfg`、`setup.py`、`go.mod`、`Cargo.toml`、`pom.xml`、`build.gradle`、`composer.json`、`Gemfile`
- 任务入口：`Makefile`、`justfile`、`Taskfile.yml`，以及 `package.json` 的 `scripts`
- 运行环境：`Dockerfile`、`docker-compose.yml`、`.nvmrc`、`.python-version`、`rust-toolchain.toml`
- CI：`.github/workflows/` 里的主 workflow（只看测试与发布命令）
- 风格：`.editorconfig`、`ruff.toml`、eslint / rustfmt / gofmt 配置（只看项目强制的风格，不展开全部规则）

然后读项目主入口（按仓库实际入口：`main`、`cmd/`、包入口、`index.ts` 等）。

然后输出 **depth=3 的目录结构**。在核心模块目录旁标注 `← 核心`。

接着用 2~3 句话回答：

- 这个项目的核心执行路径是什么？（从入口到主要产出）
- 架构风格是什么？（库 / CLI / 服务 / 框架扩展 / 单体应用 / 其他并命名）

这两句必须引用入口文件或主函数，禁止只复述 README 营销文案。

---

## 2. 分析维度一：Issue 列表筛选

用 `gh` 拉 **open** Issue。标签命中以下**之一**即可：`good first issue`、`help wanted`、`bug`、`enhancement`。再过滤，**必须同时满足**：

- 近 60 天内有活动（看 `updatedAt` / 评论时间，排除 stale）
- 无人认领：无 assignee，且评论中无人声称 `I'll take this` / `I'm working on this` / `assigned to me` / `我来做`
- 描述清晰：有期望行为或可复现步骤
- 改动范围大约 1~3 个文件，不涉及整体架构重构
- 工作量能落在目标周期内

```bash
gh issue list --repo OWNER/REPO --state open --limit 100 \
  --json number,title,labels,assignees,updatedAt,comments,url,body
```

标签过滤可多次调用后合并去重。不要把 closed / 已认领 / 纯讨论贴进表。

**输出表格（列名不要改）：**

| Issue # | 标题 | 类型 | 所需技能 | 预估工作量 | 推荐理由 |

类型用：`bug` / `enhancement` / `good first issue` / `help wanted`（取最贴切的主标签）。

预估工作量用：`0.5d` / `1d` / `2-3d` / `1w`，不要用模糊的「简单」。

零结果时输出一行说明，不要凑数。

---

## 3. 分析维度二：贡献缺口

先完整阅读 [contribution-dimensions.md](contribution-dimensions.md)，再按那 7 个维度逐项检查源码。

每个维度都必须定位到 **具体文件路径 + 函数名**。禁止「整体上看错误处理较弱」这类空话。找不到实现就写清搜过哪些目录/符号，结论标成缺失。

**每个维度固定输出（标题与字段名不要改）：**

**现状描述：**（文件路径 + 函数名）

**缺陷 / 缺失：**（当前方案的问题，或完全缺失）

**影响程度：** high / medium / low

**改进方向：**（1~3 句话，可落地的改法）

**改动范围：**（预计文件数 + 代码行量级，如「2~4 文件 / ~150 行」）

**可对外讲清的贡献价值：**（一句话：这个贡献解决了什么、对谁有用）

七个维度标题按 `contribution-dimensions.md` 中的顺序原样使用。

影响程度要诚实：只有会在生产中丢数据、无法恢复、错误副作用、或可被外部输入触发的安全问题时才标 high。纯体验或纯文档优化标 low。

---

## 4. 最终输出：Top 3 贡献建议

综合 Issue 与七维分析，按**可对外讲清的贡献价值 × 可完成性**排序，最多 3 条。优先满足：

1. 能在目标周期内完成（默认 2 周）
2. 和用户技术栈重叠
3. 有一条能讲清楚的技术决策，而不是改文案/修 typo
4. 入口文件明确，reviewer 容易看懂范围
5. 不依赖未合并的巨型 RFC 或核心维护者口头拍板

少于 3 个合格项就少输出，不要注水。

**每条格式（字段名不要改）：**

**第 N 名：{PR 方向名称}**

- 一句话描述：
- 来源维度：Issue #xxx / 代码分析-维度X
- 入口文件：
- 为什么适合我：（结合用户技术栈）
- 预计工作量：小 / 中 / 大
- 可对外讲清的贡献价值：（具体技术决策与对仓库/用户的收益，不要空泛的「熟悉开源」）
- 风险点：（维护者偏好、测试缺口、兼容性、需要设计讨论等）

工作量约定：小 ≈ 1~3 天，中 ≈ 1 周，大 ≈ 2 周。超过 2 周的不要进 Top 3。

## 落盘

在回复用户的同时，把本阶段完整分析报告写入 `ARTIFACT_ROOT`（默认 `<当前任务工作目录>/artifacts`）：

```
<ARTIFACT_ROOT>/project/<owner>-<repo>/analysis.md
```

- `<owner>-<repo>` 来自 `REPO_URL`（例：`pallets-click`）。
- 目录不存在则创建；`analysis.md` 已存在则**覆盖**为本次全文。
- 内容与聊天输出一致。

输出结束后停。提示用户选第 N 名（或给出自己的方向），再进入阶段 2。回复里可附上落盘路径。

## 本阶段硬约束

- 引用路径用仓库内相对路径。
- 不要建议无法在 2 周内落地的重构。
- 用户若只要其中一块（例如只要 Issue 表），仍做完准备工作，再按需截取；未声明截取时输出全文。
- 必须落盘到对应 `project/<owner>-<repo>/analysis.md`，不能只回复不写文件。
