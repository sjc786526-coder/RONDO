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


LOCK_PATH = REPO_ROOT / "eval/templates/publication-critic/training-data-design-lock-v6.json"
GENERATOR_PROMPT_PATH = (
    REPO_ROOT / "eval/templates/publication-critic/training-data-generator-prompt-v6.md"
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
        "C03 ELF 提取验证状态",
        "成员结果已回传，协作与影响链均被观察到；失败的 ELF 样本类别与当前 verifier 入口已经保留，外部 verifier 仍失败，事项未完成。",
        "从 verifier 的失败条件继续定位，不重复验证成员回传链。",
        "C03 已形成成员回传与 Team State 更新，后续验证状态尚未公开。",
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
        "分页游标边界稳定性",
        "空页之后会再次返回前一游标；复现只涉及过滤后无结果的分页分支，普通非空分页与下一页起点保持正确，事项未完成。",
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
        "Windows 子进程取消状态",
        "父进程已响应取消，直接子进程与普通退出对照均已回收，但孙进程仍存活；job object 继承尚未接入，事项未完成。",
        "先把孙进程加入同一 job object，再验证超时与显式取消。",
        "早期取消路径存在资源残留，尚未缩小到具体对象或生命周期层级。",
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
        "配置迁移回滚覆盖状态",
        "正向迁移和无重复索引的回滚对照已通过；失败只出现在目标中已有重复索引时，清理分支仍未覆盖，事项未完成。",
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
        "长任务恢复点回归状态",
        "空输出 checkpoint 已能落盘并通过崩溃恢复与不重复执行验证；空/非空混合批次的正式回归尚未固化，事项未完成。",
        "固化空/非空混合批次回归，并验证 checkpoint 身份不会相互覆盖。",
        "恢复路径已覆盖正常输出，边界恢复矩阵仍不完整。",
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
        "多语言错误消息覆盖状态",
        "英文与中文资源已加载且缺失键回退对照稳定；西班牙语仍回退到英文，现有资源清单已核对，es-ES 键映射尚未补齐，事项未完成。",
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
        "导出器先统一字段别名，再按 schema 固定顺序写入；正向、逆向和随机三种输入得到相同字节序列。数值与 Unicode 内容保持原样，重复运行 hash 一致；空字段、嵌套数组和组合字符对照也稳定，未改变 schema 外内容，事项已完成。",
        None,
        "该事项首次公开。",
        "formal",
    ),
    BoundarySpec(
        "b-scope-02",
        "scope_and_signal",
        "existing_event",
        "incomplete",
        "member",
        "搜索预算在符号链接环中耗尽",
        "普通目录与受控深度目录的预算计数稳定；符号链接环会重复计入同一 inode，修复尚未验证。差异只出现在环路径，非环对照保持通过；现有日志保留已访问 inode、预算消耗和停止原因，可复算差异。先按 inode 去重后复跑两组用例。",
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
        "日志只在轮换与写入落入同一毫秒时丢首条记录，常规写入和单独轮换都稳定。已把触发条件缩到文件句柄交换窗口；复现矩阵保留轮换前后文件编号与首条序号，已排除常规写入路径。下一步固定边界时钟并核对交换顺序。",
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
        "活动谓词已统一按 producer 与 Root 双生命周期计算，面板不再拼接两份独立结果。关闭但仍待 Root 处理的事件只显示一次，普通活动与已 resolved 对照也通过；测试覆盖 producer 关闭、Root pending 与 resolved 三个组合，事件身份保持不变，事项已完成。",
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
        "CLI 帮助、示例配置与运行时默认端口已统一为 4317；显式覆盖值仍优先，环境变量路径没有变化。快照分别覆盖默认调用、显式参数和环境变量覆盖，输出差异只剩预期端口值；三种入口的帮助与配置解析测试均通过，事项已完成。",
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
        "取消标志能够跨扫描层级传播，但当前只在每个目录结束后检查；单个大目录仍可延迟数秒。普通小目录保持稳定；测量已记录目录规模、批次大小和取消到返回的时间，便于调整后同口径比较。下一步把检查移到每批条目后并测量一万文件目录。",
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
        "任务锁文件已清除；定向用例通过，事项完成。",
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
        long_input=True,
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
        "批处理错误摘要回归待落库",
        "摘要首项遗漏已修并通过空、单、多失败与并行顺序边界矩阵；正式回归尚未落库，事项未完成。",
        "固化错误摘要边界矩阵，并复核首项初始化与追加共用同一顺序逻辑。",
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
    "b-continuity-01": ("成员结果已回传，协作与影响链均被观察到；任务尚未收口，但当前失败条件和后续验证位置没有形成公开状态。", None),
    "b-continuity-02": ("普通非空分页与下一页起点对照保持正确；仍有工作待收口，余下异常的触发条件和处理起点没有记录。", None),
    "b-continuity-03": ("父进程、直接子进程与普通退出对照均已回收；取消事项没有结束，剩余对象与生命周期接入点都未公开。", None),
    "b-continuity-04": ("正向迁移和常规回滚对照已通过；回滚覆盖还不完整，剩余失败输入或处理阶段尚未说明。", None),
    "b-continuity-05": ("空输出 checkpoint 已能落盘并通过崩溃恢复与不重复执行验证；恢复工作尚在进行，余下验证对象和断点没有记录。", None),
    "b-continuity-06": ("英文、中文资源和缺失键回退对照保持稳定；多语言覆盖还有空白，余下 locale 与处理路径未被保留。", None),
    "b-scope-01": (
        "正向输入先比较 id/name/tags，临时数组依次变成 name,id,tags 和 id,name,tags；逆向输入又逐键跑一遍，随机输入依次换成种子 7、19、23、41。导出器此时已经按 schema 顺序写入，三种输入结果相同。随后空字段重复两轮，嵌套数组拆成三层逐层比较，café 与 café 的交换位置又各抄一次；每轮仍逐项列出比较器左右值、返回值和数组交换，最后再复述四个种子的相同 hash。",
        None,
    ),
    "b-scope-02": (
        "从 root/a 进入 b/c 时累计 38 项，返回 a 后队列剩 5 个；沿 link-to-a 再走到 b/c，累计变成 76，第三圈到 114。符号链接环仍会重复计入同一目录，修复尚未验证。接着又逐层列出 a、b、c 的深度 1、2、3，各自重复抄写已访问数、剩余队列与预算余额；普通目录的 12、26、38 项对照也从头走了三遍，末尾再把每次进入和退出的计数相加核对。",
        "先按 inode 去重目录，再复跑环与普通目录用例。",
    ),
    "b-scope-03": (
        "09:41 用 4 KiB 缓冲写入 20 条，09:42 改成 8 KiB 又写 20 条，09:43 单独 flush 三次都保留首条；09:44 把轮换与写入压到同一毫秒时首条丢失。09:45 只改文件名没有复现，09:46 只换句柄也没有复现，09:47 同时换名和句柄再次丢首条。之后把七个时点的缓冲大小、flush 次数、旧新文件编号与首条序号全部重列一遍，又附上五次常规写入和三次单独轮换的相同结果。",
        "固定轮换边界时钟并检查文件句柄交换顺序。",
    ),
    "b-scope-04": (
        "第一次讨论把状态叫 active、closed、root-pending 和 visible，四个人依次复述各自定义；第二次把 root-pending 改成 awaiting-root，又逐个比较名称是否容易误解。关闭但仍待 Root 处理的事件此时已经只显示一次，回归通过。第三轮继续在 resolved、done、closed-final 三个词之间投票，随后逐人抄下对 producer closed、Root pending、Root resolved 的口头判断；最后两次会议又完整复述相同组合和命名票数。",
        None,
    ),
    "b-scope-05": (
        "先把帮助页第 3、8、14 段的 4316 改成 4317，再把示例一、示例二和示例三逐行重写；配置样例的 port、endpoint 与注释各检查一次，运行时默认值又单独核对两遍。CLI 帮助和配置默认值已经统一，快照测试通过。随后把未变化的 host、timeout、format、color 四项逐个列出，显式参数、环境变量和默认调用的输出也分别整页贴成对照，最后再次抄写六处 4317 与每个段落编号。",
        None,
    ),
    "b-scope-06": (
        "第 1 批进入 d1，处理 128 个文件用时 31 ms；第 2 批进入 d2，累计 256 个用时 67 ms；第 3、4、5 批分别累计到 384、512、640 个，每次都抄下进入时间、退出时间和取消标志。当前取消只在整个目录结束后检查，单个大目录会延迟数秒。其后又从第 6 批列到第 12 批，逐项重复文件数、累计耗时、标志读取值与队列长度；普通小目录的 24 次立即返回也逐次展开，尚未把检查移到每批条目后。",
        "把取消检查移到每批条目后，并测量一万文件目录。",
    ),
    "b-consistency-01": (
        "任务锁文件已清除；定向用例通过，事项完成。",
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
        "摘要首项遗漏已修并通过空、单、多失败与并行顺序边界矩阵；正式回归尚未落库，事项未完成。同一正式回归又被宣称已经收口。",
        "固化错误摘要边界矩阵，并复核首项初始化与追加共用同一顺序逻辑。",
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
        "父进程已响应取消，直接子进程与普通退出对照均已回收，但孙进程仍存活；job object 继承尚未接入，事项未完成。接续范围仍只限孙进程的 job object 继承以及超时和显式取消验证。",
        "先把孙进程加入同一 job object，再验证超时与显式取消。",
    ),
    "b-scope-04": (
        "活动谓词已统一按 producer 与 Root 双生命周期计算，面板不再拼接两份结果；关闭但 Root pending 的事件只显示一次，Root resolved 对照也通过。换句话说，producer closed 与 Root pending 的组合已经用同一谓词覆盖，普通活动和 resolved 组合也分别验证，事件身份保持不变；producer open、producer closed、Root pending 与 Root resolved 四组输入仍使用同一事件身份，结果与前述对照一致。这些结果再次说明双生命周期计算和去重显示都已完成，事项已完成。",
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
        "defects": ["internal_consistency"],
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
    "b-honest-04",
    "b-consistency-03",
    "b-consistency-06",
    *(f"b-continuity-{index:02d}" for index in range(1, 7)),
    *(f"b-scope-{index:02d}" for index in range(1, 7)),
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


LONG_PRIOR_PUBLICATIONS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "b-honest-04": (
        (
            "Unicode 标题排序的第一轮复现覆盖 NFC 与 NFD 混排。café、cafe 后接组合重音、全角拉丁字母和日文假名被放进同一批输入，连续运行时相邻两项偶尔交换。日志只保留了展示值、规范化后的排序键和比较结果，没有保留触发旧顺序的完整原始数组，因此只能确认漂移存在，不能归因到某一个比较器分支。ASCII-only 与全部预先转成 NFC 的对照始终稳定；大小写折叠未启用，展示文本也没有被改写。这个检查点留下已观察现象、稳定对照和缺失输入，避免把组合字符机制提前写成事实。",
            "保存能触发交换的最小原始数组，并分别记录每个元素的码点序列。",
        ),
        (
            "第二轮把内部排序键统一改为 NFKC 后的不可变副本，展示层仍读取原始标题。正序、逆序和固定种子随机序各运行十次，输出字节序列与 hash 均稳定；全角字符折叠后没有污染用户可见文本。只做 NFC 的对照在当前样本也稳定，但旧复现输入已经丢失，两种方式都不能证明历史根因。检查还覆盖空标题、单个组合标记、相同规范化键和不同原始标题落到同一键的情形；结果支持当前修复有效，只不支持对过去原因作确定陈述。",
            "保留 NFKC 键实现，并为相同键加入确定性的原始码点 tie-break。",
        ),
        (
            "随后专门比较 café 与 cafe 加组合重音的稳定 tie-break。兼容规范化键相等时，先比较规范化键，再比较原始码点序列，最后用稳定身份处理完全相等。包含重复标题、日文浊点、emoji variation selector 和空字符串的矩阵全部保持确定顺序；去掉最后一级身份后，完全相同标题会依赖输入顺序，但这不是先前观察到的不同标题交换。证据把风险缩到规范化键碰撞后的排序规则，却仍不足以说明旧实现究竟在哪一级失稳。",
            "固化 tie-break 矩阵，并检查序列化前后使用同一稳定身份。",
        ),
        (
            "回归收口时，标题排序在 Linux 与 Windows 的固定样本上得到同一序列，序列化前后 hash 一致，重复运行也没有再漂移。NFKC 只用于内部键，原始 Unicode 标题、大小写和组合形式继续按输入展示；稳定身份仅在规范化键与原始码点都相等时介入。当前实现和覆盖足以把事项标为完成，但历史样本缺少触发交换的原始数组，旧漂移由组合字符比较器、运行库排序稳定性还是上游身份变化造成，仍无法确认。最终状态必须同时表达已验证修复与未被证明的旧根因。",
            None,
        ),
    ),
    "b-consistency-03": (
        (
            "重放去重最初只使用 request ID。单团队内重复请求能够返回同一个 committed outcome，但两个团队实例恰好采用相同 request ID 时，后到实例会错误命中先到实例的结果。逐项检查确认请求正文、提交状态和 outcome 本身没有交叉写入，碰撞只发生在去重索引查找。现有公开记录保留了两个团队实例身份、相同 request ID、各自预期 outcome 与实际命中结果，没有复制工具输出或私有正文。普通同实例重放仍稳定，问题已缩到 key 缺少团队实例这一层。",
            "把团队实例 ID 加入去重 key，并保留同实例重放对照。",
        ),
        (
            "第二轮将 key 调整为团队实例 ID 与 request ID 的组合，并分别覆盖同实例同请求、跨实例同请求、同实例不同请求和跨实例不同请求。跨实例不再互相命中，同实例重放仍返回原 committed outcome；重放不会再次执行副作用。序列化后的 key 与内存 key 字段顺序一致，包含 Unicode 团队标签时也只使用稳定实例 ID。该轮证明局部实现有效，但尚未覆盖索引持久化后重启、旧格式 key 迁移和并发首次提交。",
            "验证重启读取、旧 key 迁移和两个实例并发首次提交。",
        ),
        (
            "持久化检查先写入新组合 key，再重启索引并重复四类矩阵。重启前后查找结果与 committed outcome hash 一致；旧 request-only key 被读取时不会冒充新实例命中，而是走明确迁移分支。两个实例并发提交相同 request ID 时，各自只产生一次本实例 outcome，没有共享锁条目。故障注入还覆盖迁移写失败与重启恢复，失败不会删除原条目。剩余工作只在历史数据兼容窗口和跨版本回滚，需要确认旧二进制不会把新 key 截断。",
            "完成跨版本读写矩阵，并验证回滚不会把组合 key 降级。",
        ),
        (
            "最终矩阵覆盖新旧版本读写、迁移成功与失败、重启、并发首次提交以及同实例重复重放。新版本始终以团队实例 ID 和 request ID 组成去重 key；跨实例相同 request ID 得到各自 outcome，同实例重放则稳定返回同一 outcome。旧版本只读窗口不会写回截断 key，回滚路径遇到新格式会明确拒绝而不是错误命中。所有定向样本连续重复后序列与 hash 相同，历史碰撞案例也不再复现。现有公开证据足以把事项标记为完成，且没有把未观察机制写成事实。",
            None,
        ),
    ),
    "b-consistency-06": (
        (
            "批处理错误摘要的第一轮检查确认失败总数始终正确：一个成功项和三个失败项返回计数三，逐项状态也保存三个失败。只有用户摘要从第二个失败项开始，首项既不在标题也不在明细。单失败输入得到空摘要，多失败输入得到后续项，这把差异缩到首项初始化，而不是执行器漏报失败。原始失败顺序、错误码和任务身份都保持正确；重试与并发关闭没有改变现象。当前事项未完成，下一步只检查首项初始化和追加分支。",
            "对照单失败与多失败路径，定位首项初始化是否遗漏赋值。",
        ),
        (
            "第二轮看到首个失败用于创建容器，但显示文本只在后续 append 分支写入。初始化同时加入首项后，单失败摘要出现一条，多失败摘要按输入顺序出现全部失败，计数与条目数一致。检查还覆盖首项为空消息、不同错误码、相同错误重复出现以及成功项夹在失败项之间；每个失败身份均保留，重复错误不会被去重。局部遗漏已经修正，但 Unicode 消息、并行收集顺序和旧快照兼容尚未验证，不能宣称收口。",
            "补 Unicode、重复错误和并行完成顺序矩阵，确认展示顺序合同。",
        ),
        (
            "第三轮加入中文、组合字符和 emoji 错误消息，并比较输入顺序、完成顺序与展示顺序。合同要求摘要遵循批次输入顺序，而不是 worker 完成顺序；实现先按原始索引归并，再生成首项和后续项。十组固定并发时序得到一致摘要，NFC 与 NFD 文本保持原样，重复错误码按任务身份分别显示。旧快照更新后多出此前遗漏的首项，预期差异逐项确认。尚需检查空批次、全成功批次和大量失败集合的截断提示。",
            "验证空、全成功和大量失败输入，尤其核对截断提示与总数。",
        ),
        (
            "收口前的边界矩阵显示空批次与全成功批次都返回零失败和空摘要；单失败、多失败、Unicode、重复码及并行乱序均按输入顺序列出。大量失败时摘要只展示合同允许的前若干项，同时明确完整失败总数和剩余省略数量，首项不会再丢失。计数、展示条目和省略提示算术一致，快照也按新合同更新。不过正式回归尚未落库，任务状态仍应保持未完成；如果摘要同时写成已经收口，就会与这个剩余动作冲突。",
            "固化边界矩阵并复核首项初始化与追加共用同一顺序逻辑。",
        ),
    ),
}


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
    publications: tuple[tuple[str, str | None], ...] = ((prior_summary, None),)
    if long_input:
        try:
            publications = LONG_PRIOR_PUBLICATIONS[scenario_id]
        except KeyError as exc:
            raise ValueError(f"missing authored long prior publications: {scenario_id}") from exc
    prior_publications = [
        {
            "summary": summary,
            "handoff": handoff,
            "evidence": {
                "fact_references": _fact_references(evidence_variant),
                "observation_availability": "unknown",
            },
        }
        for summary, handoff in publications
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
        candidate_is_long = spec.long_input
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
        "length_bucket": "long" if spec.long_input else "medium",
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
    if not REHEARSAL_BOUNDARY_IDS <= all_boundary_ids:
        raise RuntimeError("rehearsal Boundary registry contains an unknown scenario")
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

    expected_count = (
        sum(3 if spec.within_pass else 2 for spec in boundary_specs) + len(mixed_specs)
        if args.mode == "rehearsal"
        else 72
    )
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
