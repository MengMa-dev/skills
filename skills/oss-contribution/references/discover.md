# 阶段 0：搜索可贡献项目

在还没有目标仓库时，用 GitHub 数据筛出 **Top 3** 适合贡献的项目。本阶段只发现、不分析源码、不写代码。

需要 `gh` 已登录，或环境变量 `GH_TOKEN` / `GITHUB_TOKEN`。请求外网。

## 何时进入

用户说：搜可贡献项目、找开源项目、按 star 筛仓库、没有 `REPO_URL` 但想贡献、列出值得提交 PR 的仓库。

用户已经给出明确 `REPO_URL` 时，跳过本阶段，直接阶段 1。

用户明确要 Agent / LLM / MCP 架构向仓库时，改用 `agent-oss-contribute`，不要在本 skill 里改走 `--domain agent` 作为默认。

## 怎么跑

用**本 skill 目录**下的脚本执行（不要手写搜索结果顶替脚本）。先定位本 `SKILL.md` 所在目录（skill 根），再跑其中的 `scripts/discover_repos.py`——不要写死某一产品或某一用户的安装路径：

```bash
python3 "<本 skill 根目录>/scripts/discover_repos.py" \
  --top 3 \
  --domain any \
  --artifact-root "<ARTIFACT_ROOT>"
```

需要网络权限。若当前 cwd 不是 skill 根，必须传入脚本的绝对路径（由 skill 根解析得到）。

**每次搜索都必须传 `--artifact-root`**（即本 skill 的 `ARTIFACT_ROOT`，默认 `<当前任务工作目录>/artifacts`）。这样脚本才能读取 `search/` 历史，避免反复推荐同一批仓库。

默认 `--domain any`：不套 Agent 关键词。未传 `--language` 时，按默认技术栈搜 Python、TypeScript、Go、Rust。

### 默认行为（防结果固化）

- 多组 query 的结果**轮询合并**，避免第一条热门 query 占满候选池。
- 默认最多 hydrate **40** 个候选再打分（`--max-candidates`）。
- 默认 **排除** `ARTIFACT_ROOT/search/` 历史结果里已出现过的 `owner/repo`（`--exclude-previous`）。
- 用户说「可以重复之前的 / 不要排除历史」时：加 `--no-exclude-previous`。

### 用户过滤条件（每次搜索可追加）

用户口头提的条件，**翻译成脚本参数**，不要忽略。可组合：

| 用户意图示例 | 参数 |
|---|---|
| 不限领域 | 默认即 `--domain any`，不必再传 |
| 只要 TypeScript / Python / Go / Rust | `--language TypeScript`（可重复；传入后替换默认语言列表） |
| 只要某 topic | `--topic cli`（可重复） |
| 额外关键词（http、parser…） | `--query "http parser"`（**追加**到默认 query，不覆盖领域模板） |
| 完全自定义搜索词 | `--raw-query "cli argument parser"`（不再套默认语言模板） |
| stars 下限 / 上限 | `--stars 2000` / `--max-stars 20000` |
| 活跃窗口 | `--days 14` |
| Issue 关闭比更严 | `--min-ratio 2` |
| 不要某个仓库 | `--exclude owner/repo`（可重复） |
| 不要某个组织 | `--exclude-org cli`（可重复） |
| 允许重复历史推荐 | `--no-exclude-previous` |

示例（用户：只要 Go，排除之前看过的，stars 至少 2000）：

```bash
python3 "<本 skill 根目录>/scripts/discover_repos.py" \
  --top 3 \
  --domain any \
  --language Go \
  --stars 2000 \
  --artifact-root "<ARTIFACT_ROOT>"
```

脚本会打多组 GitHub 搜索、去重、轮询合并、应用排除与硬性条件，再打分。

## 硬性条件（不满足即淘汰）

- Stars ≥ `--stars`（默认 1000）；若给了 `--max-stars` 则同时 ≤ 上限
- 近 `--days` 天内有 commit/push（`pushedAt`，默认 30）
- 未 archived、非 fork
- Issue **closed / open > `--min-ratio`**（默认 1；open = 0 且 closed > 0 视为通过；两边都是 0 淘汰）
- 样本里至少 3 条已合并 PR（否则算不出合并速度）
- 命中排除列表（手动 `--exclude` / `--exclude-org`，或历史 search）的仓库淘汰

## 得分（只对通过硬性条件的仓库）

- **PR 合并速度分** = `100 / (1 + 中位合并天数)`  
  中位合并天数来自最近最多 25 条 merged PR 的 `mergedAt - createdAt`。越快越高。
- **Release 频率分** = `min(100, 近 12 个月非 draft Release 数 / 12 × 100)`  
  平均每月 1 次 Release 打满 100。
- **总分** = `0.5 × PR 分 + 0.5 × Release 分`

按总分降序取 Top 3；合格不足 3 个就如实少列，不要用未过硬性条件的仓库凑数。

## 输出格式

把脚本的 stdout **原样展示**（已含地址、描述、本次过滤与排除说明）。不要改排名。可在表后再加 1～2 句：本次用了哪些用户过滤，以及默认不限领域、语言跟默认技术栈。

若脚本失败：把 stderr 给用户，提示 `gh auth login` 或设置 token，不要用训练记忆编造仓库列表。

## 落盘

在回复用户的同时，把本阶段完整输出写入 `ARTIFACT_ROOT`（默认 `<当前任务工作目录>/artifacts`）：

```
<ARTIFACT_ROOT>/search/<YYYYMMDD-HHMMSS>.md
```

- 文件名用**本次执行开始时**的本地时间，例如 `20260912-173800.md`。
- `search/` 不存在则先创建。
- **每次搜索新建一个文件**，不要覆盖历史搜索结果（历史文件也是下次 `--exclude-previous` 的数据源）。
- 文件正文与聊天展示内容一致；文首可加一行元数据：`# 搜索时间: ...` 与所用参数（`--domain` / `--query` / `--language` / `--exclude` / `--top` 等）。

脚本失败时：仍写入该 md（记录命令、stderr、失败原因），方便回溯。

## 结束后

停下来，请用户从 Top 3 里选一个（或给出别的 `REPO_URL`），再进入阶段 1。回复里可附上本次落盘路径。可提醒：下次搜索默认会排除本次 Top 里的仓库；若要换一批过滤条件可直接说。
