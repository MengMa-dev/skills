# 架构层 7 维度检查清单

检查源码时按此清单逐项取证。每个维度的回答必须落到具体文件和函数。未找到实现 = 缺失，不是「可能有」。

先从入口、Agent 循环、tool 注册、消息/state 对象这几处下手，再跟调用链往下读。

---

## 1. 任务规划（Task Planning）

判断当前规划范式：ReAct / Plan-and-Execute / CoT / 无显式规划 / 其他（命名）。

检查：

- 任务能否被分解为子任务？有无显式的 Plan 生成步骤？
- 子任务执行失败时，是动态重规划，还是直接报错退出？
- 规划结果是否可持久化，以支持断点续跑？
- 若完全没有规划层、只靠 LLM 单步决策，是否存在引入规划层的空间？引入点应挂在现有循环的哪一步？

取证方向：`plan` / `planner` / `decompose` / `replan` / `todo` / `steps`；ReAct 则看 think-act-observe 循环函数。

---

## 2. 多 Agent 协作

判断拓扑：单 Agent / 固定多 Agent / 动态派发。

检查：

- 当前是单 Agent 还是多 Agent？
- 若是单 Agent：是否存在天然适合拆成 Orchestrator + Worker 的场景（研究、编码、浏览、评审等）？
- 若已是多 Agent：通信协议是什么？角色职责是否清晰？结果如何聚合？
- Agent 之间是状态共享，还是完全无状态串行调用？

取证方向：`orchestrator` / `supervisor` / `handoff` / `swarm` / `crew` / `graph` 节点、消息总线。

---

## 3. 上下文管理策略（Context Management）

检查长对话和 token 上限怎么处理。

检查：

- context 接近模型 token 上限时：硬截断 / 滚动窗口 / 摘要压缩 / 无策略直接失败？
- 压缩或截断会不会丢掉关键工具调用历史或中间结果？
- 跨轮次对话历史如何存储和读取？有无重复塞入同一段 transcript？
- 系统指令 / 工具结果 / 对话历史是否差异化管理？

取证方向：`trim` / `truncate` / `summarize` / `compact` / `max_tokens` / `window` / memory store。

---

## 4. Human-in-the-loop 机制

检查执行中能否人工干预。

检查：

- 低置信度或高风险操作（写文件、外部 API、发消息、付款、删数据）是否会暂停等待确认？
- 有无 Checkpoint，支持中断后从断点恢复？
- 人介入后，反馈能否进入后续决策，还是只能重头跑？

取证方向：`interrupt` / `approval` / `confirm` / `checkpoint` / `human` / `hitl` / LangGraph `interrupt_before`。

---

## 5. Agent 评估框架（Evaluation）

检查能否系统评估 Agent 表现。

检查：

- 有无 eval 模块或测试集？粒度是只看最终答案，还是追踪完整 trajectory？
- 是否接入 LangSmith / Arize / 自定义 pipeline？
- 工具选择是否正确、参数是否合理，有没有被量化追踪？
- 若没有评估：最小可用 eval pipeline 的改造成本（文件数、能否复用现有 fixture）？

取证方向：`eval` / `evals` / `trajectory` / `langsmith` / `dataset` / `benchmark`。

---

## 6. Tool 检索与路由（Tool Retrieval）

检查工具怎么注册、怎么被选中。

检查：

- 全量 tool schema 注入 system prompt，还是按需检索？
- 工具数超过约 20 个时，有没有按任务检索相关子集（向量或其他索引）？
- 工具描述质量如何？是否语义过近导致选错工具？
- 是否支持 MCP？不支持的话，现有 tool 层接到 MCP 的改造点在哪？

取证方向：`tools` / `registry` / `bind_tools` / `mcp` / `list_tools` / embedding 检索。

---

## 7. Streaming 与中间状态可见性

检查执行过程对外是否可见。

检查：

- 是否支持 token-by-token streaming？
- 中间状态（当前子任务、调用了哪个工具、参数是什么）是否对外暴露？
- 有无事件/状态订阅接口，供前端展示进度？
- 若缺失：现有循环能否低侵入地挂上 streaming / 状态广播（回调、queue、SSE）？

取证方向：`stream` / `on_token` / `event` / `callback` / `SSE` / `websocket` / run state。

---

## 取证写法

现状描述至少包含：

```
`path/to/file.py` 中的 `function_name`
```

一条证据不够时再补调用链上下游各一处。不要用「核心模块」「agent 层」代替路径。
