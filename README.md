# RONDO

**RONDO Optimizes Networked Deliberation and Orchestration**

RONDO 是一个基于 Codex CLI 源码开展的实验性学习项目，目标是将 Agent Harness 的相关理论转化为可运行、可测量、可迭代的工程实践。

## codex源码基线

- 上游项目：[OpenAI Codex](https://github.com/openai/codex)
- 冻结版本：Codex CLI `v0.147.0`
- 当前研究周期保持该源码基线稳定；后续上游更新仍需作为独立任务评估。
- codex源码位于codex-source-code/

## 产品线

RONDO 由两套并列的产品源码组成，共享测评、构建锁与工具设施：

- **RONDO Local**（`mydev/`）：保持冻结 Codex 的单智能体 thread/rollout 语义，扩展 Guardian 的模型、
  reasoning effort、provider 与本地推理能力，承载研究方向 1、2。
- **RONDO Multi**（`multidev/`）：研究方向 3 的独立产品源码，可自由演进任务图与证据图，不要求与 Local 同内核。

两者的 crate 名与二进制名沿用上游（`codex-cli` / `codex`），产品身份由测评侧路径与字段承担。
当前阶段与建立进度见 `doc/WBS.md`。

## 模型选取

- 标准性能测评的供应商、base URL、主模型与 Guardian 模型由 ignored `rondo.local.toml` 的
  `paid_eval` profile 选择；每个真实批次再由独立 pair lock 冻结实际条件，生产源码不固定某个供应商或模型。
- 多智能体方向探索独立调查、证据复用和可验证汇合；具体模型组合与流程由后续测评决定，不在项目简介中固定。
- 本地审批模型采用可替换的 OpenAI-compatible 接口；当前基线模型与验收状态以 `doc/WBS/local-approval-model.md` 为准。

## 研究方向

0. 为RONDO建立量化测评基准，以便后续基于性能指标驱动优化或者检验效果（原始codex和RONDO统一关闭websocket)：
    A、轻量离线冻结回放测评，用于测评运行时和数据结构优化，工具执行优化等行为保持型优化，以及故障注入，同时降低反复测评的成本。
    B、真实 API + Terminal-Bench 2.1 实际任务测试，用于测评行为改变型优化，同时作为最终真正可信的测评指标。
1. 学习其他agent harness实现，尝试RONDO在Terminal-Bench 2.1 Task Resolution Success Rate指标上的性能优化。（此优化允许为不可插拔，无需实现一键切换，但是应当保证可以与原始冻结的codex尽可能公正对比）
2. 将 Codex `approve for me` 的审批模型尝试替换为微调后在本地推理的小模型，并量化其审批质量与成本相对云端教师模型的差距。（此能力应该设置为可插拔式，可一键切换审批模型，且尽可能不影响原有功能与性能；参与对比的具体模型见 `doc/WBS/local-approval-model.md`）
3. 研究共享可信证据链的多智能体协作，使工具调用结果等证据可以成为多个智能体的共同上下文，并评估其在方案审查、代码审查和多智能体通信中的效果与开销。（此能力作为**独立产品源码**开展，与单智能体产品线并列演进，不作为其内部的可插拔模式）

## 许可证

RONDO 采用 [Apache License 2.0](LICENSE)。基于或包含的上游 Codex 源码继续受其原有许可证和 NOTICE 约束。
