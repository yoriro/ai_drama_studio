# C011 修复闭环审查：PASS

审查人 Astra。当前实现提交 e4605bb7cbf5f59be2dc8ed38dd3a8725c1f89da；C010 基线 1ef70e5d5fad245d6e38e1472eaa16ffb523aa59。原第二审查 review-reaudit-20260909.md 的31条AC映射、完整diff审计与历史失败保留；修复过程详见 review-loop-20260909.md。本文件的当前结论优先，不将旧“全部完成”声明作为现状。

## 当前判定

**PASS。** T40–T45实现修复及独立回归、T23同页真实浏览器组合、T44/T38异常与生成矩阵、T25–T28收尾均已完成。最终提交`2acf32a5f86adb951406313f5af4b539964bd4f4`，52/52 checkbox、31条AC、17条主追溯行。下方过程段落中的待验/退回描述是当时状态，以本结论及最后收口段为准。

- B11：取消前旧GET不能解除取消失败保护。T40新增独立 taskCancelFailureReadOrder.test.tsx 两参数用例，保留原错误/后续权威GET/POST一次。
- B12：取消成功后读取失败保持确认保护；修复期间独立发现的自触发读取循环也已修复。T41 taskCancelConfirmationFailure.test.tsx 三用例及独立循环探针覆盖。
- B13：过滤重建保留展开任务必须刷新详情，消失重现保持收起再显式读。T42 taskFilterDetailRebuild.test.tsx 六用例与过滤/重开探针覆盖。
- B14：导演台复用presentShotStatus，精确显示“已变更（changed）”。Astra普通环境实际双主题核验见 review-t43-ordinary-20260909.log；52429历史环境为受控，不误称普通。
- B15：T44八页异常矩阵已有补充；导演台T44A前置装置交付后正式补验见 T44-director-save-failure-postT44A-20260909.log。当前T23-B16组合已补齐并独立核验，整体PASS。
- B16：T23实际发现收起ready详情跨重连保留，明确再次展开却没有新GET。T45生产仅一行将连接重建时ready与loading一起失效；新增 taskClosedDetailReconnect.test.tsx 三用例覆盖自然断线/过滤及取消建立缓存而另任务展开。Astra逐行检查POST无body且一次、当前展开任务详情字段、显式重开GET精确2、终态/错误/时间逐项相等。未改任何既有测试。

## T45实际原始前端输出

下列记录从Luna该任务的原CommandExecution事件stdout/stderr/exit_code恢复，不是重跑；metadata保存准确command/cwd/时间/事件身份。旧手工整理的T45日志只作摘要，不能把摘要称完整RAW OUTPUT。

| 检查 | 原始记录前缀（均位于.work/c011） | 真实结果 |
|---|---|---|
| 初次新用例 | T45-raw-d132852b-71ea-478d-aa0d-60269978052a | exit1；含新测试的取消等待/查询缺陷，不把它全称B16目标红测 |
| 修复前目标红测 | T45-raw-f79e7827-8ee9-469a-a437-770fd0d3dbd3 | exit1；3 tests failed，均 expected 1 to be 2 |
| 修复后最终定向 | T45-raw-00a13f6c-c348-4d45-8bd8-59397d9d90ad | exit0；3 tests passed |
| npm.cmd --prefix frontend run test | T45-raw-846e586c-5cf1-44c1-af94-721feead68cc | exit0；34 files / 174 tests passed |
| npm.cmd --prefix frontend run build | T45-raw-1baa25ed-e75a-4dce-a486-62ea3fd330a9 | exit0；68 modules transformed |

每个前缀均有.stdout.log/.stderr.log/.metadata.json。React Router提示保留；No test files found是准备失败，不冒充红测。

## Astra最终实现七条独立探针

全部于2026-09-10在T45同一行生产修复工作树实际运行，随后该实现提交e4605bb。未修改实现或既有测试，原失败证据保留。以下均真实退出0；无输入变化不重复跑。

| 命令 | 原始结果 |
|---|---|
| python -X utf8 .work/c011/probe-task-observation.py | probe-task-observation-20260910-102734.stdout.log：14场景，failed=[] |
| python -X utf8 .work/c011/probe-cancel-read-order.py | probe-cancel-read-order-20260910-102734.stdout.log：4场景，failed=[] |
| python -X utf8 .work/c011/probe-cancel-confirmation-loop.py | probe-cancel-confirmation-loop-20260910-102734.stdout.log：list1/detail1/POST1，错误可见且取消受保护 |
| python -X utf8 .work/c011/probe-filter-reopen.py | probe-filter-reopen-20260910-102734.stdout.log：重开前detail1、后detail2，列表/详情done，POST0 |
| python -X utf8 .work/c011/probe-closed-detail-reconnect.py | probe-closed-detail-reconnect-20260910-102722.stdout.log：GET由1到2、POST0、未自动展开，列表/详情failed、取消/完成时间与server restarted逐字段相等 |
| python -X utf8 .work/c011/probe-runtime.py | probe-runtime-20260910_102734_25900.log：实际生产queue/lifespan、独立HTTP/WS/asyncpg、140历史AND/limit20/50/100精确数量及ID、非法输入422、终态cancel409、queued/running取消一致；shutdown0、port_closed=true、RESULT PASS |
| python -X utf8 .work/c011/probe-template-contract.py | probe-template-contract-20260910_102734_20260.log：四份spec人工模板经正式API逐字PATCH/GET、fixture生命周期/媒体解码；shutdown0、port_closed=true、RESULT PASS |

收起详情探针原始关键行：
```json
{"name":"explicit reopen after closed-detail reconnect","ac":"AC-11,AC-15","observed":{"lists":2,"detailsBeforeExplicitOpen":1,"details":2,"posts":0,"remainedClosed":true,"list":"failed","fields":["—","failed","0.5","—","2026/9/9 GMT+8 8:00:02","2026/9/9 GMT+8 8:00:00","2026/9/9 GMT+8 8:00:01","2026/9/9 GMT+8 8:00:05","server restarted"]},"passed":true}
PROBE_SUMMARY={"checks":1,"failed":[]}
```

17个高风险AC（03、10–21、24、25、27、28）沿原审查映射均有实际定向结果。受控handler/client隔离真实GPU，证明生产任务存储/HTTP/WS/进程生命周期与前端接线，不证明真实生成质量或M6。

## 完整后端回归的同输入复用

Astra已实际运行 powershell.exe -NoProfile -File .work/c011/run_checks.ps1 -Task T39 -EvidenceLabel astrafinal20260909loop，受测4bd3a713f12121f8fc082626d8f0d8154e79fead，总进程exit0。原始T39-astrafinal20260909loop-test.log及分步stdout/stderr/PID/exit-code均保留。

backend目录 python -m pytest -q：348 passed in 239.87s (0:03:59)，PID23652，exit0。独立库ai_drama_studio_c011_t39_full_20260909_183354_38988；独立DATA_DIR .work/c011/data/T39-astrafinal20260909loop-full-20260909_183354-38988。Alembic upgrade/current/check均exit0、head6b8e3f0a1d24、No new upgrade operations detected。

到e4605bb，git diff --name-status 4bd3a71 -- backend frontend/package.json frontend/package-lock.json为空；T45仅前端controller及独立新测试/文档，运行装置未修改。后端结果可依AGENTS验收频率规则复用；前端采用上表新的174 tests/build，不把旧G前端171 tests说成覆盖T45。今日七探针另验证当前输入。

## 不升级为已验证的边界

原生桌面200%缩放、动态reduced-motion仍未验证，按已批准spec7.4非阻塞；非法非空Router state的IAB动态注入限制沿既定组合证据；非editable错误pre的剪贴板读回限制保留。M6真实模板部署、真实GPU视频与交付质量属于C012。本轮不改这些产品边界、不归档、不推送。

## 31条AC当前核对表

本表保留原审查的具体实现/测试定位；最新修复用例与七探针细节见上文。真实浏览器未完成部分单独注明，不由自动测试替代。

| AC/风险 | 具体实现与用例/人工证据 | 当前核对 |
|---|---|---|
| 01 常规 | 全量 diff；后端 app/alembic/workflows 与 DECISIONS diff 为空；唯一既有测试 M 为授权 C009 do_POST | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 02 常规 | returnLocation + AppShell/AuxiliaryPageReturn；`returnLocation.test.ts::accepts each work route and preserves search and hash`、`captures work locations and inherits the same state between auxiliary pages`；T05/T24D 来源返回日志 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 03 外部输入 | returnLocation、ProjectPage 错误分支；`returnLocation.test.ts::rejects non-work, unsafe, and hostile source pathnames`、`distinguishes no source from a non-empty invalid state`；`projectReturnError.test.tsx::shows the structured 404 and returns to the real home route without mutation` | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 04 常规 | ProjectPage 集标题 Link 与独立编辑/删除；T06-browser-acceptance-20260907_1450.log | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 05 常规 | styles、PageTitle、AppShell 与八页；T35-isolated-browser-acceptance-20260909.log 的修复后标题/长风格名矩阵 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 06 常规 | styles 三轨局部滚动、响应式；T24-final-browser-matrix-20260908.log、T35、T24F | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 07 常规 | focus-visible、控件语义、reduce规则；T24D/E、T35、T24-reduced-motion-static-audit-20260909.log | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 08 常规 | 八页 mutation/确认/body 差异审计；T38-controlled-browser-20260909_1505.log 与8份独立 task DB 回读；既有 Director mutation seam 回归 | PASS；T44/postT44A普通异常矩阵、T23-B16连续组合与T24当前证据收口已核 |
| 09 常规 | statusPresentation、ShotsPage、DirectorPage；`statusPresentation.test.ts::only presents the changed shot badge for changed shots`、参数化 `presents the %s generation state`、`keeps freshness independent from generation state` | PASS；T43真实ordinary双主题逐字观测补齐，见review-t43-ordinary-20260909.log |
| 10 外部输入 | api/tasks、taskList、TasksPage；`test_c011_task_listing.py::test_task_listing_filters_before_limit_and_validates_query`；taskList.test.ts 三用例 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 11 外部输入 | TasksPage详情、taskObservation；`taskBoundary.test.tsx::expands one formal detail, preserves nulls and long error text, and does not expose payload`；taskDetailReconnect 参数化终态用例 | PASS；T40–T42/T45精确回归、七探针及T23-B16同页连续组合已独立核验 |
| 12 并发 | taskObservation取消、TasksPage按钮；taskCancel.test.tsx 三用例、taskCancelAuthority、taskCancelFilterOwnership | PASS；T40–T42/T45精确回归、七探针及T23-B16同页连续组合已独立核验 |
| 13 并发 | cancel确认/REST-WS顺序；`taskCancelRaces.test.tsx::keeps a terminal WS winner when a late POST returns running`、409用例；taskDetailEventOrder 两用例 | PASS；T40–T42/T45精确回归、七探针及T23-B16同页连续组合已独立核验 |
| 14 并发 | cancel错误归属/资源消失；taskCancelRaces 404、network、filterB、unmount用例；taskCancelFilterOwnership 两用例 | PASS；T40–T42/T45精确回归、七探针及T23-B16同页连续组合已独立核验 |
| 15 并发 | socket-first、缓冲、重连；taskObservation.test.tsx 首项与 `reconnects at 1/2/5/10 seconds, clears protocol error after sync, and stops on unmount`；taskDetailReconnect 四用例 | PASS；T40–T42/T45精确回归、七探针及T23-B16同页连续组合已独立核验 |
| 16 并发 | setQuery、listRequest/epoch；taskObservation.test.tsx 的 old filter / one in-flight 用例；taskCancelFilterOwnership | PASS；T40–T42/T45精确回归、七探针及T23-B16同页连续组合已独立核验 |
| 17 并发 | detail请求去重、事件修订、remote cancel；taskCancelIntentObservation 三用例、taskDetailEventOrder 两用例；taskObservation 首项/第三项 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 18 外部输入 | 生产 parseTask/parseTaskEvent/cancel helper；taskBoundary 的非法Task、422/500与非法WS参数矩阵、JSON与恢复用例 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 19 外部输入 | ApiErrorMessage、各页加载/错误/媒体状态；taskBoundary 错误原文，T15/T38普通日志 | PASS；T44/postT44A普通异常矩阵、T23-B16连续组合与T24当前证据收口已核 |
| 20 跨进程 | 既有create_app/TaskQueue/EventBus/WS/DB；`test_c011_task_observation.py::test_c011_cross_process_cancel_observation_matches_rest_ws_and_db` | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 21 跨进程 | 同上，queued/running/done竞争、安全点及DB只读比较 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 22 常规 | 正式页面+ordinary fixture；T24/T35/T38日志及controlled单列证据 | PASS；T44/postT44A普通异常矩阵、T23-B16连续组合与T24当前证据收口已核 |
| 23 常规 | 45checkbox/31AC/17主行、NOTES候选与commit；T28报告、当前G、当前diff | PASS；当前T23组合、52/52 checkbox、17主行、NOTES/候选与最终提交均已核对 |
| 24 跨进程 | ui_fixture prepare/verify生命周期；原T03 ordinary证据，本轮runtime两个批次独立prepare/verify | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 25 外部输入 | 正式模板GET/PATCH与人工运行配置；T24A/T38记录、本轮probe-template-contract | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 26 常规 | theme、ThemeSwitch、styles；themeWiring按钮用例；T24C、T24最终矩阵 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 27 外部输入 | theme初始化/Storage边界；theme.test.ts 默认/合法两值/非法值/read-write DOMException/未知错误7项 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 28 并发 | AppShell主题不改路由key；themeWiring三项、themePageState三项（资产意见、导演镜头选择、Clip意见/选择/scrollLeft） | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 29 常规 | BackNavigation/AuxiliaryPageReturn/项目与集页；returnLocation、projectReturnError；T24D尺寸/键盘/replace日志 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 30 常规 | styles三类checkbox与原绑定处理；T24E-browser-acceptance-20260908_145851.log、T35共享控件检查 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |
| 31 常规 | directorTrackLayout、三轨共同style；directorTrackLayout.test.ts 六项空/单/不等时长/多列/小数/向上舍入 | PASS；沿原具体用例及未受影响人工证据；当前自动回归通过 |

## T23重启调用失败的独立裁决

2026-09-10重启PID27232在engine.connect阶段输出WinError64/asyncpg ConnectionDoesNotExistError。Astra读取实际PostgreSQL服务器日志，10:37:27与10:38:56均为数据库`ai_drama_studio_c011_t23_t45_20260910`不存在；原创建/seed的精确数据库是`ai_drama_studio_c011_t23_t45_20260910_103500`。pg_isready accepting、独立psycopg只读连接完整库名成功，服务PID5544未重启。证据`review-t23-restart-diagnosis-20260910.log`；Luna对应`T23-T45-readonly-diagnosis-20260910.log`。

判定为重启调用库名错误，不是产品行为歧义或数据库故障。授权仅修正精确同库启动参数/新未存在DATA_DIR并继续T23；不重启共享PG、不改实现、不重放已取消任务。第一次失败及真实未验证状态保留，不能写成通过。实际126已在原shutdown安全点成为canceled，恢复应按该真实状态验证，不能预设failed。

## T23证据归属继续核对

585bbaa已回填T23，Astra核对原工具输出确认最终126实际点击/字段及新GET成立：review-t23-target126-cua-raw-20260910.json，后端review-t23-runtime-raw-9958dafb-53fd-45ed-80a3-ea93bd7eacac.stdout.log仅GET126一次/POST0，exit0；初始12184全记录为review-t23-runtime-raw-0f0600ee-feb3-49de-984a-6e37442f6f05.stdout.log，POST126一次。

但R2过程曾停启Vite，原type筛选和125展开状态有重置；同URL不足以证明原缓存跨越整个后端重连。上述字段/请求切片有效，不能充作未重载的完整组合。Astra要求追加同一前端进程/同一tab无goto或reload、只重启后端的最小连续组合。当前T23整体验收仍待该证据，不能提前T25。

## Astra专项复审放行（2026-09-10）

B16最小连续组合已独立核验PASS：T23-T45-B16-combo-20260910.log；原始CUA与运行时分段复原为review-t23-combo-cua-raw-20260910.json和review-t23-combo-runtime-raw-20260910.json。Vite PID29904创建10:46:27，整个02:47–02:48 UTC组合未停启，无goto/reload；另任务125展开、新目标127未展开时真实取消一次；backend29484 shutdown后只重启backend29220，点击目标前自动GET125，显式展开127后新GET127一次，无后续POST。当前展开125完整错误及时间自动重建，127始终收起到明确点击。

Astra独立psycopg只读实际输出：current_database=ai_drama_studio_c011_t23_t45_20260910_103500；127=canceled,progress0.5,cancel_requested_at=2026-09-10 10:47:39.883906+08,finished_at=2026-09-10 10:47:51.960212+08,error_msg=null。与真实AX各字段一致。受控shutdown安全点产生canceled是实际终态，不预设server restarted失败；取消语义未改变。

据此B11–B16实现/专项缺口均解除；31AC的功能、专项与既定替代验收证据可通过。本次独立复审放行T25前的代码/证据门槛，允许Luna按顺序核对T38/T39/退回旧任务→T25→T26–T28，最终AC23文档提交一致性仍待完成后核查。没有新增产品决定或未修实现BLOCK。清理仅限本批次后端/Vite；不重复同输入G。

## 必查清单收口

| 项目 | 核对结果 |
|---|---|
| 范围围栏、versioning、continuity | PASS；全量C010基线审计沿原报告；本修复没有后端app/alembic/workflows变化，未新增候选/版本/音频/continuity机制 |
| 重试与失败语义 | PASS；本轮修复维持取消失败可见、确认待同步与禁止mutation重发；WS重连属于既定观察恢复，不是业务失败重试 |
| spec外改动、DECISIONS | PASS；8f3c4bd后生产范围仅任务观察/controller接线与Director既定文案；DECISIONS无diff |
| 追溯与断言强度 | PASS；23个C011新增测试文件全部有原追溯归属，原审查逐用例映射继续有效；T40/T41/T42/T45新增回归逐行核读了请求顺序/次数、按钮防重、精确字段及错误；非只判存在 |
| 既有测试保护 | PASS；基线下唯一M为test_c009_resource_lifecycle.py::_LifecycleHTTPHandler.do_POST，成功响应与submit入队后放行原屏障；原测试/顺序/区间/失败断言未改 |
| 错误体、409/422 | PASS；后端错误合同未变，前端严格解析detail.code/message并显示完整原因；探针含非法query422、终态cancel409及敌意协议输入 |
| 任务竞态与失败、外部输入 | PASS；17个高风险AC均有当前独立探针；入队快照/生产事务通路未改，取消GET先后/terminal winner/旧query/非法ID/主题存储外部输入已验证 |
| 验收装置有效性 | PASS（限定范围）；真实create_app/lifespan/TaskQueue/EventBus/REST/WS/PostgreSQL通路，controlled handler/client与离线媒体边界明确；T44A原生行锁只控制时序，不替换响应/业务代码；不证明GPU/M6 |
| 走查粒度 | PASS；T44逐页异常含操作→观测值，postT44A导演台在途错误保留草稿/事务，T23-B16同页连续组合有实际按钮/断线/新GET/独立DB逐字段对照 |
| 探针覆盖 | PASS；七条最终独立诊断全exit0，原失败和修复前红测不删除；完整pytest未替代专项 |
| 完成证据与固定收尾 | PASS；最终2acf32a、52/52、31AC/17主行、NOTES与候选及Luna六段报告已核对 |

本轮修复未删除文件，未编辑既有测试或生产后端，未归档/推送C011、未启动C012。四份独立新回归归任务系统mock，满足探针确认BLOCK须补回归并回填追溯的要求。


## 最终结论与提交核对

- **BLOCK：无未解决项。** B11–B16均有明确根因修复或补验，探针确认的实现问题均新增独立任务系统mock回归并回填原追溯行。没有用全量通过替代专项。
- **SPEC-DEFECT：无未解决项。** 本轮文档仅补既有验收切片/装置归属/执行顺序、修正历史与当前状态，不更改产品行为或减少AC；spec开头仍为“目标与边界”“外部依赖”。
- **DEFER：** 原生全页200%与动态reduced-motion仍未动态验证。触发条件为获得合规原生缩放/媒体偏好控制能力后补相应走查；非法Router state IAB动态注入、错误pre剪贴板读回同样保留既定组合证据/工具限制，不宣称动态通过。真实GPU视频和M6质量属于C012，不纳入C011完成声明。
- **PASS：** 依据当前批准spec的全部必需门槛，C011闭环完成；未自行归档、推送或进入C012。

最终HEAD：`2acf32a5f86adb951406313f5af4b539964bd4f4`。实现最后变更为T45 `e4605bb7cbf5f59be2dc8ed38dd3a8725c1f89da`；后续均为文档/NOTES。Luna T28提交`b01381c`后，Astra仅提交三份文档的最小校正，移除顶部仍称“唯一待T28”的矛盾，并精确标明T43 ordinary、T45摘要/raw、当前前端与旧G后台的适用范围。

实际最终只读核对结果见`review-commit-consistency-20260910.json`：
```json
{"head":"2acf32a5f86adb951406313f5af4b539964bd4f4","checked":52,"unchecked":0,"ac":31,"primary_trace":17}
```
`git diff --check`退出0；暂存区为空；相对e4605bb的frontend/backend差异为空；相对4bd3a71的backend/前端依赖差异为空；相对C010的backend/app、alembic、workflows、DECISIONS差异为空。工作树仅用户原有` M AGENTS.md`和`?? .work/`。未把这些纳入提交。两批后台29484/29220实际退出0、Vite中断退出1，最后52223/53223无监听、上述后台与Vite29904进程均不存在；未重启共享PostgreSQL。

本轮实际七条独立探针全部退出0，前端全量34 files/174 tests、build68 modules退出0；完整backend实际348 passed in239.87s、Alembic三步退出0来自上述同输入Astra G。Luna为退回原task另外实际运行了status/task观察/详情/取消/竞争/权威/重连、theme与director定向套件，均退出0；未再次启动无变化的完整G。

Luna六段报告：`luna-completion-20260910.md`，由原任务实际报告原文保存并由Luna补齐B11–B16映射、真实异常分支、删除项及未验证限制；Astra已核读最终全文。对应原始验收记录已独立核对。NOTES已追加本轮已验证事实；DECISIONS保持只读，候选是将既有校验工作路径+search/hash、辅助页无业务状态与replace返回明确为跨change约定，供Astra/需求方后续评估，未自行采纳。本轮修复无文件删除；现有C011历史失败与原报告均保留。
