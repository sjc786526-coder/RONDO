# RONDO

**RONDO Optimizes Networked Deliberation and Orchestration**

RONDO 是一个基于 Codex CLI 源码开展的实验性学习项目，目标是将 Agent Harness 的设计理论转化为可运行、可测量、可迭代的工程实践。项目主要由 AI 完成开发，人负责规划、约束与验收。

## 源码基线

- 上游项目：[OpenAI Codex](https://github.com/openai/codex)
- 冻结版本：Codex CLI `v0.146.0`
- 在主体开发完成前，RONDO 将保持该源码基线稳定；后续再评估和追加上游更新。

## 研究方向

1. 为 Agent Harness 内核建立量化测评基准，并基于测量结果尝试性能优化。
2. 研究共享可信证据链的多智能体协作，使工具调用结果等证据可以成为多个智能体的共同上下文，并评估其在方案审查、代码审查和多智能体通信中的效果与开销。
3. 将 Codex `approve for me` 的审批模型替换为本地训练和微调的约 4B 参数小模型，并量化其审批质量、安全性与成本。
4. 接入 Anthropic 格式接口以兼容 Claude 模型，同时完善 OpenAI 兼容接口的模型接入能力，为多智能体架构提供多模型基础设施。

## 当前状态

项目处于仓库初始化阶段，尚未形成稳定 API 或可发布版本。

## 许可证

RONDO 采用 [Apache License 2.0](LICENSE)。基于或包含的上游 Codex 源码继续受其原有许可证和 NOTICE 约束。
