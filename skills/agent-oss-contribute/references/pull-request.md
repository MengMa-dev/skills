# 阶段 4：提交 PR

用户明确要求提交 / 开 PR 时才进入本阶段。按逻辑提交 2~4 个 commit，再用 `gh` 开 PR。不要改 git config，不要 `--no-verify`，不要 force push 到 `main`/`master`。

## 提交前检查

在 `LOCAL_PATH` 下**并行**收集：

- `git status`（含未跟踪文件）
- `git diff`（staged + unstaged）
- `git log` 与 `git diff [base-branch]...HEAD`（了解本分支相对主分支的历史）
- 当前分支是否跟踪远程、是否需要 push

不要提交密钥文件（`.env`、`credentials.json` 等）。用户点名要提交这类文件时先警告。

若在 `main`/`master` 上有未提交改动：先建功能分支再 commit。分支名用仓库习惯；没有习惯时用 `feat/<scope>` 或 `fix/<scope>`。

## Commit

按阶段 3 的「Git 提交计划」执行。每个 commit 只做一件事。type 只用：`feat` / `fix` / `refactor` / `test` / `docs`。

消息走 HEREDOC，1~2 句写原因：

```bash
git add <relevant-files>
git commit -m "$(cat <<'EOF'
feat(scope): 一句话描述

EOF
)"
```

commit 失败（含 hook 拒绝）时：修好后打 **新的** commit，不要 `--amend`，除非同时满足：用户要求 amend、HEAD 是本会话刚做的 commit、且还没 push。

提交后 `git status` 确认干净（或只剩有意不提交的文件）。

## Push 与开 PR

需要时先 `git push -u origin HEAD`。然后：

```bash
gh pr create --title "feat(scope): 一句话描述" --body "$(cat <<'EOF'
## Problem
...

## Solution
...

## Changes
- ...

## Testing
- ...

## Notes for Reviewer
...

EOF
)"
```

**PR body 禁止项（必须遵守）：**

- 不要追加 `## Test plan`、checklist（`- [ ]` / `- [x]`）、或任何「验证清单」小节。验证写在 `## Testing` 的普通列表即可。
- 不要追加任何 AI/编辑器署名 footer（例如 `Made with …`）。
- 不要套用宿主 Agent 的全局 PR 模板（如 Summary + Test plan）；本阶段只用上面的 Problem / Solution / Changes / Testing / Notes for Reviewer。
- `gh pr create` 的 `--body` 以 `Notes for Reviewer` 一节结束，其后不得再有额外段落。

若仓库 `CONTRIBUTING.md` 或 `.github/PULL_REQUEST_TEMPLATE.md` 有必填段落，保留它们，并把下面各节填进去（可嵌进模板对应标题下）。模板自带的 checklist 若属于仓库要求可保留；**仍不要**自行追加 AI/编辑器署名。

## PR 描述草稿（标题和分节名不要改）

**标题：** `{type}({scope}): {一句话描述}`

**Problem**（描述当前存在的问题，客观陈述，不带情绪）

**Solution**（描述本 PR 的解决思路，以及为什么选择这个方案）

**Changes**

- 新增 / 修改了什么

**Testing**

- 如何验证这个改动有效
- 测试用例覆盖了哪些场景

**Notes for Reviewer**（需要 reviewer 重点关注的地方，或有意为之的设计决策）

标题的 type 与主导 commit 一致。Problem 写仓库里的客观缺口，不要写「我觉得很乱」。Solution 对应阶段 2 的选定方案。Changes 对照 `git diff`。Testing 写实际跑过的命令和覆盖场景；用短句列表，**不要**改成 checkbox checklist。

落盘与最终 `gh pr create` 的 body 均不得含 AI/编辑器署名或自造 Test plan checklist。

## 落盘

开 PR 成功（或失败）后，把本阶段产物写入 `ARTIFACT_ROOT`（默认 `<当前任务工作目录>/artifacts`）：

```
<ARTIFACT_ROOT>/project/<owner>-<repo>/pull-request.md
```

至少包含：PR 标题草稿、Problem/Solution/Changes/Testing/Notes for Reviewer 全文、最终 PR URL（成功时）、所用分支与 base。失败时写错误原文与已执行的 git/`gh` 命令。项目目录不存在则创建；已有则覆盖。

## 完成后

只返回 PR URL，外加一行：标题、相对的 base 分支，以及落盘路径。不要再复述整份 diff。不要自动进入阶段 5；用户要总结时再读 [summary.md](summary.md)。

若 `gh` 鉴权失败或远程拒绝：停下来把错误原文给用户，不要改用 web 界面凑合，也不要 force push；仍写入 `pull-request.md`。
