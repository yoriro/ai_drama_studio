# C011 执行任务

本文件是实施计划，checkbox 只表示已有验收证据，不替代 commit 证据；实施范围以需求方另行指定的任务为准。最初规划轮不授权实施；需求方随后已向 Luna 派发执行，本次 2026-09-07 裁决仅解除下述 T03 装置修复与重新验收的阻塞。按依赖一次只执行需求方指定的一项；失败/歧义立即停止，不勾选、不推进、不重试任务、不覆盖失败证据。新增测试只能是新的独立文件；任何已存在测试文件都不能修改。

## 通用验收命令与约定

- 本轮规划基线：`1ef70e5d5fad245d6e38e1472eaa16ffb523aa59`。正式实施前记录实际HEAD与已有改动；未经授权不清理 `.work/`。
- 以下文件名/CLI 是前置 task 的**计划交付合同**，不是声称当前已存在。`tasks.md` 不授权把它们今天落盘。
- **G**：在仓库根运行 `powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task Txx`（Txx 换为本项编号）。T01 必须先交付此装置；各项调用内部逐条执行 `npm --prefix frontend run test`、`npm --prefix frontend run build`，在新建、仅迁移的 PostgreSQL/独立 DATA_DIR 中以 backend 为 cwd 执行 `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、`python -m pytest -q`，最后 `git diff --check`。每步原生退出码为0才继续；stdout中“passed”不能替代已结束进程和真实退出码。
- 定向 backend 命令也由T01装置以新隔离库运行；装置提供 `-Task Txx -TargetPytest tests/...` 参数。定向后完整pytest使用**另一个**新建仅迁移库，不能复用已有Task的浏览器库。前端定向命令在本项明列。
- 浏览器 ordinary、受控任务、pytest 三类环境分离；通过环境变量显式选择，不改用户 `backend/.env`。现场选择并记录可用端口；若Vite固定代理8000被用户进程占用，单独的验收Vite配置放.work并启动隔离端口，不能停用户进程或修改生产业务地址。启动自有后台进程使用 Hidden 窗口。
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

- [ ] **T04 交付受控任务运行时装置**
  - 依赖：T01。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§11 M5。
  - 交付范围：仅交付 `.work/c011/task_runtime.py`：既有 create_app 的显式注入 seam、独立进程/管道 barrier、生产 TaskQueue/EventBus/REST/WS/真实 PostgreSQL；足量有效 target 和混合历史任务通过队列原语产生。CLI 支持 serve、自检和按 task ID 放行/失败控制，输出 READY 与 barrier reached 事实。外部 clients/handler 为明确受控替代。普通 app.main 默认 handler/配置不改。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：`C011 验收装置与生产通路归属`。
  - 验收方式与命令：`python .work/c011/task_runtime.py --help`；`python .work/c011/task_runtime.py self-check`；G。自检以独立 HTTP/WS 客户端观察真实 enqueue→claim→progress→done，第三方 DB 只读连接对照，正常退出后本轮进程消失；逐项审计无直接状态 UPDATE、伪 WS/第五 task type/生产 endpoint。服务端写操作前一次核对该 runtime 的 /openapi.json。
  - 验收归属：AC-20；取消胜方验收另列 T22。本 task 不声称真实 GPU/业务产物成功。

- [ ] **T05 实现设置与任务中心的来源返回**
  - 依赖：T02、T03。
  - R：无；PRD：§2.1(1-3,8)、§9、§11 M5。
  - 交付范围：新增最小 navigation 来源决策与独立纯函数用例 `frontend/src/features/navigation/returnLocation.test.ts`；在 AppShell 及所有现有指向 /settings、/tasks 的页内链接接线。来源放路由 state；辅助页继承、replace 返回、刷新/无来源/非法来源行为严格按 spec §2.1。目标错误页保留首页链接；不引入草稿保存或最近页持久仓库。
  - 计划测试层级：纯函数。
  - 追溯行：`C011 导航来源返回与剧集唯一入口`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/navigation/returnLocation.test.ts`；G；人工浏览器逐项 AC-02/03：六类来源、辅助页互跳、刷新、新标签、浏览器 back/forward、非法来源和已删实体，记录目标 URL 与零额外 mutation。纯函数用例不得声称验证已挂载 Router；真实浏览器补足接线。
  - 验收归属：AC-02/AC-03 完整。实现前对被替换的既有导航片段 git blame。

- [ ] **T06 移除剧集重复入口**
  - 依赖：T05。
  - R：无；PRD：§2.1(3)、§9、§11 M5。
  - 交付范围：只删除 ProjectPage 的“进入集工作区”重复 Link；保留原集标题 Link 和独立编辑/删除按钮。删除前 git blame 定位用途，记录精确删除项，不扩大为删卡片或改路由。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 导航来源返回与剧集唯一入口`。
  - 验收方式与命令：`rg -n '进入集工作区' frontend/src` 应无匹配（rg exit 1 为预期）；G；人工鼠标和键盘进入正确集，取消/确认编辑删除仍按原语义，点击操作不进入集。
  - 验收归属：AC-04；低影响重复展示删除不新增自动测试，替代方式为上述真实操作。

- [ ] **T07 统一视觉变量与应用壳**
  - 依赖：T03、T05。
  - R：无；PRD：§2.1、§9、§11 M5。
  - 交付范围：在 styles.css 定义并消费 spec §3 token，改 AppShell/PageTitle/BackendStatus 的排版、导航、玻璃面板、CTA、焦点与 reduced-motion。保留品牌和健康诊断语义。集中替换对应旧色值，禁止为了主 CTA 数量隐藏原功能；各页业务区域在后续明确 task 收口。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`。
  - 验收方式与命令：G；在四个视口人工检查 header/背景/标题/health/导航的计算样式、无远程字体请求、对比度、换行和键盘焦点；输出每个视口截图。
  - 验收归属：AC-05/06/07 的壳与共享基础样式部分；本 task 不勾全页验收完成。

- [ ] **T08 整理项目首页和剧集列表视觉**
  - 依赖：T06、T07。
  - R：无；PRD：§2.1(1,3)、§9、§11 M5。
  - 交付范围：只改 HomePage/ProjectPage 的布局与展示样式：项目/剧集卡片、创建和编辑表单、空态入口、标题层级、响应式网格。保留风格选择、CRUD、确认和标题导航；不增加 Hero 生成/风格市场/作品流。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工按 spec §4.1 两页清单执行创建、编辑、取消、确认删除与导航，记录正式请求；四视口根无水平溢出、按钮可见、空态不造假。
  - 验收归属：AC-05/06/07/08 对这两页的完整切片。

- [ ] **T09 整理设置页视觉**
  - 依赖：T07。
  - R：R11；PRD：§2.1(2)、§3.2、§3.5、§9、§11 M5。
  - 交付范围：仅整理 SettingsPage 诊断、风格表单和四模板编辑器布局/样式。长模板/hash/message 可读，诊断刷新与保存保持各自状态；保留所有字段和按钮、返回来源入口，不改模板正文或 API helper。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工逐项风格 CRUD/冲突显示、四模板读取和显式保存、诊断刷新、真实 unhealthy/error 呈现；四视口检查编辑器与长 hash 不撑破页面。普通后端真实 health 不可用时该验收保持未完成。
  - 验收归属：AC-05/06/07/08 的设置切片；C012 正式模板安装不属于此 task。

- [ ] **T10 整理集壳与剧本页视觉**
  - 依赖：T07。
  - R：R1、R2、R3；PRD：§2.1(3,4)、§3.1、§3.2、§9、§11 M5。
  - 交付范围：只整理 EpisodeWorkspacePage 的上下文标题、返回项目、四 tab、剧本编辑区和 impact 确认展示。保留 generated revision 角标、字数约束、两生成按钮、任务链接及现有 mutation 处理，不改生成/确认/token/去重语义。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工四视口浏览四 tab 并完成剧本编辑保存/取消、影响预检显示实际删除数量、取消确认不提交；逐项对照原路径/body。实际生成/取消竞态仍由既有回归与 T23 验证，不能以本 task 的排版检查替代。
  - 验收归属：AC-05/06/07/08 的集壳与剧本展示切片。

- [ ] **T11 整理资产页视觉与媒体布局**
  - 依赖：T07。
  - R：R4、R11；PRD：§2.1(5)、§3.2、§3.5、§9、§11 M5。
  - 交付范围：只整理 AssetPage 的资产表单、意见输入、当前图和画廊布局，保留 project 级范围、旧剧本提示、上传/current/删除/seed/DEBUG。复用现有同步与 action，禁止视觉重构顺带重写资产队列/请求。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工四视口按 §4.1 资产清单逐项操作 CRUD、上传、切 current、非 current 删除；对照原 body、显示完整 string seed、DEBUG 由响应决定，图片比例不裁切内容。
  - 验收归属：AC-05/06/07/08 的资产切片；图片生成业务成功不由 fixture 证明。

- [ ] **T12 整理分镜页视觉**
  - 依赖：T07。
  - R：R5a；PRD：§2.1(6)、§3.2、§3.4、§9、§11 M5。
  - 交付范围：只整理 ShotsPage 镜头卡片、文本/时长/绑定编辑区、changed 与场景数警示区域。保留原序和全部字段，禁止新增镜头增删/排序。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：G；人工四视口保存分镜字段/绑定、观察原 API 和零/多场景提示；changed 样式在 T14 统一，但当前业务标记不得消失。
  - 验收归属：AC-05/06/07/08 的分镜切片。

- [ ] **T13 整理导演台视觉与窄屏布局**
  - 依赖：T07。
  - R：R5、R5a、R6、R7、R8、R9、R10、R11、R12；PRD：§2.1(7)、§3.2-§3.5、§9、§11 M5。
  - 交付范围：只调整 DirectorPage 展示与 director 样式：三轨同一滚动容器和列定义、详情窄屏下移、preview/slot/take/输入区视觉。保留 directorModel/directorSync 原业务决策/同步接线、所有 soft warning/disabled 条件、DEBUG/媒体路径和比例。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/director`；G；人工四视口比较三轨列与 duration 比例、滚动对齐；按 §4.1 Director 清单操作原 preview/create、设置、槽位、take/current/delete，记录每项入口和请求不变。
  - 验收归属：AC-05/06/07/08 的导演台切片；不声称真实视频生成链路在本 task 重新验收。

- [ ] **T14 统一既有新鲜态与生成态展示**
  - 依赖：T10、T11、T12、T13。
  - R：R8、R12；PRD：§2.1(4,6,7)、§3.2、§3.3、§3.4、§9、§11 M5。
  - 交付范围：最小共享状态文案/Badge，仅消费已知状态；新增独立 `frontend/src/features/status/statusPresentation.test.ts`，把 Shots/Director 的标签统一到 spec §4.2，并保持剧本/资产旧剧本原文、R8 黄色、R12 已删原文。不把业务 freshness 判定迁入通用组件。
  - 计划测试层级：纯函数。
  - 追溯行：`C011 既有功能入口与状态呈现不变`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/status/statusPresentation.test.ts`；G；穷举 normal/changed、五种生成态×fresh/stale 和 null/旧/当前 revision 展示，人工确认 generating+stale 共存且 stale 本身不禁用。
  - 验收归属：AC-09 完整；纯函数只证明文案/状态投影，页面集成由人工与 T24 补足。

- [ ] **T15 统一全局加载错误空态与媒体失败展示**
  - 依赖：T08、T09、T10、T11、T12、T13。
  - R：无；PRD：§2.1、§5 通用、§9、§11 M5。
  - 交付范围：整理 ApiErrorMessage/EmptyState 及各页呈现接线：主错误直显原 message、code 另列；loading/error/empty 区分，长错误换行；现有媒体 onError 在真实页面可见。保留原业务表单和动作，缺数据不渲染假卡片，不增加自动重试或业务 fallback。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 全局异常空态与媒体错误呈现`。
  - 验收方式与命令：G；按 AC-19 对 §4.1 全页逐一人工制造加载、空数据、读取失败、动作失败；媒体页另检查损坏响应。浏览器网络调试的阻断/响应替换证据标记为受控外部输入，与普通成功通路分开。
  - 验收归属：AC-19；Task 页异步/协议自动验证由 T19/T21 提供，本 task 不替代。

- [ ] **T16 接入任务过滤读取客户端并验证既有 API 窗口**
  - 依赖：T02、T04。
  - R：无；PRD：§2.1(8)、§5 任务、§11 M5。
  - 交付范围：扩展 api/tasks.ts 的 listTasks 查询参数，仅允许现有 status/type/limit，复用 parser。新增 `backend/tests/api/test_c011_task_listing.py` 通过生产 GET 与真实 PostgreSQL 验证过滤先于 limit、默认50/最大100、id降序、空数组和非法 query 422；不改 backend/app 或既有 test_tasks.py。
  - 计划测试层级：API 集成。
  - 追溯行：`C011 任务列表过滤与有限历史`。
  - 验收方式与命令：`python -m pytest -q tests/api/test_c011_task_listing.py`（cwd=backend，先用 T01 装置准备新的定向库）；G。混合 fixture 超过100，失败/终态置于未过滤最新50之外，证明不是缓存切片假过滤。
  - 验收归属：AC-10 的正式 API 窗口与客户端边界；页面控件在 T17。

- [ ] **T17 接入任务过滤控件与有限历史展示**
  - 依赖：T07、T16。
  - R：无；PRD：§2.1(8)、§5 任务、§9、§11 M5。
  - 交付范围：TasksPage 增加 status/type/20-50-100 控件、进行中/历史分组和窗口说明、空结果文案；选全部省略对应参数，组内 id DESC。只提取本页必要的查询/分组纯函数并新增 `frontend/src/features/tasks/taskList.test.ts`，不加分页/搜索/总数。每次过滤使当前请求代次变化，为 T18 接入事件刷新。
  - 计划测试层级：纯函数。
  - 追溯行：`C011 任务列表过滤与有限历史`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskList.test.ts`；G；普通浏览器选控件并核对实际 GET、匹配集合/数量/组别/空态。同步在普通顺序下可用，竞态完整验收单列 T18。
  - 验收归属：AC-10 的控件/分组/窗口说明完整；T18 前不能宣称 AC-16 完成。

- [ ] **T18 落实任务中心列表与详情的 WS 权威同步**
  - 依赖：T02、T17。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§9、§11 M5；D-008。
  - 交付范围：把 TasksPage 已有同步按需整理到 features/tasks，实际页面消费同一协调器。明确初连/重连缓冲、过滤代次/socket身份、未知详情去重、terminal替代读取、列表窗口补足、过期请求不写状态、最新失败可见、卸载清理与无轮询。新增独立挂载 TasksPage 的 `frontend/src/features/tasks/taskObservation.test.tsx`；不用测试副本替代生产 action/parser。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务中心 REST/WS 同步与过滤竞态`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskObservation.test.tsx`；G；deferred+FakeSocket 逐项 AC-15/16/17：初始/重连顺序、过滤A/B、列表/详情过期补读、同时未知事件、终态去重、idle零GET、1/2/5/10秒重连和卸载。GET账本由真实 fetch stub 记录。
  - 验收归属：AC-15/16/17 完整；输出明确仅 DOM/传输 mock，真实进程见 T22/T23。

- [ ] **T19 接入任务详情与严格错误呈现**
  - 依赖：T15、T18。
  - R：无；PRD：§2.1(8)、§5 任务、§9、§11 M5。
  - 交付范围：TasksPage 可展开具体 task 正式详情，完整时间/错误与 request_id 展示；接线 parseTaskResponse/parseTaskEventResponse 的可见失败路径，状态/进度/ID/extra字段不能强转；协议错误关闭该 socket、观察重连成功前错误不消失。新增 `frontend/src/features/tasks/taskBoundary.test.tsx`，挂载真实页面。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务公开边界与可见协议错误`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskBoundary.test.tsx`；G；按 AC-11/18 注入长错误/null时间/取消时间、未知enum/越界progress/非safeID/extra payload/畸形JSON及422/500，断言DOM原文、非法ID零详情GET、没有空列表伪成功。
  - 验收归属：AC-11/18 完整；既有 api/tasks parser 的合法合同不放宽。

- [ ] **T20 接入单任务取消基本交互**
  - 依赖：T19。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§9、§11 M5。
  - 交付范围：新增复用 requestJson/parser 的 cancelTask helper（无 body POST），在 TasksPage 实际按钮接线；每task in-flight、queued/running/已请求/终态按钮状态与等待文案；取消成功后权威读取详情和当前窗口，确认前无成功提示。新增独立 `frontend/src/features/tasks/taskCancel.test.tsx`。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务取消交互与终态竞争`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskCancel.test.tsx`；G；按AC-12遍历状态、鼠标/键盘双击和多task隔离；断言真实helper收到的method/path/body、POST=1、200 running仍显示等待且没有canceled假状态。
  - 验收归属：AC-12 完整；竞争/失败不夹带为未列出的修复，后续T21独立验收。

- [ ] **T21 封闭取消竞争错误与当前页面隔离**
  - 依赖：T20。
  - R：无；PRD：§2.1(8)、§5 任务、§6.1、§9、§11 M5；D-008。
  - 交付范围：落实取消与done竞争、迟到200 running、404/409权威刷新与资源消失、超时未知结果、筛选A/B/展开B/卸载identity。操作错误不被后台GET清除；未知结果确认前禁止再次提交，仅显式刷新或观察重建。新增独立 `frontend/src/features/tasks/taskCancelRaces.test.tsx`，保持T20既有用例不变。
  - 计划测试层级：任务系统 mock。
  - 追溯行：`C011 任务取消交互与终态竞争`；`C011 任务取消错误与资源消失重建`。
  - 验收方式与命令：`npm --prefix frontend run test -- src/features/tasks/taskCancelRaces.test.tsx`；G；deferred控制AC-13/14两种胜方与迟到响应，实际DOM/action链证明POST一次、正确task归属、GET次数/路径、无success notice、消失清详情且不污染B。
  - 验收归属：AC-13/14 完整；不修改后端竞争裁决或改既有测试换绿。

- [ ] **T22 验证跨进程取消与观察一致性**
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

- [ ] **T24 完成全站响应式视觉与功能保留验收**
  - 依赖：T05-T15、T23。
  - R：R1、R2、R3、R4、R5、R5a、R6、R7、R8、R9、R10、R11、R12；PRD：§2.1、§3.1-§3.5、§5、§9、§11 M5。
  - 交付范围：不夹带代码或装置改动；使用T03普通生产后端/fixture逐页执行spec §3视口矩阵、§4.1每项功能入口、AC-02..09/19/22。检查四类生成按钮的现有请求接线时单独使用T04受控handler模式并明确不证明实际生成；普通模式不得触发未授权GPU流水线。未满足项记录为失败并停在本task。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 导航来源返回与剧集唯一入口`；`C011 全站视觉与响应式可访问性`；`C011 既有功能入口与状态呈现不变`；`C011 全局异常空态与媒体错误呈现`；`C011 全局浏览器功能与视觉验收`。
  - 验收方式与命令：人工浏览器四视口+200%缩放、Tab/Enter/Space、reduced-motion与计算对比度；记录每页/每功能实际检查结果、截图及method/path/body。`npm --prefix frontend run test -- src/features/director`；G。自建自动浏览器脚本若尚无前置task，不可临时补进此task。
  - 验收归属：AC-05..08/22全页结论在这里收口；不得只交首页截图就勾全站。

- [ ] **T25 完成范围追溯与回归审计**
  - 依赖：T24。
  - R：无；PRD：§0、§5 通用、§9、§11 M5。
  - 交付范围：核对所有AC/追溯/指定用例和人工记录；保护基线既有测试，允许新增独立测试文件；核对后端生产、schema/migration/workflow/template零变化、无新增业务、无未列装置、无旧日志伪装新结果。只修正文档事实，不修代码或重跑失败到绿。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：G；`git diff --check`；`git diff --name-status 1ef70e5d5fad245d6e38e1472eaa16ffb523aa59`；`git diff 1ef70e5d5fad245d6e38e1472eaa16ffb523aa59 -- backend/app backend/alembic backend/workflows` 应为空；`git status --short`；人工按基线逐一核对既有test无M/D、新增用例逐行回填；`rg -n '^\| C011 .*待填' openspec/TRACEABILITY.md` 应无匹配。
  - 验收归属：AC-01/23；范围依据允许文件集，不要求整个change diff为空。

## 固定收尾任务

- [ ] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）
  - 编号/依赖：T26；依赖T25。
  - R：无；PRD：§11 M5。
  - 交付范围：只记录本change已实际验证的命令、环境事实和坑；没有新增事实就不改NOTES，在完成报告写「无」。当前规划轮不提前写实施事实。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：`git diff -- NOTES.md`，逐条对照原始日志；`git diff --check`；G（Task=T26）。AC-23，不把历史端口/通过数写成当前结果。

- [ ] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）
  - 编号/依赖：T27；依赖T26。
  - R：无；PRD：§11 M5。
  - 交付范围：只在完成报告列出确有跨change价值的候选与依据；没有则「无」。不因该checkbox自行编辑DECISIONS。可评估来源返回的路由state边界是否值得记录，不能把未验收计划当既成决策。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：人工核对候选与已验收证据；`git diff -- DECISIONS.md` 应为空；G（Task=T27）。AC-23。

- [ ] change 文档与 commit 状态一致
  - 编号/依赖：T28；依赖T27。
  - R：无；PRD：§11 M5。
  - 交付范围：完成报告逐项列AC、真实命令/结果、浏览器与mock证据差异、删除项、未验证/阻塞、NOTES与DECISIONS候选；只有全部通过才勾选。按授权提交范围核对，不纳入.work，不自行归档或推送。
  - 计划测试层级：不新增自动测试。
  - 追溯行：`C011 范围回归与文档提交一致性`。
  - 验收方式与命令：G（Task=T28）；`git diff --check`、`git diff --cached --name-status`、`git status --short`、`git log --oneline -5`，逐项核对checkbox/证据/commit。若尚未获提交授权，明确报告“未提交”，不把该项勾成提交已完成；有权限后只提交已验收且明确授权文件。AC-23。
