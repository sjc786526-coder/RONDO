# OpenAI Codex documentation

本目录保存从 OpenAI 官方在线文档下载并按日期冻结的 Markdown 快照，供 RONDO 离线检索和实验复现。
快照不是 Codex CLI 的版本化文档发布物；抓取日期、RONDO 源码基线和来源地址以各快照内的
`SOURCE.md` 为准。

## 当前快照

- `snapshot-2026-08-04/`

阅读顺序：先读 `manual.md` 获取精简说明，通过 `index.md` 定位主题，需要完整核验时检索
`full.md`。判断 RONDO 实际行为时，`mydev/` 中的源码和测试高于文档快照。

## 创建快照

在仓库根目录运行：

```bash
./codex-doc/fetch-snapshot.sh YYYY-MM-DD
```

脚本只创建新快照，不覆盖已有日期目录。所有下载成功后才会发布目标目录，并同时生成来源说明和
SHA-256 校验和。已冻结快照不应手工修改。
