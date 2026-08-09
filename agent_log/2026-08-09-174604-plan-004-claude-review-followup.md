# plan 004 Claude复核跟进

日期：2026-08-09

## 范围

- 在工作树 `.claude/worktrees/0809-plan004-review-fixes`、分支 `0809-plan004-review-fixes` 上继续修订
  `plan/004-remaining-test-failures-investigation.md`。
- 逐项独立核对用户转交的Claude复核，不实施39个严格失败或2个附加事项，不修改产品/测试源码，不运行Cargo构建
  或测试。
- 本批修订提交后按用户授权合并本地 `main`，不推送远端。

## Live code复核结论

Claude新增的2个阻断项与3个一句话补丁均成立：

1. external门禁冲突成立。`external-agent-migration/src/service_tests/plugins/marketplaces.rs` 中
   `import_plugins_infers_external_official_marketplace_when_missing_from_settings` 是当前缺省官方源进入真实import
   编排的贯通测试；它最终调用 `plugins.rs::add_marketplace`。原修订的宽过滤器 `test(/import_plugins/)` 会选中它，
   如果只“新增”fake组合测试而不原位改造旧测试，正式门禁仍可能访问GitHub。
2. Landlock shared helper冲突成立。`linux-sandbox/tests/suite/landlock.rs::assert_network_blocked` 接受任意非零，
   binary缺失也会被当作成功，并被wget以外的测试复用。原修订既要求wget使用强合同，又保留整包定向门禁，确实会
   把真实域名和宽松legacy合同混入D族hermetic证据。
3. OAuth core调用点成立。`core/src/mcp_skill_dependencies.rs` 的首次登录与去scopes重试也调用
   `perform_oauth_login`；CLI新增flag后，这两处必须显式保持launch browser为true，否则会改变turn期生产行为。
4. JUnit能力边界成立。`scripts/build-watchdog-lib.sh::rondo_inspect_junit_report` 只检查文件类型、闭合
   `</testsuites>` 与SHA-256；`retained` 不表示已解析failure/skip。测试体内提前 `return Ok(())` 在JUnit中仍是
   passed，报告解析无法发现这种语义假绿。
5. 决策表003不同步成立。正文已经把公开 `Direct` variant收紧为审计例外，原表仍只写“默认不变”，没有记录禁止
   配置/CLI/wire/生产构造与静态审查要求。

补充发现：Claude正文主要点出curl/ping/nc三项，但live code中shared helper除wget外共有6个调用者；另有
`sandbox_blocks_ssh`、`sandbox_blocks_getent`、`sandbox_blocks_dev_tcp_redirection`。方案按live code列全6项，
避免只修复审查示例而遗漏同类边界。

## 修订与理由

### 1. external原位改造并使用精确门禁

- 明确必须原位改造并重命名现有真clone测试为
  `import_plugins_infers_external_official_marketplace_with_fake_adder`，旧测试不得与新测试并存。
- fake返回带本地marketplace/plugin manifest的installed root，使组合测试继续覆盖source推导、adder参数、插件安装、
  outcome与配置，而不是只在adder处结束。
- 新增点名纯source测试，保留点名本地marketplace测试；门禁改为三个测试名的结尾锚定正则，不再使用
  `test(/import_plugins/)` 宽匹配。
- 理由：既保住唯一组合链路，又从命令层排除仍会真实clone的旧测试名。

### 2. wget使用独立helper，legacy调用者具名例外

- 明确新wget合同不得复用或修改 `assert_network_blocked`，使用仅服务于该用例的本地listener helper/内联fixture。
- 列全另外6个shared-helper调用者，本阶段不修改、不作为D族hermetic证据；它们仍参加最终workspace全量，失败仍红。
- 删除D族整包定向门禁，只保留点名wget强合同。最终workspace全量仍提供整体兼容回归，但不把legacy通过冒充
  wget合同证据。
- 同步限定完成标准和真实网络硬约束只约束本计划新建/修改并计入对应族验收的测试，并为6项legacy合同开具名例外。
- 理由：本任务严格清单只有wget一项；批量收紧shared helper会未经取证扩张范围，保留整包定向门禁又会破坏D族
  hermetic证据的自洽性。

### 3. OAuth保护非CLI生产行为

- 明确CLI首次与去scopes重试都传 `!no_open_browser`。
- 明确core首次与去scopes重试、既有silent wrapper都显式传true；禁止执行者顺手改成false。
- 给rmcp launcher零/一次调用测试和CLI flag透传测试冻结具名测试名，门禁改为结尾锚定匹配，避免宽
  `browser`/`oauth` 过滤器把无关测试混入附加事项证据。
- 理由：本附加事项只消除CLI测试/显式flag下的宿主浏览器副作用，不改变turn期依赖登录的既有产品行为。

### 4. 拆开JUnit完整性、结果语义和测试体语义

- `junit_status=retained` 只作为收尾/哈希完整性证据。
- 执行者从 `summary.env` 取得 `junit_path`，用独立只读XML解析汇总实际testcase、failure与skip；正式命令用
  `--retries 0` 机械阻止重试吞红，`--flaky-result fail` 作为纵深约束。
- 明确JUnit无法识别测试体提前成功返回；I/K必须通过删除静默返回、正对照、fake计数与代码审查证明。
- 理由：不虚构watchdog现有能力，也不把语义正确性错误委托给报告格式。

### 5. 同步决策表与执行序列

- 决策003写入 `#[doc(hidden)] Direct`、禁止配置/CLI/wire/生产构造和静态审查选择点。
- 更新D、J、K既有决策，新增watchdog/JUnit能力边界与Landlock legacy例外决策。
- 执行序列同步为独立wget helper、原位改造external测试、core OAuth保持true和JUnit独立解析。

## 验证边界

- 静态核对上述测试名、调用点、shared helper调用者、watchdog实现和方案交叉引用。
- 执行 `git diff --check`、命令过滤器/危险旧措辞检索和提交前暂存区检查。
- 本批仍是纯文档修订，没有运行Cargo构建、测试、V8、bwrap、OAuth或完整workspace；这些证据属于后续实施任务。
