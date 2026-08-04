# OpenAI Codex 官方文档冻结快照

- 新增 `codex-doc/`，保存 2026-08-04 官方在线文档的 `index.md`、`manual.md` 和 `full.md`。
- 快照记录 RONDO `v0.146.0` 源码基线、官方来源、抓取时间和 SHA-256；正文未由 Agent 生成或改写。
- 新增不可覆盖已有日期目录的抓取脚本，并在根级 `AGENTS.md` 记录离线文档阅读顺序和源码优先级。
- 验收：官方网络下载成功；三个文件共 3,306,360 字节；`bash -n`、Markdown 形态检查、
  `sha256sum --check SHA256SUMS`、重复日期拒绝和 `git diff --check` 均通过。
