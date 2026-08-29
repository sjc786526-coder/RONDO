# Plan 098 工作包二最终验收整改日志

## Finding 与整改

- 最终验收首轮 finding 成立：原 finalizer 只核对权威任务 Markdown 的内容 SHA，并把 accepted implementation commit 常量写入工件；renderer、五头任务实现、consumer 或其他 projection 单独漂移时不会重新锁定工作包二。
- 保持工作包一 accepted commit `55342bdb11b09c11b589fd398717f7712fca012c` 的任务语义组件原字节不变；把任务/产品合同、packet validator、renderer、五头 task/data reference 和正式 input/rubric/output/release projections 共 13 个必要组件冻结为有序 canonical component list。组合 SHA-256 为 `b0124de561f52fb464c223989d003af1e9f2a8a24eccd9ca349a4d769e3488d5`。
- `load_build_contracts()` 现在先核对固定 commit、算法、组件路径、组合 SHA 和每个当前文件的实际 SHA；缺失、symlink、字节漂移或 design/config identity 不一致均 fail-closed。`finalize_successor_release()` 在检查 workspace、创建临时目录或写正式输出前调用该门禁。
- data design 保存完整组件绑定，generation config 绑定 commit、组合 SHA 和 design 原始 SHA，release identity 保存完整 accepted implementation；沿用既有 finalizer/identity 体系，没有新增通用审计、签名或可信设施。
- focused regression 保持权威任务 Markdown 不变，逐一漂移其余 12 个受保护组件，均验证 finalizer 在输出创建前拒绝；正常 accepted bytes、commissioning 链与 tracked consumer 继续通过。

## 重冻与验证

- 从不存在的 tracked 输出目录重新运行一次正式 finalizer。`publication-critic-v9` 仍为 216 candidates / 96 pairs，物理 split 仍为 162/27/27 candidates 与 72/12/12 pairs。
- 与整改前 release 逐文件比较后，只有 `design-lock.json`、`generation-config.json`、`release-identity.json` 和 `DATA_CARD.md` 变化；manifest、coverage、train-only smoke、三个冻结模块和全部 split 均保持原字节。manifest SHA-256 仍为 `756d7ea4c53673a447860fb4cfc245a98f5c15383569f137b1e07eacf7f90118`。
- 新 design/config/release identity SHA-256 分别为 `6fa235dce3dc37ce38514f6fbf1aee01194c164f90bc557897a2c9746f77afd7`、`0024ee7a52bec2b92b89cea68e692669186354d0bd5dde3615201b5b0344d5b4`、`9372525b9682bfbdd36ba013fc81bf3417172bcb19127652c344b0a08ffc81fe`。
- successor contract/release 与旧 contract/training-data/identity 定向回归 `47/47` passed，0 failure/error/skip；Python compile、JSON/identity readback、组件/组合 hash、正式输出差异与 Git diff 门均复核。
- 冻结 v8 tree 保持 `63981483baa00c671987d4b82887909fcc320690`，v7 tree 保持 `435c06fba3196bee21d59d88b9e6d6b1a1e1999a`。未运行 Rust/Cargo、真实模型、GPU、RunPod、Docker、付费 API 或产品动作。

## ignored 资产

- 保留原 `/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/`，并新增 `commissioning/pre-semantic-gate-release/` 保存整改前正式 release 基线；它与原 `commissioning/actual-release-check/` 均是可恢复的旧身份副本。`commissioning/semantic-gate-release-check/` 保存最终代码下的 clean-run 副本，并与最终 tracked release 逐字节一致。
- namespace 当前 54 个文件、1,229,158 原始文件字节，`du` 约 1.4 MiB；`modules/` 和 `reviews/` 保留正式 author/reviewer 输入。最终复验期间应继续保留，Plan 098 最终通过后可整体清理；未创建持久测试临时目录，未触碰其他任务 namespace。
