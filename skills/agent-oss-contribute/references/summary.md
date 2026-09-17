# 阶段 5：产出 PR 总结

把已经提过的 PR 收成一份可对外讲述的 `summary.md`。本阶段只读、只写总结文件，不改目标仓库、不开新 PR、不重跑阶段 0–4。

用户给出「之前提过的项目」或 `PR_URL` 时进入；缺这两类输入就问，不要用记忆里的仓库硬写。

## 输入

| 字段 | 说明 |
|------|------|
| `PR_URL` | `https://github.com/<owner>/<repo>/pull/<n>`；有则优先 |
| 项目标识 | 仓库 URL、`owner/repo`、`<owner>-<repo>`、或 repo 短名 |
| `ARTIFACT_ROOT` | 中间产物根目录；缺省为 `<当前任务工作目录>/artifacts`（本仓库 evals 时为 `<仓库根>/test/artifacts`） |

`LOCAL_PATH` 本阶段不需要。不要为了写总结去克隆或切仓库。

## 工作流

```
- [ ] 1. 解析输入：定位 owner / repo / PR
- [ ] 2. 读本地中间产物（缺文件不中止，注明未找到）
- [ ] 3. 用 gh 拉仓库元数据 + PR 正文（有 PR 时必拉）
- [ ] 4. 按固定五节写 summary，落盘后结束
```

定位不到唯一项目或唯一 PR 时停下让用户选，**不要**先写一份猜测文件。

---

## 1. 解析输入

**有 `PR_URL`：** 从路径解析 `owner`、`repo`、PR number。项目名固定为 `<owner>-<repo>`。

**只有项目标识：** 在 `<ARTIFACT_ROOT>/project/` 下列目录做匹配：

1. 目录名等于 `<owner>-<repo>`
2. 目录名以 `-<repo>` 结尾
3. 目录名或用户字符串互相包含（大小写不敏感）

- 命中 1 个：用它
- 命中多个：列出目录名给用户选，停下
- 命中 0 个：不要编造 `project/` 内容；仍可用 `gh` 查远程，同时告诉用户本地无中间产物

**补 PR：** 本地 `<ARTIFACT_ROOT>/project/<owner>-<repo>/pull-request.md` 里若已有最终 PR URL，直接用。否则：

```bash
gh pr list --repo OWNER/REPO --author @me --state all --limit 20 \
  --json number,title,url,state,updatedAt
```

- 1 条：用它
- 多条：列出 `number / title / url / state` 让用户选，停下
- 0 条且没有 `PR_URL`：问用户要 PR 地址，停下

## 2. 读本地中间产物

路径均相对 `ARTIFACT_ROOT`。按存在与否读取，缺的在总结里写「未找到」，不要用训练记忆补全分析结论。

| 文件 | 用来写哪一节 |
|------|----------------|
| `project/<owner>-<repo>/analysis.md` | 项目简介、如何发现 |
| `project/<owner>-<repo>/design.md` | PR 背景、实现方案 |
| `project/<owner>-<repo>/implementation.md` | 实际改了什么、收益对照验证 |
| `project/<owner>-<repo>/pull-request.md` | PR 标题、正文、URL |

先读这些文件再调 `gh`。禁止跳过本地产物直接凭 PR 标题发挥。

## 3. 拉远程信息

star 数、仓库描述、PR 正文必须来自 `gh`，禁止用记忆中的数字。

```bash
gh repo view OWNER/REPO --json name,url,description,stargazerCount,forkCount,primaryLanguage,homepageUrl
gh pr view N --repo OWNER/REPO --json title,body,url,number,files,additions,deletions,baseRefName,headRefName,state,mergedAt,author
```

已有完整 `PR_URL` 时可用 `gh pr view <PR_URL> --json ...`。

`gh` 失败：把错误原文给用户；能写的本地部分仍可落盘，但项目简介里的 Stars 写「未取到」，不要填假数字。

README 只在仓库 description 不够写满功能说明时再取（`gh api repos/OWNER/REPO/readme --jq .content` 解码，或本地已有 clone 则读 `README.md`）。不要为 summary 新建 clone。

## 4. 输出格式（标题不要改）

聊天输出与落盘全文一致。五个二级标题必须原样使用、按此顺序、不要增删节。

```markdown
# {PR 标题}

## 项目简介

- 仓库：{https://github.com/owner/repo}
- Stars：{stargazerCount}
- Language：{primaryLanguage.name 或 未知}
- Forks：{forkCount}

{最多 3 句话说明项目做什么。来自 description / README / analysis.md 准备工作。禁止营销腔和「赋能/领先」空话。}

## 本次 PR 背景

{2~5 句：仓库里原来缺什么、本 PR 做了什么。来源：PR body 的 Problem + design.md 选定方案 / 问题边界。没有 design.md 时用 PR body，并写明依据 PR 描述。}

## 如何发现这个问题 / 功能

{必须可追溯。优先顺序：
1. analysis.md 里的 Issue # 或「代码分析-维度X」
2. 用户在对话里指定的方向
3. PR body / 关联 Issue
本地 analysis.md 缺失时，明确写「本地分析产物未找到，依据 PR 描述」。禁止写「我觉得」「众所周知」。}

## PR 实现方案

{核心思路 + 改了哪些文件/层。来源：design.md 选定方案与文件清单、implementation.md 改动摘要、PR Changes / files。不要贴整份 diff，不要复述未落地的备选方案。}

## 带来哪些收益

{对仓库用户、维护者或后续贡献者的具体收益。对照 design.md 成功标准、implementation.md 验证结果、PR Testing。禁止空泛「提升代码质量」「增强可维护性」而不说清对谁、解决了哪条路径上的什么问题。}
```

功能说明超过 3 句就删到 3 句。背景不要把实现细节写完（细节放「实现方案」）。

## `<pr名>`

文件名（不含 `.md`）按下面生成，保证可进文件系统：

1. 有 PR number：`{number}-` 作为前缀
2. 标题里 `/ \ : * ? " < > |` 与空白换成 `-`，连续 `-` 压成一个，去掉首尾 `-`
3. ASCII 字母小写；中文等非 ASCII 保留
4. 整段截断到 80 字符
5. 仍为空则只用 `{number}`；连 number 都没有则用 `untitled`

例：`142-feat-retry-on-tool-timeout`、`87-为工具调用增加超时重试`

落盘路径（相对 `ARTIFACT_ROOT`，默认 `<当前任务工作目录>/artifacts`）：

```
<ARTIFACT_ROOT>/summary/<owner>-<repo>/<pr名>.md
```

目录不存在则创建。同一 PR 再跑则覆盖该文件。不要写到 `project/` 下。

## 本阶段硬约束

- 只写 `summary/` 下这一份 md；不要改 `project/` 已有文件，不要改目标仓库。
- 不要 `git commit` / `push` / `gh pr create`。
- 不要因为缺中间产物而中止；缺什么写什么，补远程能拿到的部分。
- 不要把阶段 1 的七层分析或阶段 2 全文粘进 summary。
- 用户只说「总结」但既无项目也无 PR：先列出 `<ARTIFACT_ROOT>/project/` 下已有目录（若有），请用户指定，不要挑一个就写。

## 完成后

停。回复里附落盘路径。不要提议自动进入别的阶段。
