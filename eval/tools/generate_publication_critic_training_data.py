#!/usr/bin/env python3
"""Author deterministic Plan 059 rehearsal and formal teacher records.

The text in this file is authored by the Plan 059 GPT-5.6-sol generator.  The
script only validates and serializes that authored content; it does not call a
model, API, product runtime, or training backend.
"""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data import (  # noqa: E402
    validate_packet_row,
    validate_pair_row,
    validate_scenario_row,
    validate_supervision_row,
)
from rondo_eval.publication_critic.identity import sha256_file  # noqa: E402


LOCK_PATH = REPO_ROOT / "eval/templates/publication-critic/training-data-design-lock-v2.json"
GENERATOR_PROMPT_PATH = (
    REPO_ROOT / "eval/templates/publication-critic/training-data-generator-prompt-v2.md"
)

QUALIFICATION = {
    "packet_schema": {"name": "rondo-publication-packet", "revision": "v1"},
    "rubric": {"name": "rondo-publication-qualification", "revision": "v1"},
}
EVIDENCE_V1 = {
    "semantic_entailment": "not_evaluated",
    "candidate_window": "not_frozen_before_commit",
}
ANCHOR_C01 = "plan050-c01-public-completed-collaboration"
ANCHOR_C03 = "plan050-c03-public-incomplete-collaboration"
SYNTHETIC_SOURCE = "plan059-synthetic-product-shaped-v1"


@dataclass(frozen=True)
class BoundarySpec:
    scenario_id: str
    hard_focus: str
    target_kind: str
    completion_state: str
    actor_role: str
    title: str
    concrete_state: str
    next_step: str | None
    prior_summary: str
    style: str
    unicode: bool = False
    continuity_variant: str = "available_current"
    evidence_variant: str = "none"
    long_input: bool = False
    within_pass: bool = False
    source_id: str = SYNTHETIC_SOURCE
    uncertainty_claim: str | None = None


BOUNDARY_SPECS = (
    BoundarySpec(
        "b-useful-01",
        "useful_state_transfer",
        "new_event",
        "completed",
        "member",
        "C01 协作回传状态",
        "C01 两侧任务均完成；RONDO 侧观察到成员回传，但没有观察到该协作形成操作性影响链。",
        None,
        "该案例尚未形成公开状态。",
        "formal",
        source_id=ANCHOR_C01,
        within_pass=True,
    ),
    BoundarySpec(
        "b-useful-02",
        "useful_state_transfer",
        "new_event",
        "incomplete",
        "root",
        "Windows 路径归一化仍有缺口",
        "普通盘符路径已通过；带尾随空格的 UNC 路径仍在前缀归一化后被拒，事项未完成。",
        "从 UNC 前缀归一化分支继续，先固定尾随空格用例。",
        "该事项首次公开。",
        "conversational",
        unicode=True,
    ),
    BoundarySpec(
        "b-useful-03",
        "useful_state_transfer",
        "new_event",
        "completed",
        "root",
        "缓存键在 reload 后读取旧值",
        "缓存键已改为包含配置 revision；三次 reload 定向用例都读取新值，事项已完成。",
        None,
        "已稳定复现 reload 后读取旧缓存键，键构造尚未修改。",
        "formal",
        continuity_variant="not_applicable",
        evidence_variant="none",
    ),
    BoundarySpec(
        "b-useful-04",
        "useful_state_transfer",
        "existing_event",
        "incomplete",
        "member",
        "批量归档偶发漏写尾记录",
        "单文件归档稳定；并发批次只在队列关闭与 flush 重叠时漏写最后一条，根因尚未定位。",
        "从队列关闭与 flush 的竞态窗口继续，保留单文件对照。",
        "已确认漏写只出现在批量路径，尚未缩小到具体阶段。",
        "conversational",
        continuity_variant="available_partial",
        evidence_variant="present_omitted",
    ),
    BoundarySpec(
        "b-useful-05",
        "useful_state_transfer",
        "new_event",
        "completed",
        "member",
        "配置热加载重复注册监听器",
        "重复注册来自 reload 分支未释放旧句柄；释放后监听器计数保持为一，回归用例通过。",
        None,
        "该事项首次公开。",
        "formal",
    ),
    BoundarySpec(
        "b-useful-06",
        "useful_state_transfer",
        "existing_event",
        "incomplete",
        "root",
        "索引恢复在空分片上停住",
        "非空分片恢复通过；空分片仍等待不存在的首条记录，尚未验证跳过等待是否安全。",
        "验证空分片直接完成的状态迁移，并复跑混合分片恢复。",
        "恢复流程已越过元数据加载，卡在首条记录等待。",
        "conversational",
        unicode=True,
        continuity_variant="unavailable_stale",
        within_pass=True,
    ),
    BoundarySpec(
        "b-honest-01",
        "honest_uncertainty",
        "new_event",
        "incomplete",
        "member",
        "消息泵每十分钟出现一次尖峰",
        "采样只显示尖峰与定时清理同时发生；目前只能怀疑锁竞争，根因仍未验证。",
        "单独关闭定时清理后复测，并记录锁等待分布。",
        "该事项首次公开。",
        "formal",
        uncertainty_claim="锁竞争",
    ),
    BoundarySpec(
        "b-honest-02",
        "honest_uncertainty",
        "existing_event",
        "incomplete",
        "root",
        "macOS 关闭时偶发遗留 socket",
        "现有日志只显示关闭回调未完成；析构顺序可能相关，但还没有直接验证。",
        "加入析构阶段标记并复现一次完整关闭序列。",
        "已排除正常退出路径，异常只在快速关闭时出现。",
        "conversational",
        unicode=True,
        continuity_variant="available_current",
        evidence_variant="none",
        within_pass=True,
        uncertainty_claim="析构顺序错误",
    ),
    BoundarySpec(
        "b-honest-03",
        "honest_uncertainty",
        "new_event",
        "completed",
        "root",
        "临时目录容量报警",
        "清理旧任务产物后容量恢复；报警由单次缓存增长触发，下载缓存泄漏只是未验证的猜测。",
        None,
        "该事项首次公开。",
        "formal",
        uncertainty_claim="下载缓存泄漏",
    ),
    BoundarySpec(
        "b-honest-04",
        "honest_uncertainty",
        "existing_event",
        "completed",
        "member",
        "Unicode 标题排序漂移",
        "改用 NFKC 后冻结样本顺序稳定；旧漂移可能来自组合字符比较器缺陷，但未保存足以确认根因的输入。",
        None,
        "排序在 café 与 cafe\u0301 混合输入时不稳定，尚未归因。",
        "conversational",
        unicode=True,
        continuity_variant="available_partial",
        evidence_variant="present_omitted",
        long_input=True,
        uncertainty_claim="组合字符比较器缺陷",
    ),
    BoundarySpec(
        "b-honest-05",
        "honest_uncertainty",
        "new_event",
        "incomplete",
        "member",
        "重试后首包延迟升高",
        "两次本地样本都在重试后首包变慢；样本不足以判断是连接复用还是服务端排队。",
        "增加不重试对照并分别记录连接建立与首字节耗时。",
        "该事项首次公开。",
        "formal",
        uncertainty_claim="连接复用失效",
    ),
    BoundarySpec(
        "b-honest-06",
        "honest_uncertainty",
        "existing_event",
        "completed",
        "root",
        "增量解析器遗漏末尾换行",
        "已改为保留跨块 CR，分块矩阵通过；旧遗漏可能来自缓冲拼接，但根因仍未验证。",
        None,
        "已把问题缩小到跨块换行，单块输入稳定。",
        "conversational",
        continuity_variant="unavailable_unknown",
        uncertainty_claim="缓冲拼接错误",
    ),
    BoundarySpec(
        "b-continuity-01",
        "conditional_continuity",
        "existing_event",
        "incomplete",
        "root",
        "C03 ELF 提取仍未通过 verifier",
        "成员结果已回传，协作与影响链均被观察到；外部 verifier 仍失败，事项未完成。",
        "从 verifier 的失败条件继续定位，不重复验证成员回传链。",
        "C03 已形成成员回传与 Team State 更新，但任务终态尚未成功。",
        "formal",
        continuity_variant="available_current",
        evidence_variant="present",
        source_id=ANCHOR_C03,
    ),
    BoundarySpec(
        "b-continuity-02",
        "conditional_continuity",
        "new_event",
        "incomplete",
        "member",
        "分页游标在空页后重复",
        "空页之后会再次返回前一游标；普通非空分页保持正确，事项未完成。",
        "从空页分支的 next_cursor 赋值继续，保留非空分页对照。",
        "该事项首次公开。",
        "conversational",
    ),
    BoundarySpec(
        "b-continuity-03",
        "conditional_continuity",
        "existing_event",
        "incomplete",
        "member",
        "Windows 子进程取消仍有孤儿进程",
        "父进程已响应取消，但孙进程仍存活；job object 继承尚未接入。",
        "先把孙进程加入同一 job object，再验证超时与显式取消。",
        "当前只回收了直接子进程，孙进程未纳入同一生命周期。",
        "formal",
        continuity_variant="available_stale",
        evidence_variant="present_omitted",
        within_pass=True,
    ),
    BoundarySpec(
        "b-continuity-04",
        "conditional_continuity",
        "new_event",
        "incomplete",
        "root",
        "配置迁移缺少回滚覆盖",
        "正向迁移已通过；重复索引场景的回滚仍失败，事项未完成。",
        "从回滚索引清理继续，无需重跑已通过的正向迁移。",
        "该事项首次公开。",
        "conversational",
        unicode=True,
    ),
    BoundarySpec(
        "b-continuity-05",
        "conditional_continuity",
        "existing_event",
        "incomplete",
        "root",
        "长任务恢复点未覆盖空输出",
        "有输出的恢复点验证通过；空输出时 checkpoint 尚未落盘。",
        "补空输出 checkpoint 用例，然后验证恢复不会重复执行已完成步骤。",
        "恢复路径已覆盖正常输出，空输出仍没有样本。",
        "formal",
        continuity_variant="available_partial",
        evidence_variant="none",
    ),
    BoundarySpec(
        "b-continuity-06",
        "conditional_continuity",
        "new_event",
        "incomplete",
        "member",
        "多语言错误消息缺少西班牙语",
        "英文与中文资源已加载；西班牙语仍回退到英文，资源键映射尚未补齐。",
        "补齐 es-ES 键映射并跑三语言回退用例。",
        "该事项首次公开。",
        "conversational",
        unicode=True,
    ),
    BoundarySpec(
        "b-scope-01",
        "scope_and_signal",
        "new_event",
        "completed",
        "root",
        "JSON 导出字段顺序不稳定",
        "导出器改为按 schema 字段顺序写入；三种输入顺序得到相同结果，事项已完成。",
        None,
        "该事项首次公开。",
        "formal",
        long_input=True,
    ),
    BoundarySpec(
        "b-scope-02",
        "scope_and_signal",
        "existing_event",
        "incomplete",
        "member",
        "搜索预算在符号链接环中耗尽",
        "普通目录预算稳定；符号链接环会重复计入目录，修复尚未验证。",
        "先按 inode 去重目录，再复跑环与普通目录用例。",
        "搜索上限已经生效，但环路径仍过早耗尽预算。",
        "conversational",
        continuity_variant="available_current",
        evidence_variant="present",
    ),
    BoundarySpec(
        "b-scope-03",
        "scope_and_signal",
        "new_event",
        "incomplete",
        "member",
        "日志轮换后首条记录丢失",
        "只在轮换与写入同毫秒发生时丢首条记录，常规写入稳定。",
        "固定轮换边界时钟并检查文件句柄交换顺序。",
        "该事项首次公开。",
        "formal",
    ),
    BoundarySpec(
        "b-scope-04",
        "scope_and_signal",
        "existing_event",
        "completed",
        "root",
        "状态面板重复显示已关闭事件",
        "活动谓词已统一使用双生命周期；关闭但仍待 Root 处理的事件只显示一次，回归通过。",
        None,
        "面板分别按 producer 与 Root 状态拼接，导致同一事件重复。",
        "conversational",
        unicode=True,
        continuity_variant="available_stale",
        evidence_variant="none",
        within_pass=True,
    ),
    BoundarySpec(
        "b-scope-05",
        "scope_and_signal",
        "new_event",
        "completed",
        "member",
        "CLI 帮助中的默认端口过期",
        "帮助文本已与配置默认值统一为 4317，快照测试通过。",
        None,
        "该事项首次公开。",
        "formal",
    ),
    BoundarySpec(
        "b-scope-06",
        "scope_and_signal",
        "existing_event",
        "incomplete",
        "root",
        "大目录扫描的取消响应慢",
        "取消只在每个目录结束后检查；单个大目录可延迟数秒，尚未调整。",
        "把取消检查移到每批条目后，并测量一万文件目录。",
        "已确认取消标志能传播，但检查粒度过粗。",
        "conversational",
        continuity_variant="unavailable_unknown",
    ),
    BoundarySpec(
        "b-consistency-01",
        "internal_consistency",
        "new_event",
        "completed",
        "member",
        "临时文件清理遗漏锁文件",
        "清理器现在同时删除任务创建的锁文件；定向用例通过，事项已完成。",
        None,
        "该事项首次公开。",
        "formal",
    ),
    BoundarySpec(
        "b-consistency-02",
        "internal_consistency",
        "new_event",
        "incomplete",
        "root",
        "HTTP 重定向丢失查询参数",
        "单次重定向已保留查询参数；多跳重定向仍在第二跳丢失，事项未完成。",
        "从第二跳 URL 合并继续，并保留单跳对照。",
        "该事项首次公开。",
        "conversational",
    ),
    BoundarySpec(
        "b-consistency-03",
        "internal_consistency",
        "existing_event",
        "completed",
        "root",
        "重放去重键未包含团队实例",
        "去重键已加入团队实例 ID；跨实例不再误命中，同实例重放保持稳定，事项已完成。",
        None,
        "跨团队实例的同 request ID 会错误返回旧 committed outcome。",
        "formal",
        continuity_variant="available_current",
        evidence_variant="present_omitted",
    ),
    BoundarySpec(
        "b-consistency-04",
        "internal_consistency",
        "existing_event",
        "incomplete",
        "member",
        "增量索引在删除后计数偏大",
        "新增路径计数正确；删除路径仍保留一个陈旧条目，事项未完成。",
        "从删除通知到索引提交之间的去重分支继续。",
        "计数偏大已缩小到删除通知，新增路径没有复现。",
        "conversational",
        unicode=True,
        continuity_variant="available_partial",
        evidence_variant="none",
    ),
    BoundarySpec(
        "b-consistency-05",
        "internal_consistency",
        "new_event",
        "completed",
        "root",
        "YAML 空文档被当作缺失文件",
        "空文档现在解析为显式空配置；缺失文件仍返回 not found，回归通过。",
        None,
        "该事项首次公开。",
        "formal",
        within_pass=True,
    ),
    BoundarySpec(
        "b-consistency-06",
        "internal_consistency",
        "existing_event",
        "incomplete",
        "member",
        "批处理错误摘要遗漏首个失败项",
        "失败计数已正确；摘要仍从第二个失败项开始，首项缺失，事项未完成。",
        "检查首项初始化与后续追加的分支差异。",
        "批处理能返回失败总数，但摘要内容不完整。",
        "conversational",
        continuity_variant="available_stale",
        evidence_variant="present",
        long_input=True,
    ),
)


NEGATIVE_CANDIDATES: dict[str, tuple[str, str | None]] = {
    "b-useful-01": ("处理已经结束，相关状态已经更新。", None),
    "b-useful-02": ("部分路径有进展，剩余问题还需后续处理。", "从 UNC 前缀归一化分支继续，先固定尾随空格用例。"),
    "b-useful-03": ("问题已经解决，结果已经记录。", None),
    "b-useful-04": ("批量路径仍在排查，暂时没有收口。", "从队列关闭与 flush 的竞态窗口继续，保留单文件对照。"),
    "b-useful-05": ("监听器问题处理完毕。", None),
    "b-useful-06": ("恢复流程还有缺口，需要接着处理。", "验证空分片直接完成的状态迁移，并复跑混合分片恢复。"),
    "b-honest-01": (
        "采样只显示尖峰与定时清理同时发生；锁竞争这一解释现已被断言为确定结论，任务依旧没有收口。",
        "单独关闭定时清理后复测，并记录锁等待分布。",
    ),
    "b-honest-02": (
        "现有日志只显示关闭回调未完成；这些记录被当成析构顺序错误的确证，关闭问题依然待处理。",
        "加入析构阶段标记并复现一次完整关闭序列。",
    ),
    "b-honest-03": (
        "清理旧任务产物后容量恢复；报警由单次缓存增长触发，下载缓存泄漏被当作已经证实的原因；清理任务结束。",
        None,
    ),
    "b-honest-04": (
        "改用 NFKC 后冻结样本顺序稳定；组合字符比较器缺陷被写成已经证实的旧漂移原因；修复任务收口。",
        None,
    ),
    "b-honest-05": (
        "两次本地样本都在重试后首包变慢；连接复用失效被认定为延迟来源，后续工作还没有收口。",
        "增加不重试对照并分别记录连接建立与首字节耗时。",
    ),
    "b-honest-06": (
        "已改为保留跨块 CR，分块矩阵通过；缓冲拼接错误被直接认定为旧遗漏来源，处理已经结束。",
        None,
    ),
    "b-continuity-01": ("成员结果已回传，协作与影响链均被观察到；外部 verifier 仍失败，事项未完成。", "继续定位剩余问题。"),
    "b-continuity-02": ("空页之后会再次返回前一游标；普通非空分页保持正确，事项未完成。", "后续再处理。"),
    "b-continuity-03": ("父进程已响应取消，但孙进程仍存活；job object 继承尚未接入。", "按现状继续。"),
    "b-continuity-04": ("正向迁移已通过；重复索引场景的回滚仍失败，事项未完成。", "跟进失败路径。"),
    "b-continuity-05": ("有输出的恢复点验证通过；空输出时 checkpoint 尚未落盘。", "再做一次验证。"),
    "b-continuity-06": ("英文与中文资源已加载；西班牙语仍回退到英文，资源键映射尚未补齐。", "以后完善。"),
    "b-scope-01": (
        " ".join(
            f"界面操作记录 {index}：调整面板宽度，翻看配色选项，记录滚动位置，再等待一次无关刷新。"
            for index in range(1, 9)
        )
        + " 最终结论：导出器改为按 schema 字段顺序写入；三种输入顺序得到相同结果，事项已完成。",
        None,
    ),
    "b-scope-02": (
        "排查时反复调整终端主题并记录滚动位置。普通目录预算稳定；符号链接环会重复计入目录，修复尚未验证。",
        "先按 inode 去重目录，再复跑环与普通目录用例。",
    ),
    "b-scope-03": (
        "过程中整理了窗口排列、文件颜色和命令历史。只在轮换与写入同毫秒发生时丢首条记录，常规写入稳定。",
        "固定轮换边界时钟并检查文件句柄交换顺序。",
    ),
    "b-scope-04": (
        "先花时间核对编辑器布局与无关目录列表。活动谓词已统一使用双生命周期；关闭但仍待 Root 处理的事件只显示一次，回归通过。",
        None,
    ),
    "b-scope-05": (
        "执行时多次切换标签页并抄录等待时长。帮助文本已与配置默认值统一为 4317，快照测试通过。",
        None,
    ),
    "b-scope-06": (
        "检查期间记下终端尺寸和每次光标移动。取消只在每个目录结束后检查；单个大目录可延迟数秒，尚未调整。",
        "把取消检查移到每批条目后，并测量一万文件目录。",
    ),
    "b-consistency-01": (
        "清理器现在同时删除任务创建的锁文件；定向用例通过，事项已完成。",
        "锁文件已经清除，但任务仍未完成，需要继续查同一故障。",
    ),
    "b-consistency-02": (
        "单次重定向已保留查询参数；多跳重定向仍在第二跳丢失，事项未完成。同时该多跳问题也已经全部解决。",
        "从第二跳 URL 合并继续，并保留单跳对照。",
    ),
    "b-consistency-03": (
        "去重键已加入团队实例 ID；跨实例不再误命中，同实例重放保持稳定，事项已完成。",
        "去重修复虽已完成，后续仍要把这个未完成故障继续定位。",
    ),
    "b-consistency-04": (
        "新增路径计数正确；删除路径仍保留一个陈旧条目，事项未完成。但删除路径事项又被表述为已经完成。",
        "从删除通知到索引提交之间的去重分支继续。",
    ),
    "b-consistency-05": (
        "空文档现在解析为显式空配置；缺失文件仍返回 not found，回归通过。",
        "该回归已经通过，不过同一事项尚未完成，还要继续调查。",
    ),
    "b-consistency-06": (
        "失败计数已正确；摘要仍从第二个失败项开始，首项缺失，事项未完成。同一摘要问题同时也宣称已经收口。",
        "检查首项初始化与后续追加的分支差异。",
    ),
}


SOFT_CANDIDATES: dict[str, tuple[str, str | None]] = {
    "b-useful-01": (
        "C01 两侧任务均完成；RONDO 侧观察到成员回传，但没有观察到该协作形成操作性影响链。补充边界：这里没有声称协作带来操作性影响。",
        None,
    ),
    "b-useful-06": (
        "非空分片恢复通过；空分片仍等待不存在的首条记录，尚未验证跳过等待是否安全。接续范围仍限空分片状态迁移和混合分片复跑。",
        "验证空分片直接完成的状态迁移，并复跑混合分片恢复。",
    ),
    "b-honest-02": (
        "现有日志只显示关闭回调未完成；析构顺序可能相关，但还没有直接验证。现阶段不外推到其他关闭路径。",
        "加入析构阶段标记并复现一次完整关闭序列。",
    ),
    "b-continuity-03": (
        "父进程已响应取消，但孙进程仍存活；job object 继承尚未接入。后续仍只处理孙进程继承和取消验证。",
        "先把孙进程加入同一 job object，再验证超时与显式取消。",
    ),
    "b-scope-04": (
        "活动谓词已统一使用双生命周期；关闭但仍待 Root 处理的事件只显示一次，回归通过。这里不延伸到其他事件筛选策略。",
        None,
    ),
    "b-consistency-05": (
        "空文档现在解析为显式空配置；缺失文件仍返回 not found，回归通过。结论只覆盖空文档与缺失文件的区分。",
        None,
    ),
}


MIXED_SPECS = (
    {
        "scenario_id": "mixed-01",
        "target_kind": "existing_event",
        "completion_state": "incomplete",
        "actor_role": "root",
        "title": "RPC 取消后偶发保留队列项",
        "summary": "取消信号已到达 worker，但一个队列项仍待清理；只在高并发下复现，根因未知。",
        "handoff": "固定并发为 16 后跟踪队列项从取消到回收的状态迁移。",
        "label": "PASS",
        "defects": [],
        "prior_summary": "低并发取消路径已通过，高并发尚未复现稳定。",
        "style": "formal",
        "unicode": False,
        "continuity_variant": "available_current",
        "evidence_variant": "present_omitted",
    },
    {
        "scenario_id": "mixed-02",
        "target_kind": "new_event",
        "completion_state": "completed",
        "actor_role": "member",
        "title": "日文文件名の归档顺序",
        "summary": "归档前改为按 NFKC 后的稳定键排序；日文与组合字符样本顺序一致，事项已完成。",
        "handoff": None,
        "label": "PASS",
        "defects": [],
        "prior_summary": "该事项首次公开。",
        "style": "conversational",
        "unicode": True,
        "continuity_variant": "not_applicable",
        "evidence_variant": "none",
    },
    {
        "scenario_id": "mixed-03",
        "target_kind": "existing_event",
        "completion_state": "completed",
        "actor_role": "member",
        "title": "连接池关闭后仍接受借用",
        "summary": "关闭状态现在拒绝新借用，已借连接可归还；并发关闭回归通过。",
        "handoff": None,
        "label": "PASS",
        "defects": [],
        "prior_summary": "关闭后仍可借出连接，竞争窗口已经复现。",
        "style": "formal",
        "unicode": False,
        "continuity_variant": "unavailable_stale",
        "evidence_variant": "none",
    },
    {
        "scenario_id": "mixed-04",
        "target_kind": "new_event",
        "completion_state": "incomplete",
        "actor_role": "root",
        "title": "压缩流在尾块校验失败",
        "summary": "看了很多文件，也试了几个参数，应该已经确认是第三方库的问题。",
        "handoff": "继续看看。",
        "label": "REWRITE",
        "defects": ["useful_state_transfer", "honest_uncertainty", "conditional_continuity"],
        "prior_summary": "该事项首次公开。",
        "style": "conversational",
        "unicode": False,
        "continuity_variant": "not_applicable",
        "evidence_variant": "none",
    },
    {
        "scenario_id": "mixed-05",
        "target_kind": "existing_event",
        "completion_state": "completed",
        "actor_role": "root",
        "title": "旧 schema 字段兼容读取",
        "summary": "旧字段读取与新字段迁移都通过，事项已完成；期间依次打开了编辑器、搜索了目录、调整了终端颜色并记录了午间构建耗时。",
        "handoff": "继续修复仍然失败的旧字段读取。",
        "label": "REWRITE",
        "defects": ["scope_and_signal", "internal_consistency"],
        "prior_summary": "旧字段读取失败，新字段路径正常。",
        "style": "formal",
        "unicode": False,
        "continuity_variant": "available_stale",
        "evidence_variant": "present",
    },
    {
        "scenario_id": "mixed-06",
        "target_kind": "existing_event",
        "completion_state": "incomplete",
        "actor_role": "member",
        "title": "emoji 标题触发宽度偏差 🧭",
        "summary": "界面还有一点问题，已经差不多好了。",
        "handoff": None,
        "label": "REWRITE",
        "defects": ["useful_state_transfer", "conditional_continuity"],
        "prior_summary": "宽度偏差在 emoji 与东亚宽字符混排时复现。",
        "style": "conversational",
        "unicode": True,
        "continuity_variant": "available_partial",
        "evidence_variant": "present_omitted",
    },
)


REHEARSAL_BOUNDARY_IDS = {
    "b-useful-01",
    "b-honest-01",
    "b-continuity-01",
    "b-scope-01",
    "b-consistency-01",
}


def _publication_class(target_kind: str, completion_state: str) -> str:
    return f"{target_kind}_{completion_state}"


def _fact_references(variant: str) -> dict[str, Any]:
    if variant == "none":
        return {"state": "none"}
    if variant == "present":
        return {"state": "present", "visible_count": 2, "count_omitted": False}
    if variant == "present_omitted":
        return {"state": "present", "visible_count": 3, "count_omitted": True}
    raise ValueError(f"unknown evidence variant: {variant}")


def _long_prior(seed: str, index: int) -> str:
    clauses = [
        f"{seed} 的公开检查点 {index} 保留了输入边界、已验证路径和仍未知条件",
        "记录只描述本事项，不包含工具正文、Fact 标识或私有推理",
        "重复执行保持同一公开状态，未把推测提升为事实",
        "下一步仍以当前公开边界为起点",
    ]
    return "；".join(clauses * 7) + "。"


def _continuity(
    target_kind: str,
    variant: str,
    prior_summary: str,
    evidence_variant: str,
    *,
    long_input: bool,
    scenario_id: str,
) -> dict[str, Any]:
    if target_kind == "new_event":
        return {"state": "not_applicable"}
    if variant.startswith("unavailable"):
        freshness = "known_stale" if variant == "unavailable_stale" else "unknown"
        return {"state": "unavailable", "last_known_revision": 40, "freshness": freshness}
    freshness = {
        "available_current": "current",
        "available_stale": "known_stale",
        "available_partial": "unknown",
    }[variant]
    coverage: dict[str, Any]
    if variant == "available_partial":
        coverage = {"state": "partial", "omitted_count": 2}
    else:
        coverage = {"state": "complete"}
    summaries = [prior_summary]
    if long_input:
        summaries = [_long_prior(scenario_id, index) for index in range(1, 5)]
    prior_publications = [
        {
            "summary": summary,
            "handoff": None if index % 2 else "沿该公开检查点继续，不重查已经稳定的对照。",
            "evidence": {
                "fact_references": _fact_references(evidence_variant),
                "observation_availability": "unknown",
            },
        }
        for index, summary in enumerate(summaries, start=1)
    ]
    return {
        "state": "available",
        "source_team_revision": 100 + sum(ord(character) for character in scenario_id) % 500,
        "freshness": freshness,
        "coverage": coverage,
        "prior_publications": prior_publications,
    }


def _packet(
    spec: BoundarySpec,
    summary: str,
    handoff: str | None,
) -> dict[str, Any]:
    return {
        "qualification": QUALIFICATION,
        "actor_role": spec.actor_role,
        "target_kind": spec.target_kind,
        "local_scope": {"title": spec.title},
        "candidate": {"summary": summary, "handoff": handoff},
        "continuity": _continuity(
            spec.target_kind,
            spec.continuity_variant,
            spec.prior_summary,
            spec.evidence_variant,
            long_input=spec.long_input,
            scenario_id=spec.scenario_id,
        ),
        "evidence_v1": EVIDENCE_V1,
    }


def _boundary_candidates(spec: BoundarySpec) -> tuple[tuple[str, str | None], tuple[str, str | None]]:
    positive = (spec.concrete_state, spec.next_step)
    try:
        negative = NEGATIVE_CANDIDATES[spec.scenario_id]
    except KeyError as exc:
        raise ValueError(f"missing explicitly authored Q-: {spec.scenario_id}") from exc
    return positive, negative


def _generator_identity(args: argparse.Namespace) -> dict[str, str]:
    return {
        "model": "gpt-5.6-sol",
        "reasoning_effort": args.reasoning_effort,
        "role": "direct_plan059_generator",
        "prompt_sha256": sha256_file(GENERATOR_PROMPT_PATH),
        "date": "2026-08-23",
        "session_identity": args.session_identity,
    }


def _source_group(source_id: str, scenario_id: str) -> str:
    if source_id != SYNTHETIC_SOURCE:
        return source_id
    return f"{SYNTHETIC_SOURCE}:{scenario_id}"


def _base_supervision(
    *,
    candidate_id: str,
    scenario_id: str,
    source_group: str,
    binary_label: str,
    publication_class: str,
    completion_state: str,
    hard_focus: str | None,
    defects: list[str],
    slices: list[str],
    actor_role: str,
    style: str,
    length_bucket: str,
    unicode: bool,
    generator_identity: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "scenario_id": scenario_id,
        "source_group": source_group,
        "scenario_group": scenario_id,
        "template_group": scenario_id,
        "proposed_split": None,
        "binary_label": binary_label,
        "publication_class": publication_class,
        "completion_state": completion_state,
        "hard_focus": hard_focus,
        "defects": defects,
        "slices": slices,
        "actor_role": actor_role,
        "style": style,
        "length_bucket": length_bucket,
        "unicode": unicode,
        "generator_identity": generator_identity,
        "reviewer_identity": None,
        "review_status": "pending",
    }


def _boundary_records(
    spec: BoundarySpec,
    generator_identity: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    positive, negative = _boundary_candidates(spec)
    publication_class = _publication_class(spec.target_kind, spec.completion_state)
    candidate_specs: list[tuple[str, str, str | None, str, list[str], str]] = [
        ("qplus", positive[0], positive[1], "PASS", [], "preferred"),
        ("qminus", negative[0], negative[1], "REWRITE", [spec.hard_focus], "dispreferred"),
    ]
    if spec.within_pass:
        try:
            soft_summary, soft_handoff = SOFT_CANDIDATES[spec.scenario_id]
        except KeyError as exc:
            raise ValueError(f"missing explicitly authored Within-PASS endpoint: {spec.scenario_id}") from exc
        candidate_specs.append(
            ("pass-soft", soft_summary, soft_handoff, "PASS", [], "soft_dispreferred")
        )

    packets: list[dict[str, Any]] = []
    supervision: list[dict[str, Any]] = []
    continuity_state = (
        "not_applicable"
        if spec.target_kind == "new_event"
        else "unavailable"
        if spec.continuity_variant.startswith("unavailable")
        else "available"
    )
    evidence_appearance = (
        "not_applicable" if continuity_state != "available" else spec.evidence_variant
    )
    base_slices = [
        spec.hard_focus,
        publication_class,
        f"continuity_{continuity_state}",
    ]
    if spec.hard_focus == "conditional_continuity":
        base_slices.append("threshold_near_handoff")
    if spec.target_kind == "new_event" and spec.completion_state == "completed":
        if spec.hard_focus == "useful_state_transfer":
            base_slices.append("new_completed_useful_state")
        if spec.hard_focus == "scope_and_signal":
            base_slices.append("new_completed_scope_signal")
    if "stale" in spec.continuity_variant:
        base_slices.append("freshness_known_stale")
    if evidence_appearance == "not_applicable":
        base_slices.append("evidence_not_applicable")
    elif evidence_appearance == "none":
        base_slices.append("evidence_none")
    else:
        base_slices.append("evidence_present")
        if evidence_appearance == "present_omitted":
            base_slices.append("evidence_count_omitted")
    if spec.unicode:
        base_slices.append("unicode")
    for suffix, summary, handoff, label, defects, _direction in candidate_specs:
        candidate_id = f"pc059-{spec.scenario_id}-{suffix}"
        packet = _packet(spec, summary, handoff)
        slices = list(base_slices)
        shared_long_context = (
            spec.long_input
            and spec.target_kind == "existing_event"
            and spec.continuity_variant.startswith("available")
        )
        candidate_is_long = shared_long_context or (
            spec.long_input and spec.hard_focus == "scope_and_signal" and suffix == "qminus"
        )
        if candidate_is_long:
            slices.append("long_input")
        if label == "REWRITE" and spec.hard_focus == "internal_consistency":
            slices.append("internal_consistency_rewrite")
        packets.append({"schema_version": 1, "candidate_id": candidate_id, "packet": packet})
        supervision.append(
            _base_supervision(
                candidate_id=candidate_id,
                scenario_id=spec.scenario_id,
                source_group=_source_group(spec.source_id, spec.scenario_id),
                binary_label=label,
                publication_class=publication_class,
                completion_state=spec.completion_state,
                hard_focus=spec.hard_focus,
                defects=defects,
                slices=slices,
                actor_role=spec.actor_role,
                style=spec.style,
                length_bucket="long" if candidate_is_long else "medium",
                unicode=spec.unicode,
                generator_identity=generator_identity,
            )
        )

    pairs = [
        {
            "schema_version": 1,
            "pair_id": f"pair-{spec.scenario_id}-boundary",
            "kind": "boundary",
            "scenario_id": spec.scenario_id,
            "preferred_candidate_id": f"pc059-{spec.scenario_id}-qplus",
            "dispreferred_candidate_id": f"pc059-{spec.scenario_id}-qminus",
            "target_dimension": spec.hard_focus,
            "soft_preference": None,
            "review_status": "pending",
        }
    ]
    if spec.within_pass:
        pairs.append(
            {
                "schema_version": 1,
                "pair_id": f"pair-{spec.scenario_id}-within-pass",
                "kind": "within_pass",
                "scenario_id": spec.scenario_id,
                "preferred_candidate_id": f"pc059-{spec.scenario_id}-qplus",
                "dispreferred_candidate_id": f"pc059-{spec.scenario_id}-pass-soft",
                "target_dimension": None,
                "soft_preference": "directness_and_lower_repetition",
                "review_status": "pending",
            }
        )
    scenario_slices = list(base_slices)
    if spec.long_input:
        scenario_slices.append("contains_long_candidate")
    scenario = {
        "schema_version": 1,
        "scenario_id": spec.scenario_id,
        "source_id": spec.source_id,
        "source_group": _source_group(spec.source_id, spec.scenario_id),
        "scenario_group": spec.scenario_id,
        "template_group": spec.scenario_id,
        "publication_class": publication_class,
        "completion_state": spec.completion_state,
        "actor_role": spec.actor_role,
        "style": spec.style,
        "length_bucket": "medium",
        "unicode": spec.unicode,
        "slices": scenario_slices,
        "blueprint": {
            "local_scope_title": spec.title,
            "public_state": spec.concrete_state,
            "continuity_state": continuity_state,
            "evidence_appearance": evidence_appearance,
            "candidate_brief": "表达该公开状态，并保留完成状态与适用接续边界。",
        },
    }
    return packets, supervision, pairs, scenario


def _mixed_record(
    raw: dict[str, Any],
    generator_identity: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    scenario_id = raw["scenario_id"]
    publication_class = _publication_class(raw["target_kind"], raw["completion_state"])
    spec = BoundarySpec(
        scenario_id=scenario_id,
        hard_focus=None,
        target_kind=raw["target_kind"],
        completion_state=raw["completion_state"],
        actor_role=raw["actor_role"],
        title=raw["title"],
        concrete_state=raw["summary"],
        next_step=raw["handoff"],
        prior_summary=raw["prior_summary"],
        style=raw["style"],
        unicode=raw["unicode"],
        continuity_variant=raw["continuity_variant"],
        evidence_variant=raw["evidence_variant"],
    )
    candidate_id = f"pc059-{scenario_id}-binary"
    packet = _packet(spec, raw["summary"], raw["handoff"])
    continuity_state = (
        "not_applicable"
        if raw["target_kind"] == "new_event"
        else "unavailable"
        if raw["continuity_variant"].startswith("unavailable")
        else "available"
    )
    evidence_appearance = (
        "not_applicable" if continuity_state != "available" else raw["evidence_variant"]
    )
    slices = [
        "natural_mixed",
        publication_class,
        f"continuity_{continuity_state}",
    ]
    if "stale" in raw["continuity_variant"]:
        slices.append("freshness_known_stale")
    if evidence_appearance == "not_applicable":
        slices.append("evidence_not_applicable")
    elif evidence_appearance == "none":
        slices.append("evidence_none")
    else:
        slices.append("evidence_present")
        if evidence_appearance == "present_omitted":
            slices.append("evidence_count_omitted")
    if raw["unicode"]:
        slices.append("unicode")
    supervision = _base_supervision(
        candidate_id=candidate_id,
        scenario_id=scenario_id,
        source_group=f"{SYNTHETIC_SOURCE}:{scenario_id}",
        binary_label=raw["label"],
        publication_class=publication_class,
        completion_state=raw["completion_state"],
        hard_focus=None,
        defects=list(raw["defects"]),
        slices=slices,
        actor_role=raw["actor_role"],
        style=raw["style"],
        length_bucket="short",
        unicode=raw["unicode"],
        generator_identity=generator_identity,
    )
    scenario = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "source_id": SYNTHETIC_SOURCE,
        "source_group": _source_group(SYNTHETIC_SOURCE, scenario_id),
        "scenario_group": scenario_id,
        "template_group": scenario_id,
        "publication_class": publication_class,
        "completion_state": raw["completion_state"],
        "actor_role": raw["actor_role"],
        "style": raw["style"],
        "length_bucket": "short",
        "unicode": raw["unicode"],
        "slices": slices,
        "blueprint": {
            "local_scope_title": raw["title"],
            "public_state": raw["summary"],
            "continuity_state": continuity_state,
            "evidence_appearance": evidence_appearance,
            "candidate_brief": "表达该公开状态与适用接续边界。",
        },
    }
    return {"schema_version": 1, "candidate_id": candidate_id, "packet": packet}, supervision, scenario


def _secure_directory(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"refusing symlink directory: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise RuntimeError(f"unsafe output directory: {path}")


def _secure_write(path: Path, content: bytes) -> None:
    if path.exists() and path.is_symlink():
        raise RuntimeError(f"refusing symlink output: {path}")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
    path.chmod(0o600)


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for row in rows
    )


def generate(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    namespace = Path("/home/sjc/desktop/RONDO/eval-data/publication-critic/plan059").resolve()
    if namespace not in output_dir.parents:
        raise RuntimeError("output must be a child of the Plan 059 ignored namespace")
    _secure_directory(namespace)
    _secure_directory(output_dir)

    generator_identity = _generator_identity(args)
    all_boundary_ids = {spec.scenario_id for spec in BOUNDARY_SPECS}
    if set(NEGATIVE_CANDIDATES) != all_boundary_ids:
        raise RuntimeError("explicit Q- authoring registry does not match Boundary scenarios")
    expected_soft_ids = {spec.scenario_id for spec in BOUNDARY_SPECS if spec.within_pass}
    if set(SOFT_CANDIDATES) != expected_soft_ids:
        raise RuntimeError("explicit Within-PASS authoring registry does not match soft scenarios")
    boundary_specs = list(BOUNDARY_SPECS)
    mixed_specs = list(MIXED_SPECS)
    if args.mode == "rehearsal":
        boundary_specs = [spec for spec in boundary_specs if spec.scenario_id in REHEARSAL_BOUNDARY_IDS]
        mixed_specs = [mixed_specs[0]]

    packet_rows: list[dict[str, Any]] = []
    supervision_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    scenario_rows: list[dict[str, Any]] = []
    for spec in boundary_specs:
        packets, supervision, pairs, scenario = _boundary_records(spec, generator_identity)
        packet_rows.extend(packets)
        supervision_rows.extend(supervision)
        pair_rows.extend(pairs)
        scenario_rows.append(scenario)
    for mixed in mixed_specs:
        packet, supervision, scenario = _mixed_record(mixed, generator_identity)
        packet_rows.append(packet)
        supervision_rows.append(supervision)
        scenario_rows.append(scenario)

    allowed_source_ids = {ANCHOR_C01, ANCHOR_C03, SYNTHETIC_SOURCE}
    for row in scenario_rows:
        validate_scenario_row(row, allowed_source_ids=allowed_source_ids)
    candidate_ids: set[str] = set()
    for row in packet_rows:
        candidate_id = row["candidate_id"]
        if candidate_id in candidate_ids:
            raise RuntimeError(f"duplicate candidate_id: {candidate_id}")
        candidate_ids.add(candidate_id)
        validate_packet_row(row, repo_root=REPO_ROOT)
    for row in supervision_rows:
        validate_supervision_row(row, final=False)
    if {row["candidate_id"] for row in supervision_rows} != candidate_ids:
        raise RuntimeError("packet and supervision candidate IDs differ")
    for pair in pair_rows:
        validate_pair_row(pair, final=False)
        if pair["preferred_candidate_id"] not in candidate_ids or pair["dispreferred_candidate_id"] not in candidate_ids:
            raise RuntimeError(f"pair has a dangling endpoint: {pair['pair_id']}")

    expected_count = 12 if args.mode == "rehearsal" else 72
    if len(packet_rows) != expected_count:
        raise RuntimeError(
            f"{args.mode} candidate count drifted: expected {expected_count}, got {len(packet_rows)}"
        )
    for name, rows in (
        ("scenarios.jsonl", scenario_rows),
        ("packets.jsonl", packet_rows),
        ("supervision.jsonl", supervision_rows),
        ("pairs.jsonl", pair_rows),
    ):
        _secure_write(output_dir / name, _jsonl_bytes(rows))

    source_projection = {
        "schema": "rondo-publication-critic-plan059-source-projection-v1",
        "body_free": True,
        "sources": [
            {
                "source_id": ANCHOR_C01,
                "facts": {
                    "case": "C01",
                    "outcome": "completed",
                    "collaboration": "observed",
                    "impact_chain": "not_observed",
                },
            },
            {
                "source_id": ANCHOR_C03,
                "facts": {
                    "case": "C03",
                    "outcome": "task_failed",
                    "collaboration": "observed",
                    "impact_chain": "observed",
                    "member_result_returned": True,
                },
            },
        ],
        "excluded": [
            "transcript",
            "private_reasoning",
            "raw_trace",
            "tool_output",
            "Fact_observation_body",
        ],
    }
    _secure_write(output_dir / "source-projections.json", _json_bytes(source_projection))

    run = {
        "schema": "rondo-publication-critic-plan059-generator-run-v1",
        "run_id": args.run_id,
        "mode": args.mode,
        "generator_identity": generator_identity,
        "data_design_lock_sha256": sha256_file(LOCK_PATH),
        "generator_prompt_sha256": sha256_file(GENERATOR_PROMPT_PATH),
        "authoring_script_sha256": sha256_file(Path(__file__)),
        "external_api_used": False,
        "local_model_used": False,
        "model_forward_used": False,
        "counts": {
            "scenarios": len(scenario_rows),
            "candidates": len(packet_rows),
            "boundary_pairs": sum(pair["kind"] == "boundary" for pair in pair_rows),
            "within_pass_pairs": sum(pair["kind"] == "within_pass" for pair in pair_rows),
        },
    }
    _secure_write(output_dir / "generator-run.json", _json_bytes(run))
    return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("rehearsal", "formal"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--session-identity", required=True)
    parser.add_argument("--reasoning-effort", default="runtime_not_exposed")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(generate(args), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
