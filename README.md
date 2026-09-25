# skills

MengMa 开源的 [Agent Skills](https://agentskills.io) 集合，可用于 Cursor、Claude Code、Codex 等兼容该规范的 Agent。

## 安装

```bash
npx skills add MengMa-dev/skills
```

## 仓库结构

```text
skills/
  <skill-name>/
    SKILL.md          # 必需：frontmatter + 指令
    scripts/          # 可选：可执行脚本
    references/       # 可选：按需加载的参考文档
    assets/           # 可选：模板与静态资源
test/                 # 本地 skill 测试工作区（gitignore，不入库）
```

跑 skill 测试 / evals 时，以仓库根目录的 `test/` 为工作目录、fixture 根目录，以及未指定 `LOCAL_PATH` 时的 clone 目标。该目录已被 gitignore，不要提交其中内容。

每个 skill 目录必须包含 `SKILL.md`，且 YAML frontmatter 包含 `name` 和 `description`。完整约定见 [Agent Skills 规范](https://agentskills.io/specification)。

## License

[MIT](LICENSE)
