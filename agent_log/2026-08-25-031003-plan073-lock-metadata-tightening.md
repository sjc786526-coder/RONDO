# Plan 073 selection lock 元数据窄修

日期：2026-08-25

终验记录的一项非阻塞维护项经用户要求完成窄修：报告加载 selection lock 时，除既有的结果摘要、freeze、候选、工件、threshold 数值与 runtime 绑定外，现在也要求 `run_id`、`runner_up`、`reasons` 和 threshold `method` 与已验证的 validation result 完全一致。

直接扩展既有 lock/report 绑定用例，覆盖正常 lock 和四类结构合法但元数据不一致的 lock；没有增加设施或测试数量。`SelectionLockTest` 7 项通过，`git diff --check` 通过。

未改动或重跑正式 release、result、tracked report、模型、Opus、Cargo、Docker、服务或 unseen campaign；Plan 073 的可信 `NO-GO` 终态不变。
