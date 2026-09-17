# 阶段 0：搜索可贡献项目

在还没有目标仓库时，用 GitHub 数据筛出 **Top 3** 适合贡献的项目。本阶段只发现、不分析源码、不写代码。

需要 `gh` 已登录，或环境变量 `GH_TOKEN` / `GITHUB_TOKEN`。请求外网（GitHub + npm / PyPI / crates.io 下载量）。

## 何时进入

用户说：搜可贡献项目、找开源项目、按 star 筛仓库、没有 `REPO_URL` 但想贡献、列出值得提交 PR 的仓库。

用户已经给出明确 `REPO_URL` 时，跳过本阶段，直接阶段 1。

## 怎么跑

用**本 skill 目录**下的脚本执行（不要手写搜索结果顶替脚本）。先定位本 `SKILL.md` 所在目录（skill 根），再跑其中的 `scripts/discover_repos.py`——不要写死某一产品或某一用户的安装路径：

```bash
python3 "<本 skill 根目录>/scripts/discover_repos.py" \
  --top 3 \
  --domain agent \
  --user-language "<用户语言，如 zh / en / ja>" \
  --artifact-root "<ARTIFACT_ROOT>"
```

需要网络权限。若当前 cwd 不是 skill 根，必须传入脚本的绝对路径（由 skill 根解析得到）。

**每次搜索都必须传 `--artifact-root`**（即本 skill 的 `ARTIFACT_ROOT`，默认 `<当前任务工作目录>/artifacts`）。这样脚本才能读取 `search/` 历史，避免反复推荐同一批仓库。

**每次搜索都必须传 `--user-language`**：从用户当前消息判定（中文→`zh`，英文→`en`，日文→`ja`，其余用 BCP-47 短码）。未指定时默认 `zh`。该参数写入过滤说明，并约束下面的项目描述语言。

### 默认行为（防结果固化）

- 多组 query 的结果**轮询合并**，避免第一条热门 query 占满候选池。
- 默认最多 hydrate **40** 个候选再打分（`--max-candidates`）。
- 默认 **排除** `ARTIFACT_ROOT/search/` 历史结果里已出现过的 `owner/repo`（`--exclude-previous`）。
- 用户说「可以重复之前的 / 不要排除历史」时：加 `--no-exclude-previous`。

### 用户过滤条件（每次搜索可追加）

用户口头提的条件，**翻译成脚本参数**，不要忽略。可组合：

| 用户意图示例 | 参数 |
|---|---|
| 不限领域 | `--domain any` |
| 只要 TypeScript / Python | `--language TypeScript`（可重复） |
| 只要某 topic | `--topic mcp`（可重复） |
| 额外关键词（rag、evaluation…） | `--query "rag evaluation"`（**追加**到默认 query，不覆盖领域模板） |
| 完全自定义搜索词 | `--raw-query "browser use playwright"`（不再套 agent/any 模板） |
| stars 下限 / 上限 | `--stars 2000` / `--max-stars 20000` |
| 活跃窗口 | `--days 14` |
| Issue 关闭比更严 | `--min-ratio 2` |
| 不要某个仓库 | `--exclude owner/repo`（可重复） |
| 不要某个组织 | `--exclude-org langchain-ai`（可重复） |
| 允许重复历史推荐 | `--no-exclude-previous` |
| 用户语言（描述必须对齐） | `--user-language zh`（或 `en` / `ja` 等） |

示例（用户：只要 TS 的 MCP，排除之前看过的，stars 至少 2000）：

```bash
python3 "<本 skill 根目录>/scripts/discover_repos.py" \
  --top 3 \
  --domain agent \
  --language TypeScript \
  --topic mcp \
  --stars 2000 \
  --user-language zh \
  --artifact-root "<ARTIFACT_ROOT>"
```

脚本会打多组 GitHub 搜索、去重、轮询合并、应用排除与硬性条件，再打分（含下载量等使用信号）。

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
- **使用分** = `min(100, 100 × log10(1 + 使用信号) / log10(1 + 1,000,000))`  
  **使用信号**取以下三者中的**最大值**（用来回答「有多少人在用」）：
  1. **registry 近 30 天下载**：从 `package.json` / `pyproject.toml` / `Cargo.toml` 解析包名，查询 npm / PyPI / crates.io；解析不到则用仓库名猜测。PyPI 优先 pypistats.org，失败则用 ClickHouse 公开 `pypi` 数据集兜底。取不到时该项为空，不淘汰。
  2. **GitHub Release 资源月均下载** = 近 12 个月非 draft Release 的 `downloadCount` 之和 / 12。
  3. **流行度代理** = `Stars + 2 × Forks`（无下载数据时的兜底）。
- **总分** = `0.4 × PR 分 + 0.3 × Release 分 + 0.3 × 使用分`

按总分降序取 Top 3（同分再比使用信号、再比 stars）；合格不足 3 个就如实少列，不要用未过硬性条件的仓库凑数。

给用户看的每一条都必须写出使用情况：**registry 下载量**（来源与时间窗）、**Release 资源下载**、**使用分**，以及 Stars / Forks。数字必须来自脚本，禁止估算。

## 项目描述（用户语言 + 三要素）

脚本 stdout 里的「GitHub 简介 / Topics / README 摘要」只是**素材**，通常是英文一句 slogan，**不能**当作给用户的项目描述。

展示与落盘时，为 Top 中每一个仓库用**用户的语言**重写 `项目描述`（与 `--user-language` 一致；用户中文则中文，英文则英文，不要中英混写整段）。每一条必须覆盖下面三句，缺一不可：

1. **做什么**：项目本身是什么、核心能力（1～2 句，具体，禁止「赋能/领先」空话）。
2. **解决的问题**：它针对的痛点或核心问题。
3. **适用场景**：谁、在什么情况下该用它（2～4 个具体场景即可）。

改写规则：

- 只根据素材（GitHub 简介、topics、README 摘要、homepage）改写；素材不够可再读该仓库 README 前几段。禁止编造未提及的功能、下载量或 star 数。
- 排名、地址、得分、Stars/Forks/下载量/PR 分/Release 分/使用分：**原样保留脚本数字，不要改排名**。
- 用户可见列表中**删除**「GitHub 简介 / Topics / README 摘要 / 项目描述：（用用户语言改写…）」这些素材行，换成改写后的三要素。
- 技术专有名词保留英文（MCP、LangChain 等）。

用户可见条目形态：

```markdown
### 第 1 名：`owner/repo`（得分 55.10）
- 项目地址：https://github.com/owner/repo
- 项目描述：
  - 做什么：……
  - 解决的问题：……
  - 适用场景：……
- Stars：12,345；Forks：678；Watchers：90；语言：TypeScript；最近 push：2026-09-01
- 使用情况：registry 下载 89,000（npm:pkg，近 30 天）；Release 资源近 12 个月下载 1,200；使用信号 89,000（registry 近 30 天下载）；使用分 64.3
- Issue closed/open：……
- PR 中位合并：……
- 近 12 个月 Release：……
```

英文用户则把小标题写成 `What it does` / `Problem` / `When to use it`，指标行也可译成英文，但数字不变。

可在表后再加 1～2 句：为什么默认搜 Agent 向仓库，或本次用了哪些用户过滤。

若脚本失败：把 stderr 给用户，提示 `gh auth login` 或设置 token，不要用训练记忆编造仓库列表。

## 落盘

在回复用户的同时，把本阶段完整输出写入 `ARTIFACT_ROOT`（默认 `<当前任务工作目录>/artifacts`）：

```
<ARTIFACT_ROOT>/search/<YYYYMMDD-HHMMSS>.md
```

- 文件名用**本次执行开始时**的本地时间，例如 `20260912-173800.md`。
- `search/` 不存在则先创建。
- **每次搜索新建一个文件**，不要覆盖历史搜索结果（历史文件也是下次 `--exclude-previous` 的数据源）。
- 文件正文与聊天展示内容一致（含**改写后**的用户语言项目描述，以及使用情况数字）；文首可加一行元数据：`# 搜索时间: ...` 与所用参数（`--domain` / `--query` / `--language` / `--user-language` / `--exclude` / `--top` 等）。

脚本失败时：仍写入该 md（记录命令、stderr、失败原因），方便回溯。

## 结束后

停下来，请用户从 Top 3 里选一个（或给出别的 `REPO_URL`），再进入阶段 1。回复里可附上本次落盘路径。可提醒：下次搜索默认会排除本次 Top 里的仓库；若要换一批过滤条件可直接说。
