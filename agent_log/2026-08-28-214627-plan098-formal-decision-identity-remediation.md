# Plan 098 正式判定 direct dependency identity 窄整改

日期：2026-08-28

状态：`IMPLEMENTED / FINAL_REVIEW_PENDING`

## 结论与实现

复验 finding 属实：旧 decision component list 绑定 `qualification.py`，却未绑定它正式 decode 时直接使用的 task runtime 和 raw output
schema，因此这两个依赖漂移后旧 frozen config 仍可通过 identity 校验。

本轮把以下两个直接依赖加入现有 canonical decision component list：

- `eval/rondo_eval/publication_critic/successor_task.py`；
- `eval/templates/publication-critic/successor-output-schema-v1.json`。

没有复用完整 13 组件 accepted-task bundle。后者还包含 renderer、consumer 等不是 formal decoder 直接执行的组件，会扩大 operating config
耦合；固定上述两项字节与现有 decision decoder/projection/metrics 组合 SHA，已等强覆盖本 finding，且保持轻量。

新增 focused 回归分别在临时 repo 漂移 task runtime 和 raw schema，再调用正式 `decode_with_decision_config`。修复前两处均未抛错，修复后两处
均在解析 logits 前以 implementation component mismatch fail-closed。

## 身份与 release

- decision implementation commit：`391378ee568f6d37b0b1288d6410f5f399fa0771`；bundle：
  `9ef18b6c04a63fd1b3285e69ccf2616f3c22f2558802f01794573e2e07d7afef`。
- direct runtime SHA-256：`d138bbe8c44cb9e6fc43b5a27647bbca016d41e8967af7fbb14ba0dfb6de7917`；raw schema SHA-256：
  `bec9c3c3ad66146f4b8b1b6a3b805ae50caa3a29217eef3575897fc952baa2d3`。
- directional runtime commit：`3d7797b161aeb926577f70828c850f7827a80864`；bundle：
  `668d16476295da77ae8b0f0cd212233a071da6292e247fbba8c1e2e2d381afb6`。
- directional design SHA-256：`e1d22fbd543d26e71916fe80dd7d969965b465e1d2e7f01e2171ecdf5b7751ec`；config SHA-256：
  `4ad0c5531fd3f6c464a39548af8b0f3902a2f52313982b58b6a58d653becee55`。
- v10 manifest SHA-256：`61498f2f8580eab7dda59df0e2dba9bf5700c168e33f41bfec5cbdf3bd5041a4`；qualification manifest SHA-256：
  `40c389c1f17704281b3e8e4adced6d000125ca720b4e993e9a3126a6d5d8e230`。

正式 finalizer 从空目标重建 v10 与 qualification；相对上一轮只改变各自的 design lock、generation config、manifest 与 release identity，
candidates、pairs、coverage、review 和 qualification set 字节未变。随后在独立临时目录再次生成，两个完整 release 逐字节一致；临时目录已清理。

## 验证与边界

- formal decode direct-dependency 漂移 focused：`2/2`；qualification：`7/7`。
- qualification/directional/successor：`34/34`；旧 contract/training-data/identity/v7：`43/43`；合计 `77/77`。
- Ruff format 与 `F,E9`、`git diff --check` 通过。
- accepted v2、v8/v9、五头标签、margin、loss、gate、pair 语义、数据正文和既有 review 均未修改；未读取 v9 test、旧 unseen 或 qualification
  sealed 正文。没有运行真实模型、GPU、Docker、付费 API、产品动作、合并或推送。

本轮没有新增 ignored namespace。继续保留物理根 `eval-data/publication-critic/plan098/` 约 `1.8M`，用于既有 commissioning、方向性整改、
模块交接和封存资格生成；最终复验前应保留，通过后可按用户需要清理。工作包三继续锁定。
