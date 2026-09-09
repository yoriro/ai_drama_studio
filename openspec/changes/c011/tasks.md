# C011 执行任务

### 2026-09-09 Astra 审查修复派发（需求方已授权）

本轮针对审查基线 `b4750e4ad7a8785e8ff3e965848526436aae94c3` 的B01–B10退回修复，依据spec §10与 `.work/c011/review-20260909.md`。本段优先于历史“已全部完成”结论；原始成功/失败日志与提交历史保留，不reset/amend。spec仍为31条AC，追溯仍为17条，先更新spec与追溯待补状态后才编写T29–T39。

**执行授权与顺序：** 本次需求方明确要求Luna修复问题。按T29→T30→T31→T32→T33→T34→T35→T36→T37→T38→T39串行，一次只做当前task，通过其完整验收/回填/提交后可自动进入下一个已列task，无需逐项再次询问。不能因原T28已勾或旧T24/T25的PASS跳过新修复。其他执行者/用户的改动不得回退或夹带；生产实现与新增回归由Luna负责，Astra本轮仅提交spec/tasks/追溯文档。

**已知失败的修复权限：** B01–B07的实现修复与其新回归已明确授权；对应复现失败本身不需要再次请示。先记录失败→定位当前任务根因→最小修复→定向与G验收。继续沿用原技术缺陷自主修复边界，禁止不改根因循环重跑；未获授权的既有测试修改、产品语义冲突、安全阻断、用户资源/真实GPU操作仍须报告。新增独立回归文件按T29–T36交付，所有既有测试保持不变；不改Astra探针或原报告换取通过。

**原任务重新验收：** 本轮将T05、T07、T15、T18、T19、T20、T21、T23、T24B、T24C、T24D、T24、T25及T26–T28恢复未勾。T29–T39完成后，按上述原任务列出的次序执行各自原验收（固定收尾仍最后）。已有正确实现不重写、不重复造测试；与本轮改动无关且基线/配置一致的人工证据可以精确引用，对受影响页面/时序必须新验。每个旧task满足其原验收后才能再次勾选；新修复task通过不自动代表原AC全量通过。最终T24覆盖修复后双主题全页，T25核对31条AC，之后T26→T27→T28收尾。T24A、T24E/F等未直接退回的历史切片保持原归属，不代替最终T24。

**提交边界：** Astra先提交本轮三份需求/任务/追溯文档并将原未跟踪spec纳入Git，解决审查B10的缺文件部分，绝不提前勾T28。Luna获授权逐task提交实际已验收修复与对应新增测试/追溯/状态；只用显式路径stage，不stage用户AGENTS改动或.work，不归档、不推送。T39及最终T28仍须以实际HEAD重新核对文档与修复状态。

### 2026-09-09 验收频率调整（需求方明确授权，即刻生效）

本节统一替代本文件及 spec 历史裁决中的“每个 task 都运行 G”“修复后必跑 G”频率要求；历史命令/结果原样保留，不追认未运行检查通过。G 的内容仍是完整回归，绝不通过修改 run_checks.ps1 跳过步骤来冒称 G 通过。其他定向、浏览器、异常矩阵、同 task 请求/事件/独立 DB、资源退出及任务依赖要求不变。各 task 的 R、测试层级和追溯行继续沿用原项。

| 任务/改动范围 | 当前必须执行 | 完整 G 安排 |
| --- | --- | --- |
| 纯文档、追溯、证据整理 | 原项人工核对、`git diff --check`、commit/日志一致性 | 不运行；收尾引用覆盖最终实现的阶段证据 |
| CSS/布局实现或修复 | `npm --prefix frontend run build`；原项规定的两主题/视口/受影响页面检查 | 不逐 task 运行，归阶段收口 |
| 前端状态、请求、竞态实现或修复 | 原项定向测试/探针；`npm --prefix frontend run test` 与 `npm --prefix frontend run build` | 不逐 task 跑后端全量，归阶段收口 |
| 后端/验收装置实现或修复（含 T37 如再次退回） | 原项具体定向命令、自检及规定的独立进程/HTTP/WS/DB/退出验证 | 归阶段收口；如影响公共队列、数据库、lifespan、协议或依赖且范围广，说明影响后提前执行 |
| 当前 T38 | ordinary/受控各自 fixture verify；完整八按钮逐任务证据及八页异常矩阵、恢复验证；文档一致性 | 不新跑 G；T38 门槛全部通过才进入 T39 |
| T39 集成收口 | 原项两发审查探针必须正式执行；逐测试/AC 追溯核对 | 一次完整 G；已有完全相同受测输入的成功 G 可核对后引用，不自动假定 T37 结果适用 |
| T39 后退回旧任务（含 T23/T24） | 逐项补齐规定的专项/真实浏览器证据；已被本轮同输入证据覆盖的用例明确引用，受修复影响的路径新验 | 无相关输入变化不重复 G；若产生修复，先定向验收，最终 T25 前更新 G |
| T25 最终审计 | 31 条 AC、全部必需证据及最终受测范围审计 | 核对并引用覆盖最终输入的 T39/之后完整 G；缺失或相关输入已变化时执行一次 T25 G |
| T26–T28 固定收尾 | 原项文档/候选/commit 一致性检查，引用 T25 确认的回归 | 不因 checkbox 或纯文档 commit 重跑 pytest/build |

**证据复用条件：** 列出受测 commit、当前 commit/工作树差异、相关生产/测试/依赖/装置/环境配置、实际命令、原始日志及已结束进程的真实退出码。文档提交或单纯追加日志不使运行证据失效；相关实现、fixture、配置或依赖变化使对应证据失效。不得用旧环境/其他任务的请求和 barrier 替代当前任务必需的现场证据；失败、未运行或缺原始结果不能算通过。未知是否受影响时先检查 diff/通路，不能无依据复用。

**完成口径：** 本 task 所有必需门槛满足才勾选；阶段 G 尚未到期不单独阻塞当前项。报告明确“本次执行”“引用已有本轮证据”或“本 task 不要求全量，待 T39/T25”，最终 AC-23 仍要求完整回归证据。已启动的验证不强制中断；相关失败先按既有授权修根因、补定向验证，不无变化循环全量。无需新增验证装置、测试、追溯行或修改产品行为。

本文件是实施计划，checkbox 只表示已有验收证据，不替代 commit 证据；实施范围以需求方另行指定的任务为准。最初规划轮不授权实施；需求方随后已向 Luna 派发执行，并于 2026-09-07 授权下述任务内自主修复。按依赖一次只执行需求方指定的一项；失败不得勾选或推进，技术缺陷按下节自主诊断修复，需求歧义及越界事项停止报告，不重放失败业务 Task、不覆盖失败证据。新增测试只能是新的独立文件；既有测试仅允许 AGENTS.md 明确记录的 C011 T05 提交屏障窄修正，其余不变。

## 通用验收命令与约定

2026-09-08需求方追加四项前端优化：先完成T24B-T24F（按下文依赖），结合T24A再执行最终双主题T24，最后才进入T25及固定收尾。T24本身仍是无实现改动的验收任务；实现单列在B-F，旧任务编号/提交历史不重命名、不重写。新增AC-26..31在spec定稿后已先补4条追溯行，再编写以下任务；不把过去暗色验收或G通过当作新需求完成。本轮Astra仅修改计划/追溯，不实施前端。

2026-09-08 T24B安全停止后调整：按spec §7.4将正式控件交付前的DevTools临时主题检查移交T24C，改由真实主题按钮验收。先完成下列T24B静态交付检查，才按既有派发进入T24C；不得直接凭G勾选T24B或声称双主题视觉通过。AC-05/07/26仍有准确追溯行，无新增AC或测试行；T24C承担完整双主题视觉检查及明确的主题CSS修正，验收未完成不得进入T24D。浏览器安全停止不属于可通过改脚本、换工具通路或伪造URL自主绕过的技术错误；保留原证据。本轮规划不代Luna勾选或提交任何任务。

### 需求方于 2026-09-07 授权的任务内自主修复边界

本节记录需求方“下次碰到这种情况让 Luna 自己想办法解决”的最新授权，适用于 C011 当前已被明确派发的 task。此前本文件各次裁决中对下列技术缺陷要求“立即停止并等待再次裁决”“仅允许一次重验”的限制，由本节替代；不改变需求合同、任务顺序或验收通过标准。根因未明时可以继续只读诊断，不必把每个工具错误都交回需求方。

- **可自行修复并重新验证**：当前 task 范围内的脚本语法/字符串/参数/路径拼接错误、原生命令启动与输出/退出码采集、已安装依赖的初始化、验收装置的 HTTP/WS 协议分类及资源生命周期错误，以及当前授权实现的明确编译/类型/变量作用域缺陷。前提是根因有代码或日志证据，修复保持既定 spec/PRD/API/数据语义且不扩大文件或能力范围。例如 PowerShell `.concat()`、未启动 npm 的空日志路径、把 useLocation 放错组件，都不再需要逐次请求裁决。
- **执行顺序**：保留原命令、原始输出、失败退出码或“命令未启动”事实；检查相关完整调用通路并说明根因；做最小修复；执行最便宜且能覆盖该缺陷的验证；通过后完成原 task 的全部验收。优先直接调用标准 CLI 或复用已通过验证的装置，不为一次命令另建启动器。需要重跑 G 或有数据库/文件副作用的验收时使用新批次和既定新隔离库/DATA_DIR，旧证据与部分数据保留，禁止在同一部分完成环境盲目重放 mutation。无需为了修复未启动的本地 CLI 再等待需求方批准。
- **自主修复不等于隐藏失败或自动重试**：原次运行仍标记失败/未启动；修复后的执行单独记录。禁止不改根因重复同一失败命令、循环跑到绿、吞异常、过滤错误、伪造退出码、削弱检查或拿局部通过代替整项验收。修复若未解决已判断的根因，应重新诊断；不能定位根因或只能通过越界改动继续时，停止并汇总证据与待决问题。
- **仍须停止报告**：PRD/spec/代码之间会改变行为的冲突或歧义；业务/一致性/并发验收断言失败而需要改变既定行为或期望值；需要修改任何既有测试、关闭类型/构建检查、增加依赖/机制或扩大当前授权实现范围；需要操作用户数据库/进程、缺失外部依赖门槛、重放 failed 业务 Task、破坏性清理或其他未获授权行为。普通检查失败可以诊断，但不得自行把它认定为“测试错了”。本节不授权后续 task、修改生产依赖配置或绕过外部门槛。
- **完成与报告**：按上述验收频率调整完成本 task 全部必需验收前不勾选、不回填成功、不提交；G 仅在指定收口或广泛影响触发时要求。完成报告集中列出遇到的技术缺陷、修复、各次证据与最终真实退出码，不再让需求方逐条批准这些范围内修复；提交仍遵守既有逐 task 授权，不夹带其他 task 改动。生产 Task 的失败不重试规则完全保留。

### 命令与证据

- 本轮规划基线：`1ef70e5d5fad245d6e38e1472eaa16ffb523aa59`。正式实施前记录实际HEAD与已有改动；未经授权不清理 `.work/`。
- 以下文件名/CLI 是前置 task 的**计划交付合同**，不是声称当前已存在。`tasks.md` 不授权把它们今天落盘。
- **G**：在仓库根运行 `powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task Txx`（Txx 换为本项编号）。T01 必须先交付此装置；各项调用内部逐条执行 `npm --prefix frontend run test`、`npm --prefix frontend run build`，在新建、仅迁移的 PostgreSQL/独立 DATA_DIR 中以 backend 为 cwd 执行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、`python -m pytest -q`，最后 `git diff --check`。每步原生退出码为0才继续；stdout中“passed”不能替代已结束进程和真实退出码。
- 定向 backend 使用显式环境指定的新隔离库/DATA_DIR，以 backend 为 cwd 运行原项指定的 `python -m pytest -q tests/...`（路径换为该项已列文件或 node ID），按既有准备流程完成迁移并保留原始退出码；不能连接浏览器库或用户库。T01 的 `-TargetPytest` 会在定向后继续完整 pytest，因此只在本轮也要求 G 时使用，不用它执行每个小 task 的定向检查，也不修改启动器新增选择模式。完整 G 的 pytest 仍使用另一个全新仅迁移库。前端定向命令在本项明列。
- 浏览器 ordinary、受控任务、pytest 三类环境分离；通过环境变量显式选择，不改用户 `backend/.env`。现场选择并记录可用端口；若Vite固定代理8000被用户进程占用，单独的验收Vite配置放.work并启动隔离端口，不能停用户进程或修改生产业务地址。启动自有后台进程使用 Hidden 窗口。
- 浏览器能力须用公开API发现：在当前工具文档允许的已选browser上执行`await browser.capabilities.list()`，再以`await browser.capabilities.get("viewport")`取得能力并读取其`documentation()`；不能用对象JSON序列化结果`{}`或不存在的`tab.playwright.viewport`推断能力缺失。2026-09-08 T24F裁决现场只读确认IAB列出visibility/viewport，viewport正式接口为`set({width,height})`和`reset()`。Luna按当前任务分别设置320×800、390×844、768×1024、1440×900，每次读取实际页面尺寸、截图与任务规定的布局/交互结果，结束恢复override；能力可调用的证据不等于项目四视口验收通过。原错误记录保留，可在既有自主修复范围内纠正调用并补验，无需新增脚本。原生200%与viewport、devicePixelRatio=2的证据仍须区分；T24全页原生200%和动态reduced-motion按2026-09-09 spec §7.4裁决不再阻塞，记录未验证范围，不反复重跑G或猜测隐藏API。T24F已有人工作证保持原归属。
- 自建脚本/fixture不提交。装置需记录实际命令与原始证据；文中没有可用地址、数据库或测试通过的预设结论。依赖门槛见spec“外部依赖”。
- 计划测试层级仅使用题设五种名称；同时涉及取消与跨进程的任务同时列“任务系统 mock”和“跨进程/资源生命周期”。前端使用任务事件/取消的DOM mock不冒称后端集成，反之跨进程API测试不冒称点击了React控件。
- 表达“某AC切片”意味着本task仅验收明确列出的页面/职责；AC全量收口在T23/T24/T25，不能提前声称整条AC完成。
- 先完成本spec §9逐条覆盖并补齐13条TRACEABILITY行，再编写本tasks；规划检查记录为13组映射、13行存在、缺失0。用例ID在实施后回填，不预填虚构成功。

## 按依赖执行

- [x] **T01 交付隔离回归命令装置与实施基线**
  - 依赖：无。
  - R：无；PRD：§5 通用、§10、§11 M5、§12.4。
  - 交付范围：仅交付 `.work/c011/run_checks.ps1`：记录规划基线/当前 HEAD、检查权限和工具，读取受保护配置但不打印 DSN；每个 Task 调用创建未存在的 pytest 专用库与 DATA_DIR，Alembic upgrade head 后依次运行前端 test/build、完整 pytest、git diff --check，每步保存原生 stdout/stderr/PID/退出码且失败立即停止。保留所有旧库/日志。脚本不复用浏览器库，不停用户运行进程，不安装正式模板。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T01`；检查数据库名与 `current_database()` 一致、Alembic head/check、子进程已结束、exit-code=0；人工确认凭据未进入日志且 .work 未 staged。该脚本是后续 G 命令的计划交付物，当前尚不存在。
  - 验收归属：AC-01/AC-23 的证据通路。新脚本只包装既有命令，不新增验证该脚本本身的测试。

- [x] **T02 补齐 DOM 行为测试依赖**
  - 依赖：T01。
  - R：无；PRD：§9、§11 M5。
  - 交付范围：在既有 frontend/package.json/package-lock.json 加入与当前 Node/React 18 兼容并锁定的 jsdom、@testing-library/react、@testing-library/dom 开发依赖。保留 Vitest 3.2.4 和既有默认 Node 用例环境；新 DOM 用例使用文件级 jsdom 指令。无测试文件变更、无新 runner、无空示例测试。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：`node --version`；`npm --prefix frontend ls vitest jsdom @testing-library/react @testing-library/dom`；G。人工审计 lockfile 只有同一 npm 依赖图；不得以安装失败为由升级 React/Vite/Router。
  - 验收归属：§7.1 装置前置；不证明页面行为，后续 task 实际挂载组件。

- [x] **T03 交付普通页面 fixture 装置**
  - 依赖：T01。
  - R：无；PRD：§2.1、§4、§5、§9、§11 M5。
  - 交付范围：交付 `.work/c011/ui_fixture.py`，按 spec §7.3 分离显式离线 fixture 与正式 API 设置/读取阶段；只使用本轮普通浏览器隔离库/DATA_DIR。覆盖空项目与含数据项目、四 tab、各种 changed/stale/生成态、图片/take/current/DEBUG 可见性素材。初始化无创建 API 的 Shot/take 明确记录为 fixture，不能伪称生成；不修改生产文件或新加 endpoint。单列的本前置装置 task 同时交付 `.work/c011/vite.config.ts`：仅代理本轮后端、加载原前端源码/插件，端口由现场核对后显式传入，禁止转发用户运行库或修改生产 Vite 配置。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C011 全局浏览器功能与视觉验收`、`C011 验收装置与生产通路归属`。
  - 验收方式与命令：`python .work/c011/ui_fixture.py --help`；`python .work/c011/ui_fixture.py prepare`；`python .work/c011/ui_fixture.py verify`；G。prepare/verify 读取本轮显式 DATABASE_URL/DATA_DIR 及仅验收使用的 C011_API_ORIGIN；真实值在现场选定记录，缺失则失败。写请求前保存普通后端 /openapi.json，一次确认全部 method/path；回读记录实体 ID、各页输入、媒体解码，不依赖旧库。
  - 验收归属：AC-22 的装置前置与 AC-24；prepare/verify 验证自身连接池生命周期及独立回读，不宣称上游生成/生产任务资源生命周期。spec §7.3 是其存储差异合同。AC-24 已在 spec §9 对应现有追溯行，无缺行，不新增仓库测试文件。

  **2026-09-07 Astra 对 T03 NativeCommandError 阻塞的裁决（仅本项）：**

  1. 现有 `.work/c011/T03-test.log` 记录 `python.exe : INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.` 和 `FullyQualifiedErrorId : NativeCommandError`；启动器第 72 行的 `2>&1 | Out-String` 在读取第 73 行 `$LASTEXITCODE` 前中断。`backend/alembic.ini` 的 console StreamHandler 目标为 `sys.stderr`、alembic logger 为 INFO。裁决为**验收启动器的输出/退出码处理缺陷**；原次 Alembic 的实际退出码和最终迁移状态缺失，既不能判迁移成功，也不能据此判迁移本身失败。T03 保持未完成。
  2. 允许 Luna 在 T03 内修正已建的 `.work/c011/prepare_ui_fixture.ps1` 原生命令采集，包括同一种错误调用方式的建库、迁移、fixture prepare/verify 边界。参照 T01 现有 `System.Diagnostics.Process` 做法，分流并并发读 stdout/stderr、等待进程退出、持久化 PID 与真实 ExitCode，再判定是否继续；不要 dot-source 会自动执行 G 的整份脚本，不新建通用执行框架。不改生产代码、alembic.ini、迁移、既有测试或业务规则。
  3. 不允许 `2>$null`、全局改用 Continue/SilentlyContinue、catch 后强制成功、过滤 INFO/错误关键词或只检测日志非空。修正后先用无业务副作用的临时原生命令验证：写 stderr 且 exit 0 必须完整留存并按退出码通过；无 stderr 且 exit 7 必须保存 7 并停止；进程启动失败必须停止。保存自检原始结果，不新增验证装置自身的仓库测试文件。
  4. 原 `.work/c011/T03-test.log`、已有数据目录/数据库和其余失败证据全部保留，缺失的原始 stdout/stderr/退出码明确标记缺失，不补造。允许为本次新尝试引入明确的证据批次参数/文件前缀；T01 `run_checks.ps1` 如因已有 `T03-test.log` 拒绝运行，只允许补充独立证据批次命名，Task 仍为 T03，原命令集合、全新库要求、失败停止和退出码判断不变。不得改名/覆盖旧日志、重置旧库、复制脚本为版本文件或把新尝试伪装成 T04。
  5. 上述根因修正和自检通过后，**允许一次新的 T03 完整验收**：使用新的普通浏览器隔离库及 DATA_DIR，核对本轮进程与端口归属；迁移 upgrade/current/check 均保存原生输出/退出码；启动普通后端、一次核对 OpenAPI，再执行原定 fixture prepare、verify 与 G。G 的完整 pytest 另用新建仅迁移库。不得复用原次可能已部分迁移的库；不停止、接管或连接用户 walkthrough 服务。
  6. 本次是修复验收装置后重新取得证据，不是重放 failed 业务 Task、自动重试或跳过失败 gate。若修正后的自检或任一正式门槛再次失败，保留新失败并停止报告，不连续改动/重跑直到变绿。全部 T03 验收完成前不得勾选、回填成功、提交 T03 或进入 T04。
  7. 本次裁决不替 Luna 修复或运行装置，不追认 T01/T02 已提交；现场 `git log` 的 HEAD 仍为规划基线，已有 T01/T02 勾选与“commit：无”须在完成报告如实区分。后续提交继续遵守调用方逐 task 的提交纪律，不将多个 task 的改动合成 T03 提交。

  **2026-09-07 Astra 对 T03 HttpClientHandler 阻塞的补充裁决（仅本项）：**

  1. 根因已用无业务副作用探针验证：实际 `powershell.exe -NoProfile` 为 `5.1.26100.6899`，加载前 `System.Net.Http.HttpClientHandler` 类型不可用；执行 `Add-Type -AssemblyName System.Net.Http -ErrorAction Stop` 后，`HttpClientHandler` 与 `HttpClient` 均能创建并释放，探针 exit=0、HTTP请求=0、数据库写入=0。当前启动器未显式加载程序集便在第159行创建Handler，属于装置运行依赖初始化缺失，不是后端HTTP或业务失败。
  2. 允许 Luna 在现有 `prepare_ui_fixture.ps1` 的建库、迁移、启动后端等副作用之前，显式执行上述 Add-Type，并把两种HTTP类型的构造/释放加入现有自检的启动前检查；保留程序集加载/构造失败即停止。不得下载DLL、安装包、切换shell、增加类型探测fallback或吞掉类型异常。本次由标准程序集加载解决，不能引入另一套HTTP客户端/通用启动框架。
  3. 既有自检只证明stdout/stderr/退出码采集，没有覆盖启动器HTTP依赖。修正后的自检须在实际 `powershell.exe -NoProfile` 下同时覆盖已规定的三项原生命令检查和HTTP类型初始化，记录版本、类型、退出码及零业务副作用。不能只在交互式pwsh已加载类型的会话中检查；先完成全部启动前检查，再开始新验收，避免建库/启动后才发现依赖缺失。
  4. 本次批次 `T03-rerun-20260907_121431-27344` 的 migration.exit-code.txt 为0，stderr记录迁移至 `6b8e3f0a1d24`；后端日志记录PID35808启动及8004监听。这些是该时点证据，不能说明T03完成或服务当前在线。本次裁决的只读观测未发现该PID，8004无监听；后续执行前仍须重新检查进程/端口归属，不复用历史PID、不终止用户进程。原数据库、数据目录和全部批次日志保留。
  5. 依照本次补充裁决，允许在根因修正、自检通过后，再取得一次新的完整T03验收证据：新普通验收库、新DATA_DIR、新证据批次，upgrade/current/check原生退出码均为0后启动后端，核对OpenAPI，执行fixture prepare/verify，最后按已有EvidenceLabel接口运行T03的G；完整pytest仍用另一个新建仅迁移库。原先缺失的current/check、prepare/verify和G不能用upgrade=0替代。已有日志不得覆盖，失败业务Task不得重放。
  6. HTTP就绪等待属于本轮自有进程启动观察，不重发业务mutation；连接拒绝/超时等已捕获观测必须保留具体原因及尝试记录，不能只存空字符串掩盖错误。超过既有等待期限或出现非预期异常仍失败并停止。若修正后的自检或正式验收再次失败，保留证据并报告；本补充裁决不授权后续task或连续改动/重跑直到变绿。T03仍不勾选，完整pytest未运行的事实继续明确报告。

  **2026-09-07 Astra 对 T03 事件循环阻塞及完整装置检查的补充裁决（仅本项）：**

  1. 证据：批次 `T03-rerun-20260907_122125-33044-fixture-prepare.stderr.log` 在原 ui_fixture.py 第434行进入第二个 `asyncio.run()`，第261行 `session.get(Clip, clip_id)` 报 `Event loop is closed`，后续为 Proactor 的 `NoneType.send`。原第399行已执行第一个 `asyncio.run()`；两段均导入同一模块的 `async_session_factory`，没有释放引擎。NOTES.md 第87行已有同类坑说明。裁决为 fixture 的连接池生命周期缺陷，不能据此判定生产业务失败。原批次 prepare exit=1，verify/G/完整 pytest 未完成，原证据继续保留。
  2. 本轮先完整读完现有 ui_fixture.py、prepare_ui_fixture.ps1、T03-rerun-selfcheck.ps1、vite.config.ts 和 run_checks.ps1，逐项对照本 T03 全部裁决及 spec §7.3。审计记录写本轮 .work 证据，覆盖原生命令退出码、运行依赖初始化顺序、数据库配置导入时机、事件循环/session/engine 所有权、API 已提交数据与离线事务、文件路径与批次、prepare→verify 环境传递、进程启动/退出及 G。只读审计发现的同范围装置缺陷应集中修正后再验收，不按一次报错只改一行；需求歧义或生产合同冲突仍立即停止。
  3. 具体交付拆项：① ui_fixture.py 将 prepare 的两段 ORM 与数据库身份读取纳入一个顶层异步入口，保留“分镜提交→正式 API 创建 Clip→视频准备”的顺序；② 该入口通过 finally 在同一循环内等待事务/session 退出和既有 dispose_engine() 完成，并记录实际资源顺序，不吞原异常或清理异常；③ 使用同一批次独立目录存放 manifest/OpenAPI/图片，prepare/verify 显式使用同一目录，旧目录不覆盖、不移动；④ prepare_ui_fixture.ps1 将程序集及客户端构造自检前移到建库/迁移/启动后端之前，补齐原裁决要求的 Alembic current/check 及其输出/退出码；⑤ 现有自检补齐实际 powershell.exe -NoProfile 的运行依赖检查。不得修改生产连接池或改为 NullPool，不新增执行框架、独立驱动、DLL/包依赖、迁移或仓库测试，不改旧测试。Vite 配置只核对既定代理合同，run_checks.ps1 仅沿用已授权的批次命名范围。
  4. 验收前按实际代码逐段人工审计所有 finally 与异常传播，记录覆盖与未动态验证的异常分支。先运行 `powershell.exe -NoProfile -File .work/c011/T03-rerun-selfcheck.ps1` 和 `python .work/c011/ui_fixture.py --help`，保存新批次结果；已有自检内部预期 exit=7/启动失败是规定的探针输入，自检是否通过由其断言和最终退出码判定。自检不能冒充数据库/媒体验收；不新建“测试自检脚本”的仓库测试。
  5. 全部审计和自检通过后，授权一次新的完整 T03 验收。现场查明可用端口后运行 `powershell.exe -NoProfile -File .work/c011/prepare_ui_fixture.ps1 -ApiPort <现场端口>`；新普通库、新 DATA_DIR、新证据目录，upgrade/current/check 均 exit=0，然后普通后端/OpenAPI/prepare/verify；记录 AC-24 的循环、事务/session、dispose、子进程退出及正式回读证据。再运行 `powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T03 -EvidenceLabel <本轮唯一标签>`，其完整 pytest 使用另一个全新仅迁移库。尖括号为需现场替换的参数，不预设可用端口或通过结果。
  6. 任一自检或正式门槛失败即保存本轮证据并停止，不继续修跑到绿、不复用部分数据、不重放业务 Task、不进入 T04。成功才勾选 T03；追溯分别记 AC-24 装置证据和 AC-22 的装置前置，不能把整条浏览器视觉验收回填为通过。只按既有授权提交本项已验收文档/追溯，不 stage .work 或夹带 T01/T02 的前端依赖改动，不追认旧任务已提交。报告真实命令/原始输出/退出码、HEAD/commit、遗留进程和失败分支未验证项。

- [x] **T04 交付受控任务运行时装置**
  - 依赖：T01。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§11 M5。
  - 交付范围：仅交付 `.work/c011/task_runtime.py`：既有 create_app 的显式注入 seam、独立进程/管道 barrier、生产 TaskQueue/EventBus/REST/WS/真实 PostgreSQL；足量有效 target 和混合历史任务通过队列原语产生。CLI 支持 serve、自检和按 task ID 放行/失败控制，输出 READY 与 barrier reached 事实。外部 clients/handler 为明确受控替代。普通 app.main 默认 handler/配置不改。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C011 验收装置与生产通路归属`。
  - 验收方式与命令：`python .work/c011/task_runtime.py --help`；`python .work/c011/task_runtime.py self-check`；G。自检以独立 HTTP/WS 客户端观察真实 enqueue→claim→progress→done，第三方 DB 只读连接对照，正常退出后本轮进程消失；逐项审计无直接状态 UPDATE、伪 WS/第五 task type/生产 endpoint。服务端写操作前一次核对该 runtime 的 /openapi.json。
  - 验收归属：AC-20；取消胜方验收另列 T22。本 task 不声称真实 GPU/业务产物成功。

  **2026-09-07 Astra 对 T04 OpenAPI/WS 阻塞的裁决（仅本项）：**

  1. `.work/c011/T04-selfcheck-20260907-131110-5772.log` 记录 `required task OpenAPI operations missing: [('/ws/tasks', 'get')]`。task_runtime.py 的 REQUIRED_OPENAPI_OPERATIONS 错误包含该项，而生产 backend/app/api/tasks.py 使用 `@ws_router.websocket("/ws/tasks")`。本机无网络/数据库副作用的 FastAPI 探针输出 `HTTP_IN_OPENAPI=True`、`WS_IN_OPENAPI=False`、`WS_ROUTE_TYPE=APIWebSocketRoute`，exit=0。这是装置协议分类错误，不是生产缺失接口；T04 未验收，原日志保留。
  2. 授权只修现有 task_runtime.py：从 HTTP OpenAPI 必需集合移除该 WS 项，保留原三项任务 HTTP 路径及其 method 检查；保留并实际执行原有独立 websockets 客户端握手、事件采集、Task/REST/独立 DB 对照及 barrier 检查。移除错误分类不等于取消 WS 验收。不得新增 GET /ws/tasks、修改生产路由/schema、伪造事件、放宽事件断言或跳过 WS。
  3. 同时修正 command_self_check 成功标记：现有代码只在 RuntimeCheckError 时赋 failure，其他异常逃出仍可能在 finally 写 RESULT PASS。成功标记只能放在 run_self_check（含其 finally 清理）正常返回之后；异常路径不写 PASS。用明确成功控制流保留所有异常及 traceback，不新增 broad catch，不把未知异常转换为成功。日志保存失败同样非成功，不允许原始异常被无说明覆盖。
  4. 重验前完整读完本装置，核对 HTTP/WS 分类、事件订阅时序、跨进程事件实际来源、DB/loop/engine 所有权、stdin barrier、超时/异常/清理及结果标记。审计记录已知两处修复及其余发现；其他会改变业务语义或扩大实现范围的缺陷先停止报告，不顺手实现后续任务。静态审计不能冒称真实 WS 已连接。
  5. 上述修复与审计完成后允许一次新 T04 自检：`python .work/c011/task_runtime.py --help`，随后 `python .work/c011/task_runtime.py self-check`，使用新的隔离库、DATA_DIR、证据批次和本轮自有进程；保留旧失败资源。记录 HTTP OpenAPI 核对、独立 WS 握手与匹配 task_id 的事件、barrier、REST/DB 对照、engine 释放、子进程退出及真实原生退出码。自检通过后运行 `powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T04 -EvidenceLabel <本轮唯一标签>`；完整 pytest 使用另一个新建仅迁移库。任一正式门槛再次失败即停止，不连续改动/重跑到绿。
  6. 仍归“跨进程/资源生命周期”，R：无；PRD：§2.1(8)、§5 任务、§6.1、§11 M5；沿用 AC-20 与 `C011 验收装置与生产通路归属`，覆盖行已存在，不新增测试文件或提前回填通过。全部通过才勾 T04并依既有授权提交本项文档/追溯；不提交 .work、不夹带前端依赖等其他 task 改动、不进入 T05。报告命令、原始输出、退出码及未验证边界。

- [ ] **T05 实现设置与任务中心的来源返回**
  - 依赖：T02、T03。
  - R：无；PRD：§2.1(1-3,8)、§9、§11 M5。
  - 交付范围：新增最小 navigation 来源决策与独立纯函数用例 `frontend/src/features/navigation/returnLocation.test.ts`；在 AppShell 及所有现有指向 /settings、/tasks 的页内链接接线。来源放路由 state；辅助页继承、replace 返回、刷新/无来源/非法来源行为严格按 spec §2.1。目标错误页保留首页链接；不引入草稿保存或最近页持久仓库。
  - 计划测试层级：纯函数。
  - 追溯行：`C011 导航来源返回与剧集唯一入口`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/navigation/returnLocation.test.ts`；G；人工浏览器逐项 AC-02/03：六类来源、辅助页互跳、刷新、新标签、浏览器 back/forward、非法来源和已删实体，记录目标 URL 与零额外 mutation。纯函数用例不得声称验证已挂载 Router；真实浏览器补足接线。
  - 验收归属：AC-02/AC-03 完整。实现前对被替换的既有导航片段 git blame。

  **2026-09-07 Astra 对 T05 location 作用域构建失败的裁决（仅本项）：**

  1. `.work/c011/T05-t05complete20260907_1337-test.log` 记录前端14个测试文件、88个用例通过，frontend test exit=0；`tsc -b && vite build` exit=1，G 停止，Alembic/完整 pytest 未执行。AssetPage 第64行与 EpisodeWorkspacePage 第44行的 useLocation 局部变量声明在父组件，使用位置却分别在独立模块级组件 AssetCard、ScriptEditor 内。子组件无法访问父组件局部变量，裸 location 解析为 DOM 全局 Location，产生无 state 的 TS2339；父组件未使用的局部变量产生 TS6133。这是 T05 导航接线缺陷，不是依赖/构建器失败，也不涉及产品语义歧义。
  2. 授权本轮最小修复仅限这两个生产页面：将 `const location = useLocation()` 从未使用的父组件移至实际使用路由来源的 AssetCard、ScriptEditor 函数组件顶层，遵守 Hooks 无条件调用规则；两个组件均沿用既有 Router 上下文。保留三个任务中心 Link 的 getAuxiliaryNavigationState 调用和原 pathname/search/hash/state 合同。不使用 window.location、any/类型断言、ts-ignore、关闭 noUnusedLocals、改 tsconfig 或削弱 build；不修改既有测试、生成动作、API、数据或其他业务逻辑。删除旧声明前按 AGENTS 执行 git blame，报告准确移除位置。
  3. 先只读核查 T05 全部新增来源链接的声明/使用是否处于同一有效作用域，重点检查同文件独立子组件；不得把文件内“存在 useLocation”当成接线有效。发现本裁决之外的业务歧义或额外缺陷按既有停止规则报告，不扩大本轮修改范围。现有纯函数测试不证明挂载页面接线，沿用 AC-02/03 与 `C011 导航来源返回与剧集唯一入口`；计划测试层级仍为“纯函数”，编译和真实浏览器是既有补充验收，不新增追溯行或测试装置。
  4. 修复后先运行 `npm --prefix frontend run build`，再运行 `npm --prefix frontend run test -- src/features/navigation/returnLocation.test.ts`；记录实际命令、原始输出和退出码，任一失败即停止。通过后在已授权隔离浏览器环境按原 T05 验收全部 AC-02/03，特别实际点击 AssetCard 的图片任务链接及 ScriptEditor 的资产/分镜任务链接，核对返回到同一集 assets/script tab 及原 search/hash，无额外 mutation；不以纯函数通过替代浏览器接线，不另行授权真实 GPU 生成或伪造浏览器通过证据。
  5. 上述检查通过后允许一次新的完整 G：`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T05 -EvidenceLabel <本轮唯一标签>`，完整 pytest 使用新的仅迁移隔离库/DATA_DIR，保留原次失败日志与资源，不从失败 G 中间续接或复用其通过片段冒称整轮通过。任一门槛失败停止，未全部验收前 T05 不勾选、不回填成功、不提交、不进入 T06。全部完成后仅按原逐 task 授权提交 T05 已验收改动，不 stage .work 或夹带 T02 依赖变更；报告命令/输出/退出码、浏览器证据、删除项及 commit 状态。

  **2026-09-07 T05 build 尚未启动的执行补充：** `.work/c011/T05-scopefix-build-launcher-error-20260907_140000.log` 记录 PowerShell 字符串实例误用 `.concat()`，导致日志路径为空，Tee-Object 参数绑定失败，`PROCESS_RESULT=BUILD_NOT_STARTED`。其中 `EXIT_CODE=0` 不能归属未启动的 npm，也不能作为构建证据。保留该日志。授权执行尚未启动的原定 build，不新建启动器：在仓库根通过终端工具直接执行 `& npm.cmd --prefix frontend run build`，紧接着保存 `$buildExitCode = $LASTEXITCODE`，输出该值并以 `exit $buildExitCode` 结束本次命令；保留工具原始输出和已结束进程的退出码，不用临时 Tee-Object 管道或日志文件名包装阻挡命令。后续完整 G 继续使用既有装置持久化证据。build 实际非零则停止；通过后依上一裁决继续定向测试、浏览器与新批次 G。本补充不追认此前 build 成功，不修改产品 spec、不扩大生产修复范围。

  - 2026-09-09重验：当前HEAD的 `returnLocation.test.ts` 为5 tests passed/exit 0，作用域审计与命令失败记录见 `.work/c011/T05-scope-audit-20260909.log`，原T05真实浏览器记录在相关AssetCard/ScriptEditor与配置未变化条件下精确复用；T34/T38的当前共享入口/页面证据另行引用。T39阶段完整G `.work/c011/T37-t37apparatus20260909_142315-test.log`覆盖当前受测代码的frontend/build/Alembic/backend/diff检查，未重复同输入G。

  **2026-09-07 需求方授权 T05 回归门槛中的 C009 stub 屏障窄修正：**

  - 证据与范围：G 的 `.work/c011/T05-t05scopefix20260907_1410-full-pytest.stdout.log` 记录 `1 failed, 345 passed in 138.73s`，退出码文件为1；相对C010归档基线backend无diff。既有 `/prompt` stub 先 set 屏障、再发送响应、最后 finally 记录 submit，WS线程有机会先记录ws。C011 T01/T02旧日志分别记录346 passed，不能证明该竞态不存在。当前失败保留，不能靠无修复重复跑绿消除。
  - 交付：Luna 仅按 AGENTS.md 本次例外调整 `_LifecycleHTTPHandler.do_POST`，将屏障释放置于本次 `/prompt` 响应成功及 submit 记录入队之后；明确记录成功标记在何处置位，验证发送/记录失败不放行。每次HTTP请求只记录一次，不改变任何测试断言或生产代码。该授权取代本文件此前对这一个函数的禁止修改限制，不类推到其他位置。
  - R：无；PRD：§6.2（gen_clip_video 流水线）、§6.3（显存分时）；计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C009 GPU/Comfy 资源生命周期、取消与失败：cache miss/hit 的 wake/chat/sleep/upload/submit/WS/history/view/free 精确顺序，vLLM/Comfy 跨组件活跃区间不重叠，各安全点取消、interrupt best-effort、主错误与 cleanup/free 双保留`；以及 `C011 范围回归与文档提交一致性`。现有行已包含失败用例，无新增测试行或用例。
  - 验收：人工逐字审计该文件diff仅在授权函数内，所有断言保持原文，屏障释放在记录之后形成明确同步关系，不依靠时间概率。运行 `powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T05 -EvidenceLabel <本轮唯一标签> -TargetPytest tests/task_system/test_c009_resource_lifecycle.py`，定向该文件全部用例及随后完整pytest分别使用新的隔离库/DATA_DIR，保留完整命令/输出/真实退出码；这不是对旧失败批次的重试。不得为证明稳定而无目的循环重跑；通过依据包括修复的同步关系、原断言及本轮真实运行结果。T05原定浏览器/其他验收仍需齐全才能勾选并按授权提交，不能进入T06或把新通过改写为旧批次通过。

- [x] **T06 移除剧集重复入口**
  - 依赖：T05。
  - R：无；PRD：§2.1(3)、§9、§11 M5。
  - 交付范围：只删除 ProjectPage 的“进入集工作区”重复 Link；保留原集标题 Link 和独立编辑/删除按钮。删除前 git blame 定位用途，记录精确删除项，不扩大为删卡片或改路由。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 导航来源返回与剧集唯一入口`。
  - 验收方式与命令：`rg -n '进入集工作区' frontend/src` 应无匹配（rg exit 1 为预期）；G；人工鼠标和键盘进入正确集，取消/确认编辑删除仍按原语义，点击操作不进入集。
  - 验收归属：AC-04；低影响重复展示删除不新增自动测试，替代方式为上述真实操作。

- [x] **T07 统一视觉变量与应用壳**
  - 依赖：T03、T05。
  - R：无；PRD：§2.1、§9、§11 M5。
  - 交付范围：在 styles.css 定义并消费 spec §3 token，改 AppShell/PageTitle/BackendStatus 的排版、导航、玻璃面板、CTA、焦点与 reduced-motion。保留品牌和健康诊断语义。集中替换对应旧色值，禁止为了主 CTA 数量隐藏原功能；各页业务区域在后续明确 task 收口。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`。
  - 验收方式与命令：G；在四个视口人工检查 header/背景/标题/health/导航的计算样式、无远程字体请求、对比度、换行和键盘焦点；输出每个视口截图。
  - 验收归属：AC-05/06/07 的壳与共享基础样式部分；本 task 不勾全页验收完成。

  **2026-09-09重验：** 当前T07受测文件在T35实现提交后无变化；`.work/c011/T07-current-scope-audit-20260909.log`记录token/焦点/响应式/reduced-motion/字体规则静态核对与`git diff --check`均exit 0。T35 `.work/c011/T35-isolated-browser-acceptance-20260909.log`精确覆盖当前壳的两主题四视口计算样式、根clientWidth=scrollWidth、键盘焦点、无远程字体与实际截图；T37 `.work/c011/T37-t37apparatus20260909_142315-test.log`按最新频率规则覆盖当前代码的前端/build/Alembic/backend/diff G，未重复同输入G。原失败日志保留，未扩大为全页AC验收。

- [x] **T08 整理项目首页和剧集列表视觉**
  - 依赖：T06、T07。
  - R：无；PRD：§2.1(1,3)、§9、§11 M5。
  - 交付范围：只改 HomePage/ProjectPage 的布局与展示样式：项目/剧集卡片、创建和编辑表单、空态入口、标题层级、响应式网格。保留风格选择、CRUD、确认和标题导航；不增加 Hero 生成/风格市场/作品流。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工按 spec §4.1 两页清单执行创建、编辑、取消、确认删除与导航，记录正式请求；四视口根无水平溢出、按钮可见、空态不造假。
  - 验收归属：AC-05/06/07/08 对这两页的完整切片。

- [x] **T09 整理设置页视觉**
  - 依赖：T07。
  - R：R11；PRD：§2.1(2)、§3.2、§3.5、§9、§11 M5。
  - 交付范围：仅整理 SettingsPage 诊断、风格表单和四模板编辑器布局/样式。长模板/hash/message 可读，诊断刷新与保存保持各自状态；保留所有字段和按钮、返回来源入口，不改模板正文或 API helper。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工逐项风格 CRUD/冲突显示、四模板读取和显式保存、诊断刷新、真实 unhealthy/error 呈现；四视口检查编辑器与长 hash 不撑破页面。普通后端真实 health 不可用时该验收保持未完成。
  - 验收归属：AC-05/06/07/08 的设置切片；C012 正式模板安装不属于此 task。

- [x] **T10 整理集壳与剧本页视觉**
  - 依赖：T07。
  - R：R1、R2、R3；PRD：§2.1(3,4)、§3.1、§3.2、§9、§11 M5。
  - 交付范围：只整理 EpisodeWorkspacePage 的上下文标题、返回项目、四 tab、剧本编辑区和 impact 确认展示。保留 generated revision 角标、字数约束、两生成按钮、任务链接及现有 mutation 处理，不改生成/确认/token/去重语义。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工四视口浏览四 tab 并完成剧本编辑保存/取消、影响预检显示实际删除数量、取消确认不提交；逐项对照原路径/body。实际生成/取消竞态仍由既有回归与 T23 验证，不能以本 task 的排版检查替代。
  - 验收归属：AC-05/06/07/08 的集壳与剧本展示切片。

- [x] **T11 整理资产页视觉与媒体布局**
  - 依赖：T07。
  - R：R4、R11；PRD：§2.1(5)、§3.2、§3.5、§9、§11 M5。
  - 交付范围：只整理 AssetPage 的资产表单、意见输入、当前图和画廊布局，保留 project 级范围、旧剧本提示、上传/current/删除/seed/DEBUG。复用现有同步与 action，禁止视觉重构顺带重写资产队列/请求。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工四视口按 §4.1 资产清单逐项操作 CRUD、上传、切 current、非 current 删除；对照原 body、显示完整 string seed、DEBUG 由响应决定，图片比例不裁切内容。
  - 验收归属：AC-05/06/07/08 的资产切片；图片生成业务成功不由 fixture 证明。

- [x] **T12 整理分镜页视觉**
  - 依赖：T07。
  - R：R5a；PRD：§2.1(6)、§3.2、§3.4、§9、§11 M5。
  - 交付范围：只整理 ShotsPage 镜头卡片、文本/时长/绑定编辑区、changed 与场景数警示区域。保留原序和全部字段，禁止新增镜头增删/排序。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工四视口保存分镜字段/绑定、观察原 API 和零/多场景提示；changed 样式在 T14 统一，但当前业务标记不得消失。
  - 验收归属：AC-05/06/07/08 的分镜切片。

- [x] **T13 整理导演台视觉与窄屏布局**
  - 依赖：T07。
  - R：R5、R5a、R6、R7、R8、R9、R10、R11、R12；PRD：§2.1(7)、§3.2-§3.5、§9、§11 M5。
  - 交付范围：只调整 DirectorPage 展示与 director 样式：三轨同一滚动容器和列定义、详情窄屏下移、preview/slot/take/输入区视觉。保留 directorModel/directorSync 原业务决策/同步接线、所有 soft warning/disabled 条件、DEBUG/媒体路径和比例。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/director`；G；人工四视口比较三轨列与 duration 比例、滚动对齐；按 §4.1 Director 清单操作原 preview/create、设置、槽位、take/current/delete，记录每项入口和请求不变。
  - 验收归属：AC-05/06/07/08 的导演台切片；不声称真实视频生成链路在本 task 重新验收。

- [x] **T14 统一既有新鲜态与生成态展示**
  - 依赖：T10、T11、T12、T13。
  - R：R8、R12；PRD：§2.1(4,6,7)、§3.2、§3.3、§3.4、§9、§11 M5。
  - 交付范围：最小共享状态文案/Badge，仅消费已知状态；新增独立 `frontend/src/features/status/statusPresentation.test.ts`，把 Shots/Director 的标签统一到 spec §4.2，并保持剧本/资产旧剧本原文、R8 黄色、R12 已删原文。不把业务 freshness 判定迁入通用组件。
  - 计划测试层级：纯函数。
  - 追溯行：`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/status/statusPresentation.test.ts`；G；穷举 normal/changed、五种生成态×fresh/stale 和 null/旧/当前 revision 展示，人工确认 generating+stale 共存且 stale 本身不禁用。
  - 验收归属：AC-09 完整；纯函数只证明文案/状态投影，页面集成由人工与 T24 补足。

- [x] **T15 统一全局加载错误空态与媒体失败展示**
  - 依赖：T08、T09、T10、T11、T12、T13。
  - R：无；PRD：§2.1、§5 通用、§9、§11 M5。
  - 交付范围：整理 ApiErrorMessage/EmptyState 及各页呈现接线：主错误直显原 message、code 另列；loading/error/empty 区分，长错误换行；现有媒体 onError 在真实页面可见。保留原业务表单和动作，缺数据不渲染假卡片，不增加自动重试或业务 fallback。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全局异常空态与媒体错误呈现`。
  - 验收方式与命令：G；按 AC-19 对 §4.1 全页逐一人工制造加载、空数据、读取失败、动作失败；媒体页另检查损坏响应。浏览器网络调试的阻断/响应替换证据标记为受控外部输入，与普通成功通路分开。
  - 验收归属：AC-19；Task 页异步/协议自动验证由 T19/T21 提供，本 task 不替代。

  **2026-09-09重验：** `.work/c011/T15-current-scope-audit-20260909.log`保留一次rg参数顺序错误及更正后的只读源码核对。当前普通隔离批次`.work/c011/T38-ordinary-browser-20260909_143450.log`逐页记录正常、空态、后端停止读失败、资产动作失败、图片/视频失败与文件恢复的实际观测；受控生成证据单独归属T38，不替代普通错误矩阵。T37完整G按最新频率规则覆盖当前代码，未重复同输入G。

- [x] **T16 接入任务过滤读取客户端并验证既有 API 窗口**
  - 依赖：T02、T04。
  - R：无；PRD：§2.1(8)、§5 任务、§11 M5。
  - 交付范围：扩展 api/tasks.ts 的 listTasks 查询参数，仅允许现有 status/type/limit，复用 parser。新增 `backend/tests/api/test_c011_task_listing.py` 通过生产 GET 与真实 PostgreSQL 验证过滤先于 limit、默认50/最大100、id降序、空数组和非法 query 422；不改 backend/app 或既有 test_tasks.py。
  - 计划测试层级：API 集成。
  - 追溯行：`C011 任务列表过滤与有限历史`。
  - 验收方式与命令：`python -m pytest -q tests/api/test_c011_task_listing.py`（cwd=backend，先用 T01 装置准备新的定向库）；G。混合 fixture 超过100，失败/终态置于未过滤最新50之外，证明不是缓存切片假过滤。
  - 验收归属：AC-10 的正式 API 窗口与客户端边界；页面控件在 T17。

- [x] **T17 接入任务过滤控件与有限历史展示**
  - 依赖：T07、T16。
  - R：无；PRD：§2.1(8)、§5 任务、§9、§11 M5。
  - 交付范围：TasksPage 增加 status/type/20-50-100 控件、进行中/历史分组和窗口说明、空结果文案；选全部省略对应参数，组内 id DESC。只提取本页必要的查询/分组纯函数并新增 `frontend/src/features/tasks/taskList.test.ts`，不加分页/搜索/总数。每次过滤使当前请求代次变化，为 T18 接入事件刷新。
  - 计划测试层级：纯函数。
  - 追溯行：`C011 任务列表过滤与有限历史`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskList.test.ts`；G；普通浏览器选控件并核对实际 GET、匹配集合/数量/组别/空态。同步在普通顺序下可用，竞态完整验收单列 T18。
  - 验收归属：AC-10 的控件/分组/窗口说明完整；T18 前不能宣称 AC-16 完成。

- [x] **T18 落实任务中心列表与详情的 WS 权威同步**
  - 依赖：T02、T17。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§9、§11 M5；D-008。
  - 交付范围：把 TasksPage 已有同步按需整理到 features/tasks，实际页面消费同一协调器。明确初连/重连缓冲、过滤代次/socket身份、未知详情去重、terminal替代读取、列表窗口补足、过期请求不写状态、最新失败可见、卸载清理与无轮询。新增独立挂载 TasksPage 的 `frontend/src/features/tasks/taskObservation.test.tsx`；不用测试副本替代生产 action/parser。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务中心 REST/WS 同步与过滤竞态`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskObservation.test.tsx`；G；deferred+FakeSocket 逐项 AC-15/16/17：初始/重连顺序、过滤A/B、列表/详情过期补读、同时未知事件、终态去重、idle零GET、1/2/5/10秒重连和卸载。GET账本由真实 fetch stub 记录。
  - 验收归属：AC-15/16/17 完整；输出明确仅 DOM/传输 mock，真实进程见 T22/T23。

  **2026-09-09重验：** 当前定向命令 `npm --prefix frontend run test -- src/features/tasks/taskObservation.test.tsx` 退出码0，1 file/5 tests passed，原始输出见 `.work/c011/T18-rerun-current-20260909.log`。测试继续验证生产TasksPage/观察协调器在DOM与传输mock中的socket-first、事件缓冲/去重、终态替代、过滤/重连/卸载边界；真实跨进程通路仍引用T22/T23，不以本定向测试冒称。

- [x] **T19 接入任务详情与严格错误呈现**
  - 依赖：T15、T18。
  - R：无；PRD：§2.1(8)、§5 任务、§9、§11 M5。
  - 交付范围：TasksPage 可展开具体 task 正式详情，完整时间/错误与 request_id 展示；接线 parseTaskResponse/parseTaskEventResponse 的可见失败路径，状态/进度/ID/extra字段不能强转；协议错误关闭该 socket、观察重连成功前错误不消失。新增 `frontend/src/features/tasks/taskBoundary.test.tsx`，挂载真实页面。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务公开边界与可见协议错误`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskBoundary.test.tsx`；G；按 AC-11/18 注入长错误/null时间/取消时间、未知enum/越界progress/非safeID/extra payload/畸形JSON及422/500，断言DOM原文、非法ID零详情GET、没有空列表伪成功。
  - 验收归属：AC-11/18 完整；既有 api/tasks parser 的合法合同不放宽。

  **2026-09-09重验：** 当前定向命令 `npm --prefix frontend run test -- src/features/tasks/taskBoundary.test.tsx` 退出码0，1 file/14 tests passed，原始输出见 `.work/c011/T19-rerun-current-20260909.log`。该挂载生产TasksPage测试继续保留详情字段、错误正文、非法输入/协议错误可见与无伪成功断言；未修改既有测试。

- [x] **T20 接入单任务取消基本交互**
  - 依赖：T19。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§9、§11 M5。
  - 交付范围：新增复用 requestJson/parser 的 cancelTask helper（无 body POST），在 TasksPage 实际按钮接线；每task in-flight、queued/running/已请求/终态按钮状态与等待文案；取消成功后权威读取详情和当前窗口，确认前无成功提示。新增独立 `frontend/src/features/tasks/taskCancel.test.tsx`。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务取消交互与终态竞争`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskCancel.test.tsx`；G；按AC-12遍历状态、鼠标/键盘双击和多task隔离；断言真实helper收到的method/path/body、POST=1、200 running仍显示等待且没有canceled假状态。
  - 验收归属：AC-12 完整；竞争/失败不夹带为未列出的修复，后续T21独立验收。

  **2026-09-09重验：** 当前定向命令 `npm --prefix frontend run test -- src/features/tasks/taskCancel.test.tsx` 退出码0，1 file/3 tests passed，原始输出见 `.work/c011/T20-rerun-current-20260909.log`。保留生产cancelTask/TasksPage的单次无body POST、取消中状态、权威详情/列表读取及多任务隔离断言；竞争场景仍单列T21。

- [ ] **T21 封闭取消竞争错误与当前页面隔离**
  - 依赖：T20。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§9、§11 M5；D-008。
  - 交付范围：落实取消与done竞争、迟到200 running、404/409权威刷新与资源消失、超时未知结果、筛选A/B/展开B/卸载identity。操作错误不被后台GET清除；未知结果确认前禁止再次提交，仅显式刷新或观察重建。新增独立 `frontend/src/features/tasks/taskCancelRaces.test.tsx`，保持T20既有用例不变。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务取消交互与终态竞争`；`C011 任务取消错误与资源消失重建`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskCancelRaces.test.tsx`；G；deferred控制AC-13/14两种胜方与迟到响应，实际DOM/action链证明POST一次、正确task归属、GET次数/路径、无success notice、消失清详情且不污染B。
  - 验收归属：AC-13/14 完整；不修改后端竞争裁决或改既有测试换绿。

- [x] **T22 验证跨进程取消与观察一致性**
  - 依赖：T04、T21。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§11 M5。
  - 交付范围：只新增 `backend/tests/task_system/test_c011_task_observation.py`，以独立被测后端进程、独立HTTP/WS客户端和独立DB只读连接，验证生产取消/队列/事务/发布的真实关系。测试在该新增文件内通过create_app/TaskQueue正式seam建立自身进程fixture，禁止依赖未提交的.work驱动，断言生产可观察行为而非装置自检输出。屏障控制queued取消、running意图到安全点、done先提交；不引入文件/marker业务副作用或新锁。
  - 计划测试层级：任务系统 mock；跨进程/资源生命周期。
  - 追溯行：`C011 跨进程任务取消与观察一致性`。
  - 验收方式与命令：`python -m pytest -q tests/task_system/test_c011_task_observation.py`（cwd=backend，新隔离定向库）；G；逐task记录barrier reached/released、POST/REST/WS/DB值和子进程退出；AC-21期望全部满足。mock指handler/外部服务，跨进程指实际后端与客户端。
  - 验收归属：AC-21；这是定向生产状态观察测试，不是M6重启/全资源生命周期验收，不证明Comfy实际中断。

- [ ] **T23 完成任务中心真实浏览器受控走查**
  - 依赖：T04、T21、T22。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§9、§11 M5。
  - 交付范围：不改代码；浏览器连接T04受控任务运行时，使用真实TasksPage、生产HTTP/WS和PostgreSQL，完成过滤历史、取消、等待/终态、完整错误、重连、返回来源。记录与普通生产handler的差异，不把浏览器有一条running当成真实Comfy queue_running证据。
  - 计划测试层级：任务系统 mock；跨进程/资源生命周期。
  - 追溯行：`C011 任务取消交互与终态竞争`；`C011 任务取消错误与资源消失重建`；`C011 任务中心 REST/WS 同步与过滤竞态`；`C011 验收装置与生产通路归属`；`C011 跨进程任务取消与观察一致性`。
  - 验收方式与命令：人工浏览器按AC-10..18、AC-20/21逐项执行，使用T04管道精确放行；保存实际网络/WS、截图和独立DB对照；G。若浏览器链路未经过被测page则此task失败，DOM mock结果不能代替。
  - 验收归属：任务中心用户→页面→真实API/DB/WS完整观察链；handler为mock，不声称真实生成或GPU。

- [x] **T24A 补齐受控生成按钮验收的运行配置前置（2026-09-08裁决新增，先于T24补验）**
  - 依赖：T03、T04、T23；不依赖T24完成。
  - R：无；PRD：§7、§12.2（干净测试库示例）、§11 M5；按spec §7.4执行，正式四模板生产部署仍归C012。
  - 交付范围：不改代码、不新建脚本；用既有装置准备新受控库/DATA_DIR/证据批次，启动前设置DEBUG_PROMPTS=true，确认T04的四类handler与health client替代及进程身份。先执行现有ui_fixture prepare/verify，再核对本轮OpenAPI，通过正式设置API安装spec §7.4的四行人工模板并GET逐字回读。记录四类按钮所需合法target与确认条件，避免同target任务互相冲突。此项只完成前置，不点击生成按钮或伪称到达barrier。
  - 计划测试层级：API 集成；跨进程/资源生命周期。
  - 追溯行：`C011 验收装置与生产通路归属`；AC-25已完成spec→现有行覆盖检查，无缺行，不新增仓库测试。
  - 验收方式与命令：`python .work/c011/ui_fixture.py --help`、`python .work/c011/ui_fixture.py prepare`、`python .work/c011/ui_fixture.py verify`（通过现有明确环境变量选择同一新受控批次）；正式设置页逐项保存或直接用既有HTTP客户端发送四次 `PATCH /api/prompt-templates/{key}`（body仅content，精确内容见spec），再 `GET /api/prompt-templates`；每次200且key/正文逐字一致，verify exit=0并有DEBUG字段；独立只读查询current_database()对照，进程命令/显式配置证据确认受控模式；G（Task=T24A，唯一EvidenceLabel，完整pytest另建仅迁移库）。原失败日志及旧资源保留。
  - 产出证据：只记录配置前置通过与环境身份，生产源文件/迁移/工作流/正式模板无diff；人工模板不得装到普通服务或用户库。未达到条件保持本项未完成及T24阻塞。

- [ ] **T24B 完成白紫亮色与暗色语义样式**
  - 依赖：T07、T15、T23；当前T24未完成不阻塞这项明确授权的修复。
  - R：无；PRD：§9、§11 M5；追加来源：需求方2026-09-08走查第1项。
  - 交付范围：仅styles.css。逐项交付①复用根data-theme选择两套完整token，暗色基线保留、亮色逐项采用spec §3.3；②覆盖header/状态栏/页面/表单/select/checkbox/按钮各状态/错误/DEBUG/scene与两轨/预检/媒体空态；③移除相应硬编码暗色及颜色滤镜，原媒体不反色；④双主题color-scheme/焦点/对比度与320px主题控件预留布局。此项不接线主题状态/存储，后者由T24C单独交付；不安装样式库/字体/图标包。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 明暗主题与偏好存储`、`C011 全站视觉与响应式可访问性`。
  - 验收方式与命令：`git diff -- frontend/src/styles.css`；`rg -n -- 'data-theme|--color-|--shadow-|color-scheme|filter:|#[0-9a-fA-F]{3,8}|oklch\(|rgba?\(|@media|focus' frontend/src/styles.css`；人工逐项对照§3.1/§3.3的token值、作用域和§4组件消费选择器，记录每项对应规则、无对应暗色硬编码/媒体反色、响应式与焦点规则保留。`npm --prefix frontend run build`；G（Task=T24B）。检索命中颜色定义本身不是失败，须区分主题定义与组件硬编码；不新建检验脚本或镜像测试。已有G只有在确认其后实现/依赖/装置没有变动且原生退出码完整时才可沿用并引用原证据，不能把文档调整称为重跑通过；发生相关改动后执行新批次G。
  - 验收归属：仅CSS交付与回归证据，不是AC-26或AC-05/07的渲染通过。双主题真实组件、实际合成背景对比度和320px根溢出检查完整移交T24C，在T24D前完成；最终T24仍全量检查。原DevTools安全停止证据保留，不改写其结果。静态审计和build/G均通过后才可勾选本项；本次裁决不代执行者勾选。

- [ ] **T24C 接线主题切换、偏好存储与页面状态保持**
  - 依赖：T24B、T02。
  - R：无；PRD：§9、§11 M5；追加来源：需求方2026-09-08走查第1项。仅浏览器外观偏好，不新增后端设置项。
  - 交付范围：①新增features/theme/theme.ts，单一实现dark/light解析、根属性/theme-color应用及localStorage读写的明确错误语义；②main.tsx在首次React挂载前调用一次初始化，index.html同步暗色默认theme-color，禁止重复bootstrap；③新增components/ThemeSwitch.tsx并由AppShell接线可访问的两个按钮及存储提示，styles.css补控件布局；④新增独立features/theme/theme.test.ts覆盖无/合法/非法值与存储异常的规定结果；⑤新增独立features/theme/themeWiring.test.tsx，jsdom挂载实际AppRoutes/AppShell/主题控件和实际页面，mock仅HTTP/WS边界，验证草稿/选择/筛选保持、在途生成请求精确一次及响应处理；⑥收口从T24B移交的双主题渲染检查，若发现与§3.1/§3.3不符的主题颜色、焦点或窄屏主题控件布局，只在styles.css内修正并重新验证，不提前实施T24D-F。不得修改既有测试，不给路由/页面增加theme key，不请求主题API，不新建全局状态框架。
  - 计划测试层级：纯函数；任务系统 mock（AC-28含在途与重放竞态）。
  - 追溯行：`C011 明暗主题与偏好存储`、`C011 全站视觉与响应式可访问性`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/theme/theme.test.ts src/features/theme/themeWiring.test.tsx`；`npm --prefix frontend run build`；G（Task=T24C）。人工真实按钮切换、刷新/同origin新标签、320px键盘操作并对照data-theme/color-scheme/theme-color/aria-pressed；在明暗两主题逐页检查§4全部组件、表单/状态/错误/DEBUG/预检/媒体空态，并记录实际合成背景对比度满足§3.2阈值、320px根scrollWidth不超过clientWidth、媒体无反色。使用正式主题按钮，不通过DevTools临时改根属性模拟功能；进入浏览器前须满足spec §7.4的安全URL确认条件。自动用例以原页面实际请求账本核对零额外mutation/WS，不手填期望账本。各页面草稿/镜头Clip选择/筛选独立场景，不构造同页不可达状态；在途生成选择现有允许提交的页面。
  - 验收归属：AC-26/27/28及AC-05/07双主题视觉切片；使用既有DOM装置，无新验收驱动。mock存储异常证据与真实浏览器正常存储分别说明；媒体生成/真实GPU不在本项。移交的视觉检查全部通过后才可勾选并进入T24D，不能只凭自动测试放行或留到最终T24才发现；安全URL条件未满足时保留未完成状态，不绕过安全限制。

- [ ] **T24D 统一已有返回入口为左箭头控件**
  - 依赖：T24C、T05。
  - R：无；PRD：§2.1(1-3,8)、§9、§11 M5；追加来源：需求方2026-09-08走查第2项。
  - 交付范围：①新增components/BackNavigation.tsx共享一个本地SVG和Link/button展示，保留实际元素语义；②在AuxiliaryPageReturn、ProjectPage、EpisodeWorkspacePage正常/错误/无来源分支替换原文本外观；③styles.css统一40×40/20×20图标、focus/hover及两主题；④aria-label/title继续使用原目的地名称，非法来源提示保留。源代码检索其余相同返回文案若无实际导航入口不修改；不动路由决策、目标/state/replace，不添加navigate(-1)。替换前git blame，报告准确移除的可见文字及新可访问名称。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 统一后退图标与目标保持`、`C011 导航来源返回与剧集唯一入口`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/navigation/returnLocation.test.ts`；G（Task=T24D）；`rg -n '返回项目首页|返回项目|返回刚才页面' frontend/src`人工核对每项作为名称/title保留，不能要求零匹配。真实浏览器两主题检查40px尺寸、焦点、Link Enter与button Enter/Space、原目标/replace/search/hash及无来源/已删实体；不新增低影响图标的镜像测试，实际交互补足接线。非空非法Router state分支按spec §9的2026-09-08裁决采用组合证据：上述既有非法输入测试通过；用`git diff <T24D实施前记录的实际基线> -- frontend/src/features/navigation/returnLocation.ts frontend/src/components/AuxiliaryPageReturn.tsx`审计判定/提示/目标/replace不变，人工完整读取BackNavigation.tsx与对应CSS确认Link props透传和无非法分支专属渲染；补齐同一共享Link的两主题真实尺寸/名称/焦点/键盘及辅助返回replace证据。基线须引用实际记录，不杜撰commit；记录这三部分各自能证明的范围，不声称IAB动态注入已完成。
  - 验收归属：AC-29、AC-02/03；图标统一不表示返回行为统一为历史后退。原history不可用证据保留，不以query returnTo或无state冒充非法分支；不新增注入脚本、生产调试入口或测试文件。组合证据全部齐备且其余本项验收通过后可回填追溯、勾选并按原依赖进入T24E；判定逻辑/导航语义变化或存在非法分支专属样式时本裁决不适用。最终T24对该分支沿用同一证据方法，其他浏览器门槛不变。

- [x] **T24E 修复资产勾选行与通用表单样式冲突**
  - 依赖：T24D、T12。
  - R：R8（参考候选上限/警示保持）；PRD：§3.2/§3.3（绑定编辑修订与级联）、§3.4 R8、§9、§11 M5；追加来源：需求方2026-09-08走查第3项。仅对齐样式本身R：无；R8行为不变。
  - 交付范围：①styles.css将文字输入样式限定于实际文本/数值输入，避免checkbox/radio/file继承文本框padding/min-height；②修复`.form-grid label`与`.shot-asset-option`的specificity，按spec §3.4设置18px框、8px间隔、40px可点击行及多行第一行对齐；③检查并修复同因影响的Director参考候选/镜头勾选行；④仅在布局必须时调整ShotsPage/DirectorPage的label文字容器class，不改事件、draft.asset_ids、API、上限/禁用/保存逻辑。不得大范围!important覆盖、定高裁字或拆散label关联。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 资产勾选行对齐`、`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：`npm --prefix frontend run build`；G（Task=T24E）；真实浏览器两主题四视口测checkbox与首行Range行盒中心差≤1px，检查长中文/英文名换行和输入框/上传控件未退化；分别点击checkbox、名称及Space各一次，观察选中集合和一次保存PATCH body/正式GET回读与原合同一致，取消/未保存行为不变；参考候选上限和R8提示保持。布局不新增jsdom几何断言，以实际计算样式/坐标/网络记录验收。
  - 验收归属：AC-30；现有fixture不能提供长名称时仅经本轮隔离库正式资产编辑API准备输入，不新增驱动或生产特判。

- [x] **T24F 增宽导演台镜头并保持共同时间比例**
  - 依赖：T24E、T13。
  - R：R5、R5a、R8（原选择约束保持）；PRD：§3.4、§9（一带两轨一板）、§11 M5；追加来源：需求方2026-09-08走查第4项。宽度计算本身R：无；选择/连续/同场景规则保持不变。
  - 交付范围：①新增features/director/directorTrackLayout.ts仅计算spec §3.5的共同最小宽度，输入沿用现有已验证正duration_est，空数组单独处理；②DirectorPage把同一布局宽度施加于三个轨道共同内容，保留projection.gridTemplateColumns与span/gap/选择接线；③styles.css取消本区域仅760px压缩的约束，保证最短列192px、gap8px、局部滚动与焦点可见，metadata/原因换行可读；④新增独立features/director/directorTrackLayout.test.ts覆盖空/单列/不等时长/多列/小数时长计算，既有directorModel及其测试不改。禁止独立列钳制/等宽/时间轴缩放控件或扩大为虚拟化改造。
  - 计划测试层级：纯函数。
  - 追溯行：`C011 导演台轨道可读宽度与比例`、`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/director/directorTrackLayout.test.ts`；`npm --prefix frontend run test -- src/features/director`；G（Task=T24F）。真实浏览器两主题四视口/200%下测最短列≥192px、三轨边界误差≤1px、duration比例及Clip跨列间隙；横向滚动/键盘聚焦远端控件，观察根无溢出、主题切换scrollLeft与选择保持；原选择/预检/创建/选Clip操作仍使用原合同。宽度纯函数测试不冒称真实CSS grid对齐。
  - 验收归属：AC-31；与theme在途状态保持联检AC-28，最终全页结论在T24收口。

- [ ] **T24 完成全站响应式视觉与功能保留验收**
  - 依赖：T29–T39修复及原退回任务重验完成；T05-T15、T23、T24A、T24B、T24C、T24D、T24E、T24F。需求方2026-09-08追加后须对最终实现重新验收，不能沿用旧暗色走查作为整体通过。
  - R：R1、R2、R3、R4、R5、R5a、R6、R7、R8、R9、R10、R11、R12；PRD：§2.1、§3.1-§3.5、§5、§9、§11 M5。
  - 交付范围：不夹带代码或装置改动；使用T03普通生产后端/fixture逐页执行spec §3视口矩阵、§4.1每项功能入口、AC-02..09/19/22。检查四类生成按钮的现有请求接线时单独使用T04受控handler模式并明确不证明实际生成；普通模式不得触发未授权GPU流水线。未满足项记录为失败并停在本task。
  - 计划测试层级：不新增自动测试；任务系统 mock；跨进程/资源生命周期。前者用于视觉，后两者用于受控生成接线。
  - 追溯行：`C011 导航来源返回与剧集唯一入口`；`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`；`C011 全局异常空态与媒体错误呈现`；`C011 全局浏览器功能与视觉验收`；`C011 验收装置与生产通路归属`；`C011 明暗主题与偏好存储`；`C011 统一后退图标与目标保持`；`C011 资产勾选行对齐`；`C011 导演台轨道可读宽度与比例`。
  - 验收方式与命令：明暗两主题分别执行四视口、Tab/Enter/Space与计算对比度；另执行`rg -n -A 30 -B 3 'prefers-reduced-motion' frontend/src/styles.css`和`rg -n 'transform:|animation:|animation-|transition:' frontend/src/styles.css`，人工逐项核对reduce规则覆盖所有现有悬浮位移、保留禁用循环装饰动画与缩短过渡的规则，记录位置/覆盖清单而非只判字符串存在；逐页逐状态记录实际结果、截图及method/path/body，并覆盖AC-26..31。先运行`npm --prefix frontend run test -- src/features/theme`、`npm --prefix frontend run test -- src/features/director`，再G。自建自动浏览器脚本若尚无前置task，不可临时补进此task。
  - 验收归属：AC-05..08/22与AC-26..31全页结论在这里收口；不得只交首页或单一主题截图就勾全站。至少记录8类页面（首页/项目/剧本/资产/分镜/导演台/设置/任务中心）×2主题×4视口共64个基础页面组合，另记录空/错/DEBUG/候选/状态变体；全页原生200%、动态reduced-motion按spec §7.4明确记为未验证且本次不阻塞，不能填为通过。不是只凑截图数：每格含根溢出/入口/文字焦点可读性结果及证据；任一失败不勾选。四类生成按钮在T04受控模式每主题各验一次，普通模式不触发GPU；全页保存/删除/选用等按原§4.1合同。

  **2026-09-08 Astra 对 T24 部分验收与补验路径的裁决：**

  1. T23已完成，不阻塞进入T24；T24当前未完成，禁止进入T25。commit `68ca536c169491b2eb030f8d83a265dfd7fe78aa` 仅证明文档曾提交，不证明门槛全过；保留历史commit，不reset/amend掩盖。当前checkbox保持未勾，追溯/NOTES追加更正说明普通证据有效但非整项通过；按既有文档修正授权单独提交状态更正，不把更正commit称作T24完成，不夹带未验收代码。
  2. 保留普通四视口/键盘/来源/对比度/局部滚动和G日志作为对应切片证据。720×450不是原生200%；CSS静态规则不能证明动态reduced-motion；409且无task_id/barrier不能证明生成按钮成功接线。新批次verify成功不覆盖旧DEBUG失败。旧通过证据仅在对应源码与配置不变且清楚标注模式/批次时沿用；配置变化影响的项目必须在新批次补验。
  3. 先完成T24A，随后四类生成按钮分别走真实页面→正式REST校验/入队→生产队列→受控handler：生成资产、生成分镜、资产图片、片段视频。每类保存实际method/path/body/202/task_id与同id的BARRIER_REACHED、REST/独立DB记录；分镜沿用原impact确认，其他前置按现有UI/API合同满足。实际创建数据/文件的生成handler被替代，不能以受控done冒称真实产物；不改模板校验、不直插Task跳过按钮、不在普通模式触发GPU。
  4. **2026-09-09更正，替代本项原有原生200%/动态reduced-motion补验阻断要求：** 按spec §7.4与更新后的AC-06/07执行。保留两主题四视口、键盘、对比度、功能和受控生成门槛；reduce改用本项明列的源码审计，保留生产样式。全页原生200%与动态媒体响应明确记录未验证、本次不阻塞，不再要求为它们恢复原生浏览器或新增驱动；不把viewport/DPR/静态规则冒称动态通过，不删除原失败证据。完成其余全部验收且追溯明确列出这两项范围限制后，才可勾选T24并进入T25。本次规划修改不代执行者勾选、不自动认定其他门槛通过；不修改既有测试或C012范围。
  5. T24四类受控handler接线的证据归“任务系统 mock；跨进程/资源生命周期”，普通视觉部分仍为“不新增自动测试”；沿用 `C011 既有功能入口与状态呈现不变`、`C011 全局浏览器功能与视觉验收`，并记录 `C011 验收装置与生产通路归属`。不新增自动测试文件，不修改生产/既有测试/配置或夹带驱动；需要装置实现变化先单列前置任务，本裁决仅增加运行配置准备T24A。
  6. 补验命令为原Director定向命令与 `powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T24 -EvidenceLabel <补验唯一标签>`，完整pytest另用新仅迁移库；保留原G成功及后续失败的时间顺序。全部缺项与原要求齐全才回填整项、勾T24并提交。DECISIONS候选无需新增：浏览器内置控制是验收手段，人工模板是现有PRD §7/§12.2与D-014边界下的隔离配置，不变更跨change产品约定。

- [ ] **T25 完成范围追溯与回归审计**
  - 依赖：T24A、T24B、T24C、T24D、T24E、T24F全部完成，且最终双主题T24全部验收通过。T25编号保留，执行顺序延后；不能用旧T24提交/单主题G跳过追加任务。
  - R：无；PRD：§0、§5 通用、§9、§11 M5。
  - 交付范围：核对全部31条AC/追溯/指定用例和最终双主题人工记录；保护基线既有测试，仅允许AGENTS.md明确授权的C011 T05 do_POST窄修正和新增独立测试文件；核对后端生产、schema/migration/workflow/template零变化、无新增业务、无未列装置、无旧暗色证据伪装追加需求结果。只修正文档事实，不修代码或重跑失败到绿。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：按开头验收频率表核对并引用覆盖最终受测输入的完整 G；缺失或相关输入变化时运行 `powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T25 -EvidenceLabel ('closure'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`；`git diff --check`；`git diff --name-status 1ef70e5d5fad245d6e38e1472eaa16ffb523aa59`；`git diff 1ef70e5d5fad245d6e38e1472eaa16ffb523aa59 -- backend/app backend/alembic backend/workflows` 应为空；`git status --short`；人工按基线逐一核对既有test仅允许授权do_POST范围M、其他无M/D、新增用例逐行回填（含本次4条新追溯行）；`rg -n '^\| C011 .*待填' openspec/TRACEABILITY.md` 应无匹配。
  - 验收归属：AC-01/23；范围依据允许文件集，不要求整个change diff为空。


## 2026-09-09 审查修复任务（先于重新验收与固定收尾）

- [x] **T29 保持取消请求跨筛选的所有权**
  - 依赖：本轮spec/tasks/追溯文档已提交；不依赖退回的T28；问题/验收：B01；AC-12/14/16。
  - R：无；PRD：§2.1(8)、§5「任务」、§6.1、§9、§11 M5。
  - 交付：在生产TasksPage中保持取消发起task的在途身份跨status/type/limit查询切换；新窗口仍含该task时不可二次POST，迟到错误仍归该task且不能污染其他task/卸载后的页面。只调整必要的控制器所有权/查询接线，不引入全局状态框架。 生产文件限frontend/src/pages/TasksPage.tsx、frontend/src/features/tasks/taskObservation.ts；独立新增`frontend/src/features/tasks/taskCancelFilterOwnership.test.tsx`实现下述回归，不修改既有测试。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务取消交互与终态竞争`；`C011 任务取消错误与资源消失重建`；`C011 任务中心 REST/WS 同步与过滤竞态`。
  - 验收：挂载实际TasksPage；对同task在途cancel分别切status/type/limit且仍匹配，再鼠标/键盘激活：POST精确1且无body；另一task可独立取消；迟到404/409/网络错误归属不变、离开页不污染。
  - 命令：`npm --prefix frontend run test -- src/features/tasks/taskCancelFilterOwnership.test.tsx`；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T29 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`。原始stdout/stderr/exit保留；定向与G全过后回填本次实际测试ID和证据。

- [x] **T30 让取消确认使用取消后的权威详情**
  - 依赖：T29完成；问题/验收：B02；AC-12/13。
  - R：无；PRD：§2.1(8)、§5「任务」、§6.1、§6.4、§9、§11 M5。
  - 交付：使取消前已发出的详情请求不能消费取消确认、解除提交保护；旧请求完成后合并或补发必要的最新读取，继续维持每task最多一个在途GET；不直接凭取消响应伪造终态。 生产文件限frontend/src/features/tasks/taskObservation.ts；独立新增`frontend/src/features/tasks/taskCancelAuthority.test.tsx`实现下述回归，不修改既有测试。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务取消交互与终态竞争`。
  - 验收：deferred先发详情再cancel，旧queued详情迟到；在最新读取前再次激活时POST仍1、确认状态仍在；后续真实读取分别返回canceled和running+cancel_requested_at，DOM与权威值逐字段相等；读取失败可见。
  - 命令：`npm --prefix frontend run test -- src/features/tasks/taskCancelAuthority.test.tsx`；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T30 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`。原始stdout/stderr/exit保留；定向与G全过后回填本次实际测试ID和证据。

- [x] **T31 按事件与读取先后合并任务详情**
  - 依赖：T30完成；问题/验收：B03；AC-13/17。
  - R：无；PRD：§2.1(8)、§5「任务」、§6.1、§9、§11 M5。
  - 交付：修复旧cached event覆盖后发REST终态；沿D-008现有revision/request身份实现，不添加服务端版本、时间容差或永久事件账本。 生产文件限frontend/src/features/tasks/taskObservation.ts；独立新增`frontend/src/features/tasks/taskDetailEventOrder.test.tsx`实现下述回归，不修改既有测试。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务取消交互与终态竞争`；`C011 任务中心 REST/WS 同步与过滤竞态`。
  - 验收：先running事件后GET done：status=done、progress=1、finished_at精确；反向先GET后terminal事件且旧GET迟到：terminal不回退；断言必要GET数量、无mutation重放、无提前成功通知。
  - 命令：`npm --prefix frontend run test -- src/features/tasks/taskDetailEventOrder.test.tsx`；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T31 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`。原始stdout/stderr/exit保留；定向与G全过后回填本次实际测试ID和证据。

- [x] **T32 重连重建已展开任务详情**
  - 依赖：T31完成；问题/验收：B04；AC-11/15。
  - R：无；PRD：§2.1(8)、§5「任务」、§6.1、§9、§11 M5。
  - 交付：重连后使仍展开的详情从正式GET恢复到最新状态，清楚处理旧缓存与读取失败；保持断线旧数据可见和1/2/5/10秒重连，不添加轮询。 生产文件限frontend/src/features/tasks/taskObservation.ts、必要的frontend/src/pages/TasksPage.tsx详情接线；独立新增`frontend/src/features/tasks/taskDetailReconnect.test.tsx`实现下述回归，不修改既有测试。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务公开边界与可见协议错误`；`C011 任务中心 REST/WS 同步与过滤竞态`。
  - 验收：不卸载实际页面：展开running→WS断开→服务端done/failed/canceled→重连；列表与详情的status/progress/finished_at/error_msg/cancel_requested_at逐字段相等，null时间对应字段显示—、非空时间含时区；长多行错误原文可见；没有重复POST。
  - 命令：`npm --prefix frontend run test -- src/features/tasks/taskDetailReconnect.test.tsx`；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T32 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`。原始stdout/stderr/exit保留；定向与G全过后回填本次实际测试ID和证据。

- [x] **T33 补读远端首次取消意图**
  - 依赖：T32完成；问题/验收：B05；AC-12/17。
  - R：无；PRD：§2.1(8)、§5「任务」、§6.1、§6.4、§9、§11 M5。
  - 交付：已知running任务收到生产已请求取消事件时补读最新详情，补齐取消时间；取消意图不是terminal，沿既有parser/公开事件合同判定，不改后端。 生产文件限frontend/src/features/tasks/taskObservation.ts；独立新增`frontend/src/features/tasks/taskCancelIntentObservation.test.tsx`实现下述回归，不修改既有测试。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务中心 REST/WS 同步与过滤竞态`；`C011 任务取消交互与终态竞争`。
  - 验收：分别无详情在途/旧详情在途接收相同progress的已请求取消事件；最多一个并发GET且旧读完后至多补一次必要读取；最新cancel_requested_at精确呈现、仍running且按钮等待禁用；重复相同事件不重复读取、失败可见。
  - 命令：`npm --prefix frontend run test -- src/features/tasks/taskCancelIntentObservation.test.tsx`；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T33 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`。原始stdout/stderr/exit保留；定向与G全过后回填本次实际测试ID和证据。

- [x] **T34 补齐已删除项目的首页后退入口**
  - 依赖：T33完成；问题/验收：B06；AC-03/29。
  - R：无；PRD：§5「项目」、§9、§11 M5。
  - 交付：ProjectPage真实404错误分支使用既有BackNavigation渲染首页入口；保留原message和既有正常页导航，不新增路由/状态恢复功能。 生产文件限frontend/src/pages/ProjectPage.tsx；独立新增`frontend/src/features/navigation/projectReturnError.test.tsx`实现下述回归，不修改既有测试。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 导航来源返回与剧集唯一入口`；`C011 统一后退图标与目标保持`。
  - 验收：挂载实际AppRoutes与结构化project404；原message、40px共享箭头名称/title返回项目首页同时存在，激活一次到/且无mutation；两主题实际浏览器验证共享控件、Enter/焦点；非法辅助来源继续使用既定组合证据。
  - 命令：`npm --prefix frontend run test -- src/features/navigation/projectReturnError.test.tsx`；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T34 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`。原始stdout/stderr/exit保留；定向与G全过后回填本次实际测试ID和证据。

- [x] **T35 恢复标题字号并修复首页表单窄屏溢出**
  - 依赖：T34；问题/验收：B07、AC-05/06/07。
  - R：无；PRD：§9、§11 M5；字号取spec §3.1，不新增产品决定。
  - 交付：①保留PageTitle.tsx、HomePage.tsx及styles.css的页面角色/字号修复，首页48–80px、工作页28–40px；②按spec §10.4在自有隔离环境复现合法长风格名下首页表单溢出，确认原生select、label及grid收缩通路；③仅在上述文件内修复既有首页表单标记与form-grid/label/文本数字input/select/textarea的必要宽度/网格约束，验证共享消费者。三项逐项列证据，不能夹带其他布局重构、数据截断、业务字段/校验/请求变化；checkbox/file既有合同保留。此前“只许标题选择器”范围由本条明确替代。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`。
  - 验收：先记录原失败和隔离复现的长中文/连续英文风格名、真实选项/选中值、计算grid轨道与表单边界；不得写入或停止用户5173/8000环境。修复后两主题四视口逐页读取h1计算font-size、根clientWidth/scrollWidth与焦点可达性；首页/工作页落入各自字号范围，根无溢出且控件不超容器，至少完整记录320和1440边界。相同长内容必须仍存在并能键盘选择、提交值不变；检查共享form-grid消费者、T24E checkbox18px/label40px/file控件与Director局部滚动不受影响。禁用根overflow隐藏、删长内容、缩小标题或改变视口来掩盖失败。保留旧日志，不新增浏览器驱动或CSS镜像测试。
  - 命令：按T03既有装置准备普通新隔离批次并执行`python -X utf8 .work/c011/ui_fixture.py verify`；正式风格/项目API仅操作本批次fixture；`npm --prefix frontend run build`；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T35 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`；人工按上项记录实际URL/库身份/主题/视口/字号/表单几何及功能结果。旧build只证明当时标题代码可构建，CSS新修改后重新build/G。所有验收通过再勾T35、提交并自动继续T36；本条已授权的布局根因修复无需再次请示。

- [x] **T36 补齐主题切换保持意见与导演选择的自动证据**
  - 依赖：T35；问题/验收：B08、AC-28。
  - R：无；PRD：§9（导演台意见/选择）、§11 M5；需求方2026-09-08主题追加。
  - 交付：只新增`frontend/src/features/theme/themePageState.test.tsx`；复用已有jsdom/HTTP/WS注入依赖，分别挂载实际AssetPage意见、DirectorPage意见、镜头选择、Clip选择场景，不能用手建input或复制页面状态充当生产接线；既有theme测试与生产文件不改。发现真实新实现缺陷先报告，不靠改测试输入绕过。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 明暗主题与偏好存储`。
  - 验收：各自可达场景切亮/暗后草稿/选择保持、Director轨道scrollLeft保留、URL/history不变、mutation/WS新增数=0；已有在途生成用例继续精确一次提交并消费原响应。jsdom的scrollLeft只证明属性保持，几何/滚到远端仍用T24F/T24浏览器记录。
  - 命令：`npm --prefix frontend run test -- src/features/theme`；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T36 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`；回填每个真实用例ID，不仅写测试数量。

- [x] **T37 先交付受控生成请求正文的被动观测**
  - 依赖：T36；问题/验收：B08、AC-08/20/25，装置合同见spec §10.2。
  - R：无；PRD：§5「任务」及生成端点、§6.1、§11 M5；只交付证据通路。
  - 交付：仅调整`.work/c011/task_runtime.py`受控服务入口与其既有self-check，按spec §10.2记录实际method/path/body/status/task_id；原ASGI应用接收正文一次，原响应不替换；不新增生产源码、test endpoint、事件通道、依赖或浏览器驱动。G现有正则已支持T29–T39，禁止为此重复修改启动器。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C011 验收装置与生产通路归属`；`C011 既有功能入口与状态呈现不变`。
  - 验收：独立HTTP客户端经包装入口发送实际无body、{}和含原服务签发confirm_token的请求，日志与发送字节相同、各请求仅一次、原正式响应一致；Task仍来自正式路由/队列，独立只读DB/生产WS对应同id；handler仍标受控；shutdown exit=0且自有端口关闭。
  - 命令：`python -X utf8 .work/c011/task_runtime.py self-check`（新隔离批次）；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T37 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`。自检只验证装置通路，不冒称四按钮的浏览器验证。
  - 2026-09-09补充退回：当前PassiveRequestObserver捕获所有HTTP（包括media响应）并输出完整response_body_b64，超出spec §10.2的四类生成/impact范围，导致PTY大输出淹没关键证据；replay_receive在缓存耗尽时合成http.disconnect也不符合原ASGI透传合同。仅在本既有.work装置修复：非目标请求直接交原应用，命中请求仅旁路观测实际receive/send且不合成事件，保持字节/次数/异常传播；原始stdout/stderr须在进程运行时完整落盘，控制台只读所需短行，不能事后删证据或用输出截断冒充采集。复用标准进程输出重定向与既有控制通路，不新增生产代码、依赖、第二套启动器或HTTP端点。先self-check证明生成body/响应一次透传、非目标媒体正常读取且不打印其正文、真实disconnect不被提前合成、shutdown/端口释放，再G；通过才重新勾选进入T38。

- [x] **T38 补齐双主题四按钮与逐页异常矩阵**
  - 依赖：T37；问题/验收：B08、AC-08/19/22；B06已修复。
  - R：R1、R2、R3、R4、R5、R5a、R6、R7、R8、R9、R10、R11、R12（只核对原功能合同不变）；PRD：§3.1–§3.5、§5、§9、§11 M5。
  - 交付：仅浏览器操作与证据/追溯；不在本项夹带实现或装置修改。明暗主题分别经真实页面点击四按钮，合计8次受控生成，分镜保留impact确认；每次记录实际body/202/task_id、同id barrier/release、UI与REST/独立DB终态。记录受控handler不产真实GPU媒体。
  - 计划测试层级：不新增自动测试；任务系统 mock；跨进程/资源生命周期。
  - 追溯行：`C011 既有功能入口与状态呈现不变`；`C011 全局异常空态与媒体错误呈现`；`C011 全局浏览器功能与视觉验收`；`C011 验收装置与生产通路归属`。
  - 验收：依spec §4.1八类页面逐项记录加载/空数据/读取失败/动作失败；媒体页另有媒体失败。使用T03普通隔离fixture及spec §10.2已授权失败制造方式，草稿原文保留、错误原文可见、导航可达、没有成功媒体替代；每格给操作→观测值→期望，确不可达组合注明具体理由及替代观测。普通模式不触发GPU。补验后恢复自有服务/临时媒体并验证，无用户资源改动。
  - 命令：普通与受控环境分别执行`python -X utf8 .work/c011/ui_fixture.py verify`；按T24A原正式API步骤安装§7.4逐字人工模板并GET回读，复用已验收T37观测；人工完成上述矩阵；`git diff --check`。本项不新跑 G，完整回归归 T39；新的浏览器验收不以旧亮色日志补数。
  - 2026-09-09恢复顺序：先完成本次T37装置修复，再继续T38；`739ecd4`只是部分证据提交，不改变本项未完成状态。先只读寻找旧批次完整原始文件及独立DB中#1–#8的当前状态，能恢复的证据标明实际采集时间，不能冒称当时同步回读；找不到的#4/#8入队body/barrier不能用T37其他task的{}记录替代。装置改变后受影响链路用全新受控批次重新做双主题8次按钮，每task保存同批次实际请求/202/id/barrier/release/REST/UI/独立只读DB；普通隔离环境补全八类页面可达的异常矩阵，不用正常截图或G替代。旧失败批次不重放业务Task，不覆盖日志。T38全部通过前不得正式执行T39或任何收尾；前次越过依赖的探针只归预诊断。
  - 2026-09-09完成证据：普通批次 `.work/c011/T38-ordinary-browser-20260909_143450.log` 记录 spec §4.1 各类页面的正常/空态、后端停止后的逐页读取失败、资产动作失败、媒体失败与恢复；受控批次 `.work/c011/T38-controlled-browser-20260909_1505.log` 记录亮/暗主题下四类按钮各两次真实入队，分镜 impact 确认，以及每个 task 的实际 body/202/task_id/barrier/release/UI 终态；8份 `T38-controlled-20260909_1505-taskN-db-readback.log`、`.work/c011/T38-controlled-20260909_1505-terminal-readback.log` 保留独立数据库与 REST 对照。两个批次 fixture verify、模板 API 失败及修复、服务清理证据均保留原始日志；受控handler不宣称真实GPU/M6媒体生成。
  - 本项按最新验收频率裁决未新跑 G；阶段完整回归归 T39。追溯四行已回填 T38 证据后勾选本项。

- [x] **T39 完成逐用例追溯和审查探针复验**
  - 依赖：T38；问题/验收：B01–B10、AC-23；此项通过仍须重新执行T23/T24/T25及固定收尾。
  - R：无；PRD：§0、§9、§11 M5。
  - 交付：只回填openspec/TRACEABILITY.md及tasks.md的实际事实；枚举基线后所有新增测试，回填文件＋describe/it完整名称（参数用例标实际参数）或pytest node ID；尤其statusPresentation、theme/themeWiring及T29–T36新增用例。每个用例至少归属一个现有追溯行；既有/新增文件不改，审查原报告与探针不改。
  - 计划测试层级：任务系统 mock；跨进程/资源生命周期；不新增自动测试（本项仅运行已交付回归/探针并审计）。
  - 追溯行：`C011 范围回归与文档提交一致性`及上列各修复任务所指的准确原行；无需新增同义行。
  - 验收：逐项B01–B10给修复commit/回归用例/原失败和新通过日志；31条AC全部有可核验归属；六处探针缺陷各有独立回归。前端审查探针14场景failed=[]/exit=0；跨进程probe真实RESULT PASS/exit=0、资源退出。探针若因夹具/工具变化无法证明合同，保留结果向Astra说明，不自行改断言；不得把审查报告中的六处旧失败改写成通过。
  - 命令：`git diff --name-status b4750e4`、`git diff --check`；`rg -n 'describe|it\\(|it.each|def test_' frontend/src/features backend/tests -g '*test*'`用于人工逐用例核对；`python -X utf8 .work/c011/probe-task-observation.py`；`python -X utf8 .work/c011/probe-runtime.py`（全新隔离批次，人工模板证明边界仍按报告说明）；`powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T39 -EvidenceLabel ('repair'+(Get-Date -Format 'yyyyMMdd_HHmmss'))`。
  - G 复用核验：本项上述 G 命令只在没有同受测输入的有效成功结果时执行；按开头规则逐项记录核验依据，不因 T37 曾通过就直接略过。两发正式探针仍须在 T38 完成后执行。
  - 提交核验：`git ls-tree -r --name-only HEAD openspec/changes/c011`必须含spec.md/tasks.md；工作树/提交各自真实报告，AGENTS既有改动及.work不纳入。本轮规划提交先解决B10的spec缺文件，T28最终再证明全部修复后的状态。
  - 2026-09-09探针裁决：Astra已将probe-task-observation.py唯一重连场景由直接loadTaskDetail改为挂载真实TasksPage并点击查看详情，使生产页面调用setExpandedTask；期望detail=done不变并加强读取次数/完成时间/无POST断言。新原始输出`probe-task-observation-20260909-141633.stdout.log`为14场景failed=[]/exit=0，实际页面重连回归4用例也通过。旧132904失败保留，其原因是探针漏模拟展开身份，不是据此要求生产代码刷新所有未展开缓存。此诊断不代表T39正式完成，不授权Luna修改探针/既有测试；等T38完成后按原命令执行两发探针与G，并按既有顺序重验T23/T24/T25、最后T26–T28。
  - 2026-09-09完成证据：已在T38提交 `06fb3ef` 后正式运行 `python -X utf8 .work/c011/probe-task-observation.py`（14场景、`failed=[]`、exit 0）和 `python -X utf8 .work/c011/probe-runtime.py`（全新库 `ai_drama_studio_c011_probe_20260909_150722_36700`、migration/prepare/verify/模板API/REST+WS+独立DB/关闭与端口检查均通过、exit 0）；完整原始文件与退出事实见 `.work/c011/T39-audit-20260909.log` 及对应 `probe-*` 日志。已核对 spec 唯一31条AC和17条C011追溯行、T29–T36新增测试文件及 describe/it/参数身份；对应B01–B10修复commit/原失败/新通过日志仍保留在追溯表。
  - G复用核验：T37成功G `.work/c011/T37-t37apparatus20260909_142315-test.log` 的受测代码到当前HEAD在backend/frontend、测试和运行时装置范围无差异；该G已真实记录前端30 files/160 tests、build68 modules、Alembic upgrade/current/check exit 0、完整pytest `348 passed in 392.73s`、git diff check exit 0。T38仅文档提交，故按最新频率规则引用该同输入G，未重复执行 `run_checks.ps1 -Task T39`；`AGENTS.md`和`.work`未提交。


## 固定收尾任务

- [ ] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）
  - 编号/依赖：T26；依赖T25。
  - R：无；PRD：§11 M5。
  - 交付范围：只记录本change已实际验证的命令、环境事实和坑；没有新增事实就不改NOTES，在完成报告写「无」。当前规划轮不提前写实施事实。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：`git diff -- NOTES.md`，逐条对照原始日志；`git diff --check`；引用 T25 核对的完整回归，不重跑 G。AC-23，不把历史端口/通过数写成当前结果。

- [ ] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）
  - 编号/依赖：T27；依赖T26。
  - R：无；PRD：§11 M5。
  - 交付范围：只在完成报告列出确有跨change价值的候选与依据；没有则「无」。不因该checkbox自行编辑DECISIONS。可评估来源返回的路由state边界是否值得记录，不能把未验收计划当既成决策。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：人工核对候选与已验收证据；`git diff -- DECISIONS.md` 应为空；`git diff --check`；引用 T25 核对的完整回归，不重跑 G。AC-23。

- [ ] change 文档与 commit 状态一致
  - 编号/依赖：T28；依赖T27。
  - R：无；PRD：§11 M5。
  - 交付范围：完成报告逐项列AC、真实命令/结果、浏览器与mock证据差异、删除项、未验证/阻塞、NOTES与DECISIONS候选；只有全部通过才勾选。按授权提交范围核对，不纳入.work，不自行归档或推送。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：引用 T25 核对的完整回归，不重跑 G；`git diff --check`、`git diff --cached --name-status`、`git status --short`、`git log --oneline -5`，逐项核对checkbox/证据/commit。若尚未获提交授权，明确报告“未提交”，不把该项勾成提交已完成；有权限后只提交已验收且明确授权文件。AC-23。
