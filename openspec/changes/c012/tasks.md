# C012 执行任务

规划基线 `c0830c3`；实际执行状态以各项 checkbox 和对应证据为准。先读本 change spec 与已修订 PRD R2。依赖是完成门槛，不以“已写代码”代替。不得修改任何既有测试；新回归文件一次写清本 task 的全部用例。红测仅在明确的诊断 task 中按预期失败验收，不得把装置启动失败冒充缺陷复现。

## 命令与执行纪律

- `B:` 表示 CWD=`D:\ai_drama_studio\backend`，`R:` 表示 CWD=`D:\ai_drama_studio`；下列命令省略该前缀时仍按明确标注的 CWD 执行。
- B命令前由T01提供本批显式DATABASE_URL/DATA_DIR；CLI的C012_BASE_URL为实际已核验的后端地址，不提供虚构常量。pytest不能使用真实M6库，正式模板与GPU不得由pytest连接。
- `.work/c012/acceptance.py` 及所有 `test_c012_*.py`、`taskSlowConsumerReconnect.test.tsx` 都是计划新交付文件，不代表当前存在。命令运行必须保存原始stdout/stderr/exit；运行元数据列出commit、库名和DATA_DIR但隐藏DSN凭据。
- G1=T16，G2=T33；2026-09-11审查修复阶段完整回归为T49。完整回归不逐task运行；前端/后端/文档分开按影响面验收。同受测输入按AGENTS列commit、差异、环境、命令、原日志和exit后复用。失败或输入改变后的旧结果不得充当最终通过。
- task内发现工具参数、依赖初始化、工作目录、进程调用、事件循环或日志采集缺陷，允许在当前授权装置范围诊断修复并另批运行相关检查；保留首次失败。不得改断言/业务语义、重试生产失败任务、跳过必需门槛或绕过安全层。产品语义/PRD冲突仍停止上报。

## T22 阻塞期间的调度授权

需求方本轮批准按 spec §1.1 并行推进独立工作。T22 保持发布门槛，按需求方最新批准的背景配角可省略条件复核；已有单次诊断不再追加生成。Luna 统一协调真实模型线和示范线，最多一名执行者承担受控线，禁止真实 GPU 并发。

- 真实线：T21→T23→T24→T25→T26；不再以 T22 通过作为 T23 的开工条件，当前模板/服务门槛仍必须满足。T22 检验项目与示范项目分离。
- 受控线：T02基础装置+T19→T02A；T02完整交付+T02A+T16+T19→T27→T28→T29→T30；独立库/目录/端口和 stub，不能借用示范媒体或触碰真实 GPU。
- 汇合：T22+T26+T30→T31→T32→T33→T34→T35→T36。任何未通过项仍未完成，不以其他线成功替代。
- 同一条线按序逐 task 验收，失败保留证据并暂停该线后继；共用缺陷暂停全部受影响线。不因调度变化重跑已可复用全量测试。
- Luna 独占共享文档/acceptance.py、真实服务与提交；受控执行者仅写 T27–T30 指定新测试及独立批次日志，另按 T02A 明确授权修改其 worktree 内的装置副本；不改已有测试、生产代码或共享文档。回填与提交串行，保留其他执行者和用户改动；固定装置输出串行采集并立即另存，防止证据覆盖。

## A. 锁风险与唯一性前置

- [x] T01 核定基线、隔离环境与现有回归入口
  - 依赖：无。交付：记录当前git状态、已有用户改动；为目标回归、旧库迁移、正式M6各划分独立库/DATA_DIR用途；核验可创建隔离PostgreSQL及本地binding loader，提供后续显式环境。只创建本task所需回归库，不启动GPU或使用用户业务库。
  - R：无；PRD §6.1、§10、§12.1/12.4；AC-01/02。
  - 验收：R `git status --short`、`git rev-parse HEAD`；B `python -m pip show sqlalchemy asyncpg alembic httpx websockets pytest`、`python -m alembic upgrade head`、`python -m alembic current`；独立只读SQL `SELECT current_database(), current_user`与预定库一致，人工核对DATA_DIR绝对路径及端口/进程归属，禁止打印密码。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 验收装置生产通路与生命周期；C012 范围与阶段回归及交付一致性。

- [x] T02 交付单一受控验收装置及其自检
  - 依赖：T01。交付：`.work/c012/acceptance.py`，完整实现spec §8的selfcheck/locks/migration/names/ws/cascade/recovery/trash子命令、合法离线媒体与隔离fixture、生产服务调用屏障、原始证据采集和owned资源清理。不代写生产handler、EventBus或业务结果；同一异步fixture使用单loop。
  - R：无；PRD §6.1、§6.4、§10；AC-02。
  - 验收：R `python -X utf8 .work/c012/acceptance.py selfcheck`；必须逐项得到真实成功exit0、故意失败非零、stderr+0不误判、启动失败停止、同源HTTP/WS/DB身份、子进程/端口/连接清理结果；记录spec §8各替代边界。仅`--help`/py_compile不算完成。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 验收装置生产通路与生命周期。

- [x] T03 固定锁图、独立回归与修复前复现
  - 依赖：T02。交付：`.work/c012/lock-order.md`枚举spec L1–L5的实际显式/隐式锁边、Task/关系/FK/索引锁和既有断言；一次性新增完整`backend/tests/task_system/test_c012_lock_order.py`（L1–L5参数），实际调用生产service/commit，不修改旧C009锁测试。
  - R：R3、R4、R12；PRD §3.2、§3.3、§6.1/6.4；AC-03/04。
  - 验收：R `python -X utf8 .work/c012/acceptance.py locks --case all`记录各格实际结果；B `python -m pytest -q tests/task_system/test_c012_lock_order.py -k L1`修复前须因目标锁等待/40P01及无死锁断言失败而红，原始错误与SQL等待关系完整；若未复现或因fixture/语义冲突失败，停止诊断，不直接改锁。此task验收的是已证实的缺陷及可运行装置，不宣称L1通过。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [x] T04 修复视频最终提交的源行锁顺序
  - 依赖：T03。交付：仅`services/clip_video_commit.py`及同一锁环直接必需的`services/generate_clip_video.py`顺序/锁后重读；遵循spec §2，保留Task条件终态、缓存、媒体补偿、入队快照和Asset→Clip既有入口合同。不修改T03测试。
  - R：R4；PRD §3.2、§6.1/6.4；AC-03。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_lock_order.py -k L1`、`python -m pytest -q tests/task_system/test_c009_clip_video_commit.py tests/task_system/test_c009_enqueue_locks.py`；R `python -X utf8 .work/c012/acceptance.py locks --case L1`。两种先锁方向都有完整take/后续排队结果和无40P01证据。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [x] T05 对齐资产编辑、换图和删除的关联锁顺序
  - 依赖：T04。交付：`services/assets.py`内上述三类路径按spec偏序取必要行锁、锁后重读；保留no-op、revision、changed/stale、R12与文件补偿。不新增全项目锁。
  - R：R12；PRD §3.2、§3.3、§6.4；AC-04。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_lock_order.py -k L2`、`python -m pytest -q tests/task_system/test_c009_enqueue_locks.py`；R `python -X utf8 .work/c012/acceptance.py locks --case L2`；含shot-bound/slot-only资产的双向交错。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [x] T06 对齐分镜文本与绑定编辑锁顺序
  - 依赖：T05。交付：`services/shots.py`按spec §2取得候选资产/Shot锁并重新验证归属与绑定；保留公开字段、422、no-op和级联，不加入分镜结构编辑功能。
  - R：R5a；PRD §3.2、§3.3、§3.4；AC-04。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_lock_order.py -k L3`；R `python -X utf8 .work/c012/acceptance.py locks --case L3`；实际绑定编辑与视频提交两方向的快照/修订结果均符合spec。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [x] T07 对齐片段创建及相关关系行锁顺序
  - 依赖：T06。交付：`services/clips.py`中create/slot/delete与同一锁环有关的查询顺序和FOR UPDATE锁表范围；其余业务原样。不得删除必要归属/占用校验。
  - R：R5、R5a、R7、R9、R12；PRD §3.3、§3.4、§6.4；AC-04。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_lock_order.py -k L4`、`python -m pytest -q tests/task_system/test_c009_enqueue_locks.py`；R `python -X utf8 .work/c012/acceptance.py locks --case L4`；同时验证create冲突、slot变化与删除后的引用/媒体赢家。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [x] T08 对齐分镜覆盖的锁顺序并关闭全部锁探针
  - 依赖：T07。交付：`tasks/gen_shots.py`既有覆盖事务的Asset/Shot/Clip及媒体关系锁按spec排列，源快照与R3失败无损保持；更新锁图的实际边与证据，不扩大队列并行度。
  - R：R3；PRD §3.2、§3.3、§6.1/6.4；AC-03/04。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_lock_order.py tests/task_system/test_c006_gen_shots.py tests/task_system/test_c006_cancel_commit_race.py tests/task_system/test_c009_enqueue_locks.py`；R `python -X utf8 .work/c012/acceptance.py locks --case all`。全格无40P01/超时且原断言保持；失败不得进入真实GPU步骤。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [x] T09 交付资产名称旧库预检与唯一约束迁移
  - 依赖：T08。交付：一条新Alembic revision、ORM唯一约束；迁移内只读冲突/非规范名称预检及明确报错，downgrade仅移除本约束；新增`backend/tests/task_system/test_c012_asset_name_migration.py`。历史两条migration不改。
  - R：R2；PRD §3.1、§4、§5资产名称约束；AC-05。
  - 验收：R `python -X utf8 .work/c012/acceptance.py migration`；B `python -m pytest -q tests/task_system/test_c012_asset_name_migration.py`、`python -m alembic current`、`python -m alembic check`。空库、合法旧库、精确/规范化碰撞、空白/非规范名、失败数据无损与down/up逐项检查；不操作真实旧业务库。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 资产名称唯一约束迁移与旧库预检。

- [x] T10 实现手动创建与重命名的名称合同
  - 依赖：T09。交付：`services/assets.py`/既有schema边界，结构化409与输入422、no-op、预期唯一约束异常映射；新增`backend/tests/api/test_c012_asset_names.py`。不改前端业务逻辑或通用错误体结构。
  - R：R2；PRD §3.1、§3.2、§5资产；AC-06。
  - 验收：B `python -m pytest -q tests/api/test_c012_asset_names.py`；覆盖同项目跨类型、其他项目、strip、大小写/内部空格、改名撞名、自身no-op、空白/NUL/索引超长；读回revision及下游确保失败无副作用。
  - 计划测试层级：API 集成。
  - 追溯行：C012 手动资产名称冲突与输入边界。

- [x] T11 实现 R2 新增候选去重与整批失败
  - 依赖：T10。交付：`services/gen_assets.py`模型边界与`tasks/gen_assets.py`候选处理、名称唯一冲突收敛、warning及原子marker；新增`backend/tests/task_system/test_c012_gen_assets_names.py`。不改正式模板，不把合法existing_id返回名称写入资产。
  - R：R2；PRD §3.1、§3.2、§6.2/6.4、§7；AC-07。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_gen_assets_names.py tests/task_system/test_c005_gen_assets.py tests/task_system/test_c005_invalid_existing_id.py`。逐项断言新增数量/精确内容、合法ID优先、两个warning可并存、同批首项、跨类型回滚、一次真实mock调用、marker不漂移；使用独立数据库连接核验 task 终态与 marker 同一提交，不仅断言 mock 返回。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 R2 生成候选去重与冲突失败。

- [x] T12 验证名称竞争与取消/提交原子性
  - 依赖：T11。交付：独立`backend/tests/task_system/test_c012_asset_name_races.py`，覆盖两个正式API写入、手动与生成竞争、取消与marker提交；如失败只修T10/T11归属的根因，保留原失败且不改既有测试。
  - R：R2；PRD §3.1、§3.2、§6.1/6.4；AC-08/09。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_asset_name_races.py tests/task_system/test_c005_cancel_commit_race.py`；R `python -X utf8 .work/c012/acceptance.py names`。实际独立连接锁等待、一胜一409/生成同类型复用、异类型failed及精确DB行/marker必须有原始结果。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 资产名称并发与任务原子提交。

## B. 慢客户端保护与阶段回归

- [x] T13 实现有界订阅及溢出通知
  - 依赖：T12。交付：`tasks/events.py`的256容量、溢出注销/owner通知，健康发布顺序及非阻塞不变；新增`backend/tests/task_system/test_c012_event_bus.py`。沿用既有EventBus，不加第二通道或事件表。
  - R：无；PRD §5任务、§6.1/6.4；AC-10。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_event_bus.py`；发布256/257、两个订阅、重复unsubscribe、无QueueFull泄漏与无业务回放逐项精确断言。
  - 计划测试层级：任务系统 mock。
  - 追溯行：C012 EventBus 有界订阅与慢连接释放。

- [x] T14 实现 WS owner 超时关闭和子任务释放
  - 依赖：T13。交付：`api/tasks.py`发送10秒上限、溢出/发送异常关闭、同时完成事件处理、取消后await；新增`backend/tests/task_system/test_c012_ws_lifecycle.py`。不修改Task REST或事件JSON字段。
  - R：无；PRD §5任务、§6.1/6.4；AC-11。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_ws_lifecycle.py tests/task_system/test_c012_event_bus.py`；R `python -X utf8 .work/c012/acceptance.py ws`。受控ASGI慢send与真实网络WS分开记录，1013/日志、连接基线、零pending子任务、Task不误failed及健康订阅均验证。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 EventBus 有界订阅与慢连接释放。

- [x] T15 验证慢连接关闭后的真实页面重建
  - 依赖：T14。交付：新增`frontend/src/features/tasks/taskSlowConsumerReconnect.test.tsx`，挂载生产TasksPage验证关闭→重连→列表/展开详情权威GET。现有协调器若有缺陷，只修该实际路径并补记录，不改旧测试。
  - R：无；PRD §5任务、§6.1、§9；AC-12。
  - 验收：R `npm.cmd --prefix frontend run test -- src/features/tasks/taskSlowConsumerReconnect.test.tsx`、`npm.cmd --prefix frontend run test -- src/features/tasks`、`npm.cmd --prefix frontend run build`；真实浏览器在T02受控后端经现有页面展开任务、观察连接异常/终态重建，记录该页面自己的详情GET与生成/取消POST零增加。
  - 计划测试层级：任务系统 mock。
  - 追溯行：C012 慢连接后的页面权威重建。

- [x] T16 G1 前置修复阶段完整回归
  - 依赖：T15。交付：锁顺序/唯一约束/慢连接修复后的一次完整回归与阶段报告，确认没有未完成必需门槛再进入模板/真实M6。
  - R：R1–R12（含R5a，既有全套回归）；PRD §3、§6、§11 M6；AC-01/25。
  - 验收：新隔离仅迁移库，B `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、`python -m pytest -q`；R `npm.cmd --prefix frontend run test`、`npm.cmd --prefix frontend run build`、`git diff --check`。实际计数/exit/受测输入完整记录，旧C011全量不能替代本次。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 范围与阶段回归及交付一致性。

## C. 正式输入、部署与真实 M6

- [x] T17 整理四份批准模板为正式部署输入
  - 依赖：T16及spec外部依赖中的批准正文。交付：`backend/deployment/templates/`四个固定key的UTF-8 txt与`backend/deployment/README.md`批准来源说明；恢复C007单一zimage原文，逐字核对，不根据长度或spec概述重新创作。
  - R：R11；PRD §7、§11 M6、§12.2；AC-13。
  - 验收：人工逐字对照原批准正文与四文件，记录换行/末尾换行及来源；R `git diff -- backend/alembic backend/workflows`确认此task无迁移/workflow变化；缺原文保持阻塞，不提交伪造文件。模板部署驱动验收尚未到本task。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 四份正式模板生产部署：全新生产等价库迁移后仅经设置 API 安装 `script2assets/script2shots/zimage/minimaxh3`，安装后及后端重启后四个 key 齐全、与批准输入逐字一致且无占位。

- [x] T18 交付显式模板部署 CLI 与失败合同
  - 依赖：T17。交付：`backend/app/deploy_templates.py`、独立`backend/tests/api/test_c012_template_deployment.py`；复用正式设置API/httpx，install/verify、预检先于PATCH、部分提交说明与无retry按spec §5；完善部署README的实际命令。
  - R：R11；PRD §5设置、§7、§11 M6、§12.2；AC-14。
  - 验收：B `python -m pytest -q tests/api/test_c012_template_deployment.py`；输入缺失/未知/非法UTF8/占位/缺变量、HTTP失败、内容不一致、verify零PATCH全部精确计数与错误；另在独立后端/CLI进程间令第三个PATCH在进入写入前显式失败，独立DB回读前两项已提交、后两项保持基线，进程非零且没有后续PATCH；CLI无自动重启、无SQL写入、无lifespan seed。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四份正式模板生产部署：全新生产等价库迁移后仅经设置 API 安装 `script2assets/script2shots/zimage/minimaxh3`，安装后及后端重启后四个 key 齐全、与批准输入逐字一致且无占位。

- [x] T19 交付真实输入与被动验收观测能力
  - 依赖：T18。交付：同一`.work/c012/acceptance.py`扩展spec §8的preflight --real/verify-inputs/observe --real；从spec §6.1逐字保存`backend/deployment/m6-script.txt`，记录三连跑追加句与两个动作片段目标。只新增观测能力，不接入生成重放器。
  - R：无；PRD §7、§10、§11 M6、§12；AC-02/16/18。
  - 验收：R `python -X utf8 .work/c012/acceptance.py verify-inputs`、`python -X utf8 .work/c012/acceptance.py selfcheck`；全文与spec逐字相等且不超实际SCRIPT_CHAR_LIMIT，observer无mutation、无DB种业务数据，来源/失败/清理自检通过。自检使用隔离端点，不冒充真实服务通过。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 验收装置生产通路与生命周期；C012 真实外部依赖与GPU资源归属。

- [x] T20 现场验证真实外部依赖与资源归属
  - 依赖：T19；外部依赖实际满足。交付：本轮DB/DATA_DIR/配置、vLLM模型/sleep、Comfy队列/节点/绑定/LoRA和端口进程归属报告。只启动缺失且明确属于本轮的服务，不终止用户未知任务。
  - R：无；PRD §6.3、§8、§10、§12.1/12.3/12.4；AC-16。
  - 验收：R `python -X utf8 .work/c012/acceptance.py preflight --real`；实际health、object_info、queue、sleep(level1)/wake/is_sleeping和独立DB身份逐项记录；地址/模型/权重缺失保持spec外部依赖阻塞，不修改workflow或猜参数绕过。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 真实外部依赖与GPU资源归属。

- [x] T21 全新生产等价库安装四模板并重启回读
  - 依赖：T20。交付：新M6库仅迁移、默认后端启动、部署与两次verify证据；记录原始4占位key基线与实际输入逐字比对，禁止复制旧库。该库此后专供真实示范链路。
  - R：R11；PRD §7、§11 M6、§12.2；AC-15。
  - 验收：B `python -m alembic upgrade head`；`python -m app.deploy_templates --base-url "$env:C012_BASE_URL" --input-dir deployment/templates --mode install`、同参数`--mode verify`；显式关闭并重启同库后端，再执行同一verify命令。两次集合GET全文一致、无占位、verify PATCH0；记录部分失败原始结果，不自动重装。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四份正式模板生产部署：全新生产等价库迁移后仅经设置 API 安装 `script2assets/script2shots/zimage/minimaxh3`，安装后及后端重启后四个 key 齐全、与批准输入逐字一致且无占位。

- [x] T22 真实模型三次资产提取验收
  - 依赖：T21。交付：独立检验项目的三次任务、请求快照、集合A与三次DB/API回读；从正式浏览器录入同一原文、两次生成，再仅添加spec追加句后第三次生成。
  - R：R2；PRD §3.1、§3.2、§7、§11 M6；AC-17。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`被动记录；人工按spec §6.2逐步操作；断言第二次新增0/A逐字段相同；第三次新增0或仅陈宁character+1，且A不变。陈宁未输出可接受，不得把合法新增候选被后端丢弃当作允许省略。优先复用 task #1–#3 原始请求快照、各阶段 DB/API 结果及 task #4 单次诊断，以只读对比和人工复核完成，不再提交生成任务、不跑全量 pytest。新增 `.work/c012/T22-reassessment.md` 逐项列新条件/观测/证据、原失败与响应缺失限制；原比较报告/日志保留不改。复核全部满足后回填追溯、勾选并提交；其他模型失败、非陈宁额外新增、已有项变化仍失败，不直接SQL/改模板/重跑到绿。未新增时明确本批不证明真实新增人物，插入/去重仍引用 T11/T12 已有正式证据。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 真模型三次资产提取。

- [x] T23 示范集真实生成资产及参考图
  - 依赖：T21及当前真实外部依赖；不依赖T22通过。交付：通过真实UI创建新示范项目/集、选定并记录风格、录入spec全文、完整资产提取；为两个动作段所需参考人物/场景出图并选择current，保存真实任务与媒体/快照证据。
  - R：R2、R4、R9、R11；PRD §2.1、§3.1/3.5、§6.2/6.3、§11 M6；AC-18（前半）、AC-16。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`；人工逐个正式生成按钮→task→PNG画廊/current→独立DB回读；至少人物、场景各一条真实Z-Image；两个链路分别消费script2assets/zimage正式正文，无后台补资产/上传假图代替生成。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback。

- [x] T24 示范集真实生成整集分镜并预检创建两个片段
  - 依赖：T23。交付：真实script2shots任务、整集分镜、两个目标连续同场景片段的preview/request/slots/current参考证据；记录精确Shot/Asset/Clip ID，不硬编码历史ID。
  - R：R1、R3、R5、R5a、R6、R7、R8、R9；PRD §3.1/3.4、§7、§9、§11 M6；AC-18（中段）。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`；真实UI“生成分镜”→分镜内容核对→A/B分别preview/create；回读顺序、候选、1..9引用、duration与固定slot映射；本轮按spec §6.2仅经正式UI修改原Shot description补齐抬眼/指向，不重跑整集分镜生成、不改其他字段；GET/DB逐字段核验revision及changed/stale后才重勾T24。原动作预检漏检及旧分镜证据保留，不能直接种分镜或混合场景。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback。

- [x] T25 示范集两个真实片段视频与 take 回读
  - 依赖：T24。交付：A/B分别真实生成、可播放MP4、actual_duration、画廊/current和四模板消费全链证据；记录每个task的正式请求、payload/进程/GPU/文件通路。
  - R：R4、R6、R9、R10、R11；PRD §3.2/3.4/3.5、§6.2/6.3/6.4、§11 M6；AC-18（完成）、AC-16。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`；人工真实UI生成两次、打开take/切current、媒体播放；独立只读DB和正式REST逐字段一致、视频可解码且actual>0、当前take引用正确；结束queue空/sleeping/temp0。本轮仅对原两个Clip各显式提交一次新视频任务（总计最多两次），必须另保存新payload的Shot修订与动作、新built_prompt、take/current和原始exit；不改seed抽到绿，旧take保留。T25因修正后输入重开，旧技术通过记录不删除；新输入/提示词缺动作立即记录失败，不擅改prompt。视觉语义由T26判定。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback；C012 真实外部依赖与GPU资源归属。

- [x] T26A 修订 MiniMax 正式模板与部署来源说明
  - 2026-09-11继续修订：定义采用同号Subject/Picture固定句式；逐镜主体/对象/说话者显式标签，画风位置消歧。仅模板与本地渲染核对，不视为模型输出或视频验收通过。
  - 依赖：T25技术证据与用户§6.3授权。仅改minimaxh3正文及部署README/范围文档，保留五变量/六段/参考与输出schema；git保留旧文。
  - R：R4、R11；PRD §3.2、§7、§12.2；AC-26。
  - 验收：逐镜人工核对模板规则；根目录 `git diff --check`；T26B本地selfcheck验证生产renderer五变量，不运行完整pytest。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 MiniMax 模板动作与逐镜保真。

- [x] T26B 交付单次提示词诊断装置
  - 依赖：T26A正文已准备。交付 `.work/c012/prompt_diagnostic.py`，只复用生产renderer/client/解析、读取原video3/4快照，单次响应保存、结构核对和finally sleep；生产通路差异见spec §6.3，不碰队列/cache/Comfy。
  - R：R4、R11；PRD §6.3、§7；AC-02/26。
  - 验收：根目录 `python -X utf8 .work/c012/prompt_diagnostic.py selfcheck`，生产渲染保留原shots/refs且五变量完整替换、旧单Shot正文被判结构不通过；无网络调用。不新建第二通用runner或正式测试。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 MiniMax 模板动作与逐镜保真；C012 验收装置生产通路与生命周期。

- [ ] T26C 验证单次模型正文并部署批准模板
  - 2026-09-11最新裁决：需求方接受指定prompt的真实Comfy生成作为T26替代验收，本项原部署路径不再是T26的前置。以下未执行操作及失败记录保留，不冒充已完成部署；候选模板的部署状态仍须在发布收口如实核对。
  - 最新状态（覆盖以下历史单次通过）：需求方授权通用性修正后，当前同版球馆 `.work/c012/T26C-clip2-20260911_132008` 与独立小样 `T26-generalization-sample-20260911_131923` 均结构exit0但内容未通过；前者有未翻译词及空对白占位，后者重排引用身份/旁白编号。完整证据与通路见 `.work/c012/T26-generalization-review.md`；未部署/生成视频，T26C保持未勾选。
  - 当前结果（覆盖以下历史状态）：用户授权循环第11轮球馆prompt经结构及逐镜人工核对通过，原始输出 `.work/c012/T26C-clip2-20260911_122039/prompt.txt`，review.md/checks.json留证，命令exit0。总11轮含1次超时，旧失败保留；Clip1模型诊断、设置部署/重启/视频均未执行，T26C整体仍不勾选。
  - 2026-09-13当前授权：不重新生成以重判已通过的T26；本轮仅为AC-26补取一次Clip1真实模型诊断，并在T26D按Clip2→Clip1各一次正式平台消费。失败即保留证据并停止后续；T47已完成的部署证据保留，实际消费未完成前不勾选T47。
  - 2026-09-13较早实际失败（旧合同）：唯一一次 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 1` exit 1，证据目录 `.work/c012/T26C-clip1-20260913_143707`。标题/镜头标签/时间标签存在，但旧合同期望切点 `[3.2,5.867]` 被模型输出为 `[3.0,5.5]`；详细描述漏掉输入 Shot1 完整对白。Subject/Picture 映射正确，无数值 existing_id/asset_id/image_id 复用；该诊断未进入平台提交/合并路径，未观察到后端丢弃。保留 `.work/c012/T26C-clip1-diagnostic-20260913.*`、`T26C-clip1-postdiagnostic-20260913.*` 与同目录 review.md；T26C、T26D、T47、T50及T34–T36不勾选。
  - 2026-09-13前一版窄修订授权（已被最新时间裁决覆盖）：需求方批准仅修订 `backend/deployment/templates/minimaxh3.txt` 的计时比例公式、逐镜对白先复制再补画面信息、删除重复 `PARAGRAPH HEADER PATTERNS` 并收拢为一套与M6无关的三镜六段示例；该版的精确计时要求不再作为当前通过门槛。其余五变量/schema/其他模板/生产代码/测试/剧本/验收标准不变。
  - 2026-09-13最新裁决：时间点只要求大致参考 `duration_est` 权重；取消 `times_exact`/精确比例/毫秒四舍五入作为通过门槛，不引入新误差阈值。仍检查镜头数量与输入一致、顺序一致、Shot1从开头开始、后续起点可解析且严格递增、起点在请求总时长内，不能倒序/负值/全部挤在起点/超时长。仅修订非对白区域的英文描述规则：subject_definitions、retention、summary、detailed_description、soundscape 用英文；asset_name、原文对白和明确屏幕文字保留原语言，合法中文名不得一概禁止；不做模型响应后字符串替换。按 A→B→C→D 验证，B先Clip1宿舍、后Clip2球馆各一次真实诊断，任一真实翻译、对白、动作或结构失败即停止且不循环；C需两批通过后重新经正式设置API部署/重启回读，D再按Clip2→Clip1各一次正式视频。
  - 2026-09-13较早修订批次实际失败：使用磁盘修订模板仅执行一次 Clip1 宿舍诊断，命令 exit 1，证据目录 `.work/c012/T26C-clip1-20260913_145948`，实际模板全文另存为同目录 `template.txt`。结构检查 headings/shot labels/time labels=true，但期望切点 `[3.2,5.867]`、观察值 `[3.6,6.1]`；两条输入对白均逐字存在，但描述混入中文服装词。输入 Shot2 description 本身包含“抬眼看向门口的芳嘉蔓”，因此输出 Subject1 门口目标不能判为无输入依据；Shot2 retention 的可见性依据不确定，不定性为身份映射错误。无数值 existing_id/asset_id/image_id 复用；未进入平台 Task/Comfy/合并路径，不能归因后端丢弃。Clip2、修订正文部署及 T26D 均未执行，T26C/T26D/T47/T50及T34–T36保持未勾选。
  - 2026-09-13当前修订批次 Clip1 诊断：使用磁盘修订模板仅执行一次 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 1`，wrapper exit 0，证据目录 `.work/c012/T26C-clip1-20260913_152658`，实际模板全文另存为同目录 `template.txt`。结构检查 headings/shot labels/time labels/time_axis/english_non_dialogue 均为 true，观察起点 `[3.0,5.5]` 在新合同下有效；两条输入对白均逐字存在。原人工复核记录了 Shot2 未重复“坐在书桌前”，Astra根据用户最新连续场景裁决确认该非核心姿态可由前镜/整体场景承接，不作为本批阻塞；原始输出没有被改写，后续视频仍须观察姿态与空间衔接。Subject/Picture 引用与输入有依据，无数值 existing_id/asset_id/image_id 复用；本批未进入平台 Task/Comfy/合并路径，不能归因后端丢弃。后检 tasks=15/active=0、Comfy=0/0、vLLM sleeping=true，完整审查及裁决附录见同目录 `review.md`。按新裁决继续一次 Clip2 诊断；两批通过前 T26C/T26D/T47/T50及T34–T36保持未勾选。
  - 2026-09-13当前修订批次 Clip2 诊断失败：使用同一磁盘修订模板仅执行一次 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 2`，wrapper exit 1，证据目录 `.work/c012/T26C-clip2-20260913_154409`，实际模板全文另存为同目录 `template.txt`。结构检查 headings/shot labels/time labels/time_axis=true，但 `english_non_dialogue=false`，原始未译片段为“两侧设有观众席”，时间起点 `[3.0,5.5,8.0]` 满足当前合同。人工逐镜发现 Shot1 详细段落漏掉输入要求的球员出场方向注视与明确指向动作，summary中的 pointing 不能替代该镜核心动作；Shot2与Shot4还各输出了禁止的 `No dialogue.` 空对白占位。两条输入对白逐字存在，3个Subject/Picture参考映射正确，无数值 existing_id/asset_id/image_id复用。本批未进入平台 Task/Comfy/合并路径，不能归因后端丢弃；后检 tasks=15/active=0、Comfy=0/0、vLLM sleeping=true，完整审查见同目录 `review.md`。按失败即停，当前候选正文部署/重启回读、T26D及正式视频未执行，T26C/T26D/T47/T50及T34–T36保持未勾选。
  - 2026-09-13本轮新候选历史基线核对：重新取 `5446972a5695652a595e44a2696ea29e451202e4` 的 `minimaxh3.txt`（10,756 bytes、86行）及同内容 `T47-deployment-proposal.txt`；该基线与当时工作树逐字相等，production renderer 使用 `T26C-clip2-20260911_122039` 冻结输入回放原请求逐字相等，`script2assets/script2shots/zimage` 相对基线未变，网络/生产写入为0。原始证据 `.work/c012/T26C-baseline-validation-20260913.*`。随后已授权的 T26C 定向修订提交继续改变 tracked 模板；本条只保留历史基线事实，不把它写成当前模板状态。
  - 2026-09-13本轮新候选 Clip1 诊断失败：以基线重建后的同一模板仅执行一次 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 1`，wrapper exit 0、结构检查 exit 0，但人工逐镜发现输入 Shot1 的完整对白未出现在对应 `[Shot 1]`，仅 Shot2 对白逐字出现；这是模型漏提。Shot1动作与Subject/Picture映射有输入依据，未见错误 existing_id/asset_id/image_id复用；本批未进入平台 Task/Comfy/合并路径，不能归因后端丢弃。证据目录 `.work/c012/T26C-clip1-20260913_161430`，原始 wrapper `.work/c012/T26C-candidate-clip1-20260913.*`，终态观察 `.work/c012/T26C-candidate-clip1-postobserve-20260913.*` 与同目录 `review.md`。按失败即停，不执行 Clip2、部署/重启或正式视频；T26C/T26D/T47/T50及T34–T36保持未勾选，旧 T22/T23/T26 证据不变。
  - 2026-09-13本轮定向根因排查与窄修订（待Clip1复验）：只读对照 `.work/c012/T26C-clip1-20260913_161430` 与已保留的 `.work/c012/T26C-clip1-20260913_152658`，确认当前 rendered-prompt/request 含 Shot1 完整对白，raw response 与生产 `_built_prompt` 提取结果均缺该对白；`finish_reason=stop`、current completion=937、total=4198，request 无 `max_tokens`，GET `/v1/models` 的 `max_model_len=16384`，没有截断或解析丢失证据。152658 请求与 raw response/提取均含该对白；两批 production `_built_prompt` 均与 response 内 JSON prompt 逐字相等。当前候选输出仅有 Subject/Picture 标签，不含数值 existing_id/asset_id/image_id，且未进入 Task/Comfy/merge，故本次仍只能归为模型漏提，后端丢弃不可测且未见；完整只读输出 `.work/c012/T26C-targeted-root-cause-20260913.*`。仅修改 COPY DIALOGUE 局部一句：非空对白在既有镜号/时间、景别/运镜/场景 lead-in 后立即写入同一段落、先于任何动作句，完整对白出现前不得继续动作或下一项；空对白、逐字符核对、Subject/S 语法及其他规则保持不变。下一步只按授权核实 GPU 独占/空队列后执行一次 Clip1；本条不勾选T26C，不进入Clip2。
  - 2026-09-13本轮定向修复实际失败：沿用同一冻结 Clip1、同一模型参数及 strict minimaxh3 schema，仅执行一次 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 1`，wrapper exit 0，证据目录 `.work/c012/T26C-clip1-20260913_164318`，完整 wrapper 日志 `.work/c012/T26C-targeted-clip1-20260913.*`。结构检查 headings/shot labels/time labels/time_axis/english_non_dialogue/empty_dialogue_clean 全为 true，观察起点 `[2.5,5.0]`；两条非空对白均已在原始 response/提取 prompt 中逐字出现，Shot3 空对白无 speech/placeholder。但 Shot1、Shot2 都先输出动作句，再另起对白行，未满足本轮 COPY DIALOGUE 要求的“景别/运镜/场景 lead-in 后立即对白、先于动作句”；完整逐镜结果见同目录 `review.md`，故本次仍失败。分类保持：模型先前的漏提症状本次恢复，但模型未遵守对白顺序；无错误 existing_id/asset_id/image_id 复用；未进入平台 Task/Comfy/merge，后端丢弃不可测且未见。终态只读观察 `.work/c012/T26C-targeted-clip1-postobserve-20260913.*` 显示 tasks=15/active=0、Comfy=0/0、vLLM sleeping=true。按失败即停，不进入Clip2、部署/重启或正式视频，T26C/T26D/T47/T50及T34–T36保持未勾选，T22/T23/T26旧证据保留。
  - 2026-09-13 Astra验收解释更正：保留上条“先按对白先于动作文字而停止”的历史记录，但该停止把 COPY DIALOGUE 的提示编排策略误当成独立 AC，属于验收解释错误。对 `.work/c012/T26C-clip1-20260913_164318` 的现行核对应改为：Shot1/Shot2 完整原文对白逐字出现在各自 `[Shot i]` 标签之后、下一镜标签之前，说话人 Subject/S 正确；换行或对白相对动作句的位置不单独判失败，不能声称模型遵守了“先写”策略。结构/时间轴/英文/空对白检查均通过，Clip1对白目标通过，T26C仍等待本候选 Clip2 诊断；不重跑Clip1，不改原始请求/响应/模板/测试，不提前勾选T26C。
  - 2026-09-13 B阶段 Clip2 单次诊断完成：在 Clip1 对白目标按 Astra 更正通过后，核实服务/队列并沿用同一候选、同一冻结 Clip2 仅执行一次 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 2`，wrapper exit 0，证据目录 `.work/c012/T26C-clip2-20260913_165146`，原始日志 `.work/c012/T26C-targeted-clip2-20260913.*`。结构 checks 全 true，时间起点 `[3.0,5.5,8.0]`；四镜逐项保留 Shot1 球员出场方向注视/明确指向、Shot2/4 僵住及瞳孔/嘴部变化，两条对白逐字、Subject/Picture 顺序正确、空对白无占位、非对白英文。raw response 无数值 existing_id/asset_id/image_id；未进入 Task/Comfy/merge。postobserve `.work/c012/T26C-targeted-clip2-postobserve-20260913.*` 为 tasks=15/active=0、Comfy=0/0、vLLM sleeping=true。B阶段两批当前诊断均满足现行合同，按授权进入 C：正式 install、安装后 verify、同库安全重启与重启后 verify；T26C仍待C完成后再勾选。
  - 2026-09-13 C阶段完成：保留 `verify-inputs` 因工作树 CRLF 导致的 exit 1（`.work/c012/T26C-formal-verify-inputs-failure-20260913.*`），按 HEAD blob 原始 bytes 恢复 `backend/deployment/m6-script.txt` 为 LF；修正后的 `verify-inputs` 与显式环境 `preflight --real` 均 exit 0。正式 API install 输出 `installed=script2assets,script2shots,zimage,minimaxh3`，安装后 verify、同库安全重启后 verify 均 exit 0；安装后/重启后 API 与 asyncpg 回读确认四 key 齐全、正文逐字等于部署输入、无 `[占位]`，目标 DB/DATA_DIR 一致，重启无自动 PATCH。证据为 `.work/c012/T26C-formal-{verify-inputs-pass,preflight,install,verify-after-install,verify-after-restart,readback-after-install,readback-after-restart}-20260913.*` 及重启日志；C阶段完成，正式 D 阶段的 Clip2 内容失败另按 T26D 记录。
  - 2026-09-13五点候选 B 阶段：以 HEAD 当时的 12,221-byte/88-line `minimaxh3.txt` 为基线，按授权合并引用名加引号、逐句/动作从句按源顺序转写、同镜完整对白、无关 miniature 两动作/局部静止示例及尾部重复自检删除；当前候选为 10,146 bytes/79 lines，快照 `.work/c012/T47-template-five-point-20260913.txt`，精简 diff `.work/c012/T47-template-five-point-diff-20260913.patch`，A `selfcheck` exit 0，真实 `preflight --real` exit 0。Clip1 仅一次目录 `.work/c012/T26C-clip1-20260913_183540`，wrapper exit 0，结构/对白/动作/引用/英文按 Astra 复核通过；原始人工疑点及裁决保留在 `review.md`。Clip2 仅一次目录 `.work/c012/T26C-clip2-20260913_184107`，wrapper exit 1，唯一结构失败为非对白场景词 `两侧` 未译，其他镜头/时间/对白/空对白检查 true；未进入平台 Task/Comfy/merge，未见错误 existing_id/asset_id/image_id 复用。`observe --real` 两次均 exit 0；本候选失败即停，不进入 T26D、T47 重新部署或正式视频，T26C 当前 checkbox 保持未勾选，旧 B/C 证据不删除。
  - 最新统一逐镜结构批次：`.work/c012/T26C-clip2-20260911_104820/review.md`；场景/景别/static及空对白分支改善，但时间点变为180/350/480秒，人物标签与对白归属错误，诊断exit1。未部署/生成视频，保持未完成；全部旧证据保留。
  - 2026-09-11新批结果：Clip2诊断exit0，三组Subject/Picture定义与四镜时间检查通过；人工发现详细场景标签、景别/固定运镜及对白格式缺项，见 `.work/c012/T26C-clip2-20260911_104029/review.md`。T26C保持未通过，Clip1、部署及视频未执行；旧失败证据保留。
  - 本轮结果：Clip2修正装置后一次模型输出已恢复四镜与指向，但Picture/Subject绑定及结构不满足，exit1，详见 `.work/c012/T26-template-review.md`；Clip1、API部署/重启回读未执行。
  - 依赖：T26B、真实GPU独占和空队列。每个片段仅一次诊断，保存原始结果后人工逐镜核对；两者均通过才单次正式PATCH minimaxh3并GET/安全重启/GET。
  - R：R4、R11；PRD §3.2、§6.3、§7、§12.2；AC-15/16/26。
  - 验收：根目录先执行 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 1`，再执行同命令 `--clip 2`；装置按新合同检查镜头数量/顺序、Shot1起点、后续起点可解析递增且不超请求片长，中文检查只允许输入资产原名、对白和明确屏幕文字，人工对照原快照逐镜动作/对白/引用与英文描述，两个prompt全部通过。正式API PATCH `/api/prompt-templates/minimaxh3`，在backend目录两次 `python -m app.deploy_templates --base-url http://127.0.0.1:8000 --input-dir deployment/templates --mode verify`（安装后/同库重启后），均exit0；其他三个模板正文未变。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 MiniMax 模板动作与逐镜保真；C012 真实外部依赖与GPU资源归属。

- [ ] T26D 从正式页面生成并核验修订模板的两段视频
  - 2026-09-11最新裁决：本项作为T26前置的正式页面重生成路径已由需求方批准的“宿舍既有take复核＋指定球馆prompt真实Comfy生成”替代，不再阻塞T26。保留原路径未执行记录，不把直接Comfy结果记为平台新Task或新take。
  - 最新窄授权：需求方指定122039原始球馆prompt并接受局部通用性退化，先交付临时 `.work/c012/generate_selected_prompt.py`（命令 `python -m py_compile .work/c012/generate_selected_prompt.py`），再显式 `DATA_DIR=.work/c012/t21-m6-data` 执行一次。记录真实Comfy请求/事件/输出与AC-19视觉结果；该直接通路差异见spec §6.3，不能冒充正式Task/current或据此直接勾选本项。
  - 依赖：T26C。按Clip2再Clip1各一次正式生成，分别保存Task/新take/实际prompt/快照/媒体与时间点；原current不自动切换，失败停止后续生成，不改seed重抽。
  - 2026-09-13当前执行顺序：仅在本轮修订模板的Clip1宿舍、Clip2球馆诊断均通过且修订正文完成正式设置API部署/安装后及同库重启回读后，才从正式页面按Clip2→Clip1各提交一次；本轮总计最多两次，不使用旧T47安装回读或旧Clip2 prompt替代，任一失败停止。
  - R：R4、R11；PRD §3.2、§6.2–6.4、§7、§11 M6；AC-18/19/26。
  - 验收：人工正式UI提交→Task终态→新take详情/独立DB→完整播放；每个实际prompt与输入逐镜核对，MP4可解码且动作满足AC-19；根目录 `python -X utf8 .work/c012/acceptance.py observe --real` 记录空队列/sleeping/资源身份。一次生成失败或动作缺项保留证据，不勾选T26。不因模板改动运行完整pytest。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 MiniMax 模板动作与逐镜保真；C012 真实外部依赖与GPU资源归属。
  - 2026-09-13 D阶段按授权只提交正式页面 Clip2 一次：新 task `#16`（`gen_clip_video`）终态 `done`、progress=1、error=null；新 take `#6` 为 10.125s/H.264 960x544、DB/API 可读但 `is_current=false`，原 take `#4` 仍为 current，未提交 Clip1。完整 task snapshot、built prompt、take/Clip/Asset 回读见 `.work/c012/T26D-clip2-submit-20260913.json`、`T26D-clip2-readback-20260913.json`、`T26D-clip2-prompt-compare-20260913.*`；媒体探针与完整播放证据见 `.work/c012/T26D-clip2-media-probe-20260913.*`、`.work/c012/T26D-clip2-20260913/review.md`。输入/输出核对显示模型漏提 Shot1 的出场方向注视与明确指向，详细 Shot4 另有自相矛盾描述，且保留未翻译场景片段；抽帧/完整播放未观察到指向或第三镜动作。正确参考资产已进入 snapshot，未发现数值 existing_id/asset_id/image_id 复用；snapshot/built prompt 已持久化，raw vLLM response 未持久化，后端丢弃不可证实。按失败即停，保留 task #1–#3/T22、T26 及本轮失败证据，不重试、不提交 Clip1；T26D、T47、T50、T34–T36保持未勾选。

- [x] T26 人工核验两个片段的人物、场景及动作
  - 2026-09-11最终需求方裁决：“其实已经模拟了平台生成任务，t26裁决通过”。接受宿舍take#3复核与指定原文的真实Comfy球馆视频作为本项/AC-19替代验收。球馆指向（1.5–2.75秒）/僵住（3–5.25秒及末段）、人物/场景通过；宿舍入门（0.25–1.5秒）/抬眼（3.25–4.5秒）/继续吃饭（末段）通过。证据 `.work/c012/T26-selected-video-20260911_140139/verdict.md`；T26已通过，不再因未走T26C/D原路径阻塞。真实通路未新增平台Task/take/部署/current；保留原失败，不据此宣称整个C012发布通过。
  - 当前调度：原暂缓已由最新§6.3/T26A–D窄授权替代；原失败/未通过保留。先由 luna_worker_6 核对并补齐 T02A 与 T27→T30，worker_7 暂停；T31及最终收尾依赖不变。task #14/video #4 的 summary 含指向但 detailed_description 未保留该动作，旧关键词检查仅作文本存在性证据，不算动作保真或视觉通过。
  - 依赖：T25。交付：spec §6.2第5项逐项真假表、参考图/MP4链接、可定位时间点；每项记录实际观测，不使用“符合预期”替代内容。
  - R：无；PRD §11 M6；AC-19。
  - 验收：按最新裁决人工打开宿舍take#3与 `.work/c012/T26-selected-video-20260911_140139/gym.mp4`，对照原参考图，分别检查身份无互换、宿舍/球馆、A入门/抬眼/继续吃饭、B指向/僵住，以及主体消失/额外肢体；实际时间点见裁决报告。声音/字幕不要求；不新增像素或LLM自评自动测试。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback。

## D. 级联、恢复与发布收口

- [x] T02A 补交 cascade、recovery、trash 的实际验收入口
  - 依赖：T01及T02已有基础装置/selfcheck实测、T19。交付：仅在既有 `.work/c012/acceptance.py` 补齐三个实际分发和命令实现；不创建第二runner，不把reserved改成成功或仅删掉报错。原T02整体撤回完成，其基础装置已通过证据保留；本项通过并集成后核对T02完整交付再恢复勾选。
  - 所有权：本次明确委派 luna_worker_7 在其 `C:/Users/Administrator/.codex/worktrees/4fb3/ai_drama_studio` 副本修改该装置的三个命令及直接必需的fixture/采集逻辑；不得改其他命令语义、真实GPU通路、生产或旧测试。luna_worker_6 保留主工作区集成/共享文档/提交责任。此项是受控执行者不得修改验收脚本限制的一次明确范围扩展；双方不得同时编辑主目录脚本。
  - R：R2、R3、R4、R9、R12；PRD §3.2/3.3、§6.1/6.4、§10、§11 M6；AC-02/20/22/24。
  - 验收：在显式独立数据库/DATA_DIR、仅stub外部服务的环境，R `python -X utf8 .work/c012/acceptance.py selfcheck`、同入口 `cascade`、`recovery`、`trash`。三个命令分别实际经过spec §8规定的生产service/独立进程/数据库/文件通路并取得对应矩阵、恢复/互斥及清理证据；至少保留一条自检故意失败非零和资源退出结果。纯CLI分发、仅包装既有9 passed、空events或reserved均不算交付。原始命令/环境身份/事件/exit分批另存，不能伪造独立进程证据。此项先验证装置可用，不能替代T27/T29/T30专属用例和规定人工检查；不为本装置再写“测试测试”的独立套件，不触发完整pytest。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 验收装置生产通路与生命周期；C012 M6 全级联矩阵；C012 取消心跳失败与重启资源恢复；C012 trash 启动与定时清理。


- [x] T27 验证 M6 九行全级联及所有明确子分支
  - 依赖：T02、T02A、T16、T19及独立受控环境；不依赖T22/T26。交付：新增`backend/tests/task_system/test_c012_cascade.py`按spec §7完整九行分参数，复用生产服务/独立连接/实际媒体；在隔离受控浏览器逐格记录UI变化，不能破坏真实示范集。只补跨链路覆盖，不复制纯规则用例。需求方本轮允许按spec §7.1修复此task新增未提交测试文件：loop/engine生命周期、可达marker夹具与字段期望、数据表示、合法模板、JSON和媒体fixture；不改已提交旧测试/生产。保留首次6 failed，删除Clip的500先取traceback定位，未证明fixture原因不得擅改生产；恒真自比较改为操作前后比较。
  - R：R2、R3、R4、R9、R12；PRD §3.2、§3.3、§6.4、§11 M6；AC-20。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_cascade.py`；R `python -X utf8 .work/c012/acceptance.py cascade`；精确行/ID/revision/current和文件bytes对照，编辑/换图/绑定增删/模板变更分支逐项记录；R3成功和模型失败都验证。实施后向既有九条§3.3追溯行追加实际节点。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 M6 全级联矩阵。

  - 2026-09-11补齐回填：T02A 的 `selfcheck/cascade/recovery/trash` 受控通路均已有独立 exit 0 证据；T27 提交 `e5edebfcfaeb42ad26543d2b6f893d87eefb5b79` 的九行回归最终为 `10 passed in 6.02s`、exit 0，R `python -X utf8 .work/c012/acceptance.py cascade` 最终 exit 0。受控浏览器 batch4 逐格记录脚本/资产/分镜绑定/风格模板/删除/Clip 成功与媒体播放，R 记录九行 API/队列/handler/DB/媒体事件；证据为 `.work/c012/T27-luna-test-after-media-fixture-rerun.log`、`.work/c012/T27-luna-cascade-media-fixture-rerun.log`、`.work/c012/T27-luna-cascade-acceptance-20260911-media-rerun.json`、`.work/c012/T27-browser-ui-evidence-20260911-batch4.md`、`.work/c012/T27-browser-vllm-capture-20260911-batch4.json`、`.work/c012/T27-browser-readback-20260911-batch4.json`。首次六项失败、媒体 fixture 失败及原始装置失败均保留；本回填不覆盖 T22/T26 的边界。

- [x] T28 复核错误矩阵与外部输入边界
  - 依赖：T27。交付：spec §7错误格与当前既有用例节点对照、真实页面至少一条409/422及202立即failed的操作→观测记录。默认复用既有测试；若发现新的M6跨链路缺口，仅新增`backend/tests/task_system/test_c012_error_paths.py`并登记节点，不修改旧断言。
  - R：R1、R3、R5、R5a、R6、R8、R10、R11、R12；PRD §3、§5、§6.4、§7；AC-21。
  - 验收：B `python -m pytest -q tests/api/test_c006_generate_shots.py tests/api/test_c008_review_error_codes.py tests/api/test_c009_generate_video.py tests/task_system/test_c009_review_precheck_matrix.py`；新缺口有文件时另运行`python -m pytest -q tests/task_system/test_c012_error_paths.py`；人工错误体/POST次数/任务未claim/媒体错误路径检查。所有格必须有具体节点或人工证据。
  - 计划测试层级：任务系统 mock。
  - 追溯行：C012 M6 错误与敌意输入回归。

- [x] T29 验证取消、心跳DB失败、崩溃恢复和单进程互斥
  - 依赖：T28、T02A。交付：新增`backend/tests/task_system/test_c012_recovery.py`，真实应用进程/DB/文件；queued/running取消与成功竞争、心跳错误/DB不可用时的真实限制、同库重启和第二实例拒绝。不加入心跳重试或伪造failed。
  - R：无；PRD §3.2、§6.1、§6.4、§11 M6；AC-22。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_recovery.py`；R `python -X utf8 .work/c012/acceptance.py recovery`。确定性进程屏障验证running→failed、queued保留/claim一次、副作用一次、advisory锁释放/拒绝、temp与连接退出；只使用本轮owned隔离进程。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 取消心跳失败与重启资源恢复。
  - 2026-09-11复核完成：原 T29 独立回归日志 `T29-luna-recovery-test-20260911.log` 为 `4 passed in 0.90s`、exit 0，原 recovery 命令日志 `T29-luna-recovery-acceptance-20260911.log` 为 status passed、exit 0；T45/T46 对同一生产 recovery 装置进行了后续完整结构化重验，未改变 T29 的取消、重启、互斥与资源边界。T29 原始日志和失败证据均保留，T46 复核使用独立库与 DATA_DIR。

- [x] T30 验证生产 trash 启动和每日清理
  - 依赖：T29、T02A。交付：新增`backend/tests/task_system/test_c012_trash_cleanup.py`，真实文件/启动进程和每日调用路径；cutoff前/恰好/之后、trash外媒体、IO失败与shutdown。仅验证生产清理，发现越界/生命周期缺陷先报告定位，不顺手扩大清理范围。
  - R：无；PRD §6.4、§10、§11 M6；AC-24。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_trash_cleanup.py`；R `python -X utf8 .work/c012/acceptance.py trash`；记录精确保留/删除文件与bytes，受控计时等待与真实启动证据分开，明确不是实际24小时长跑。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 trash 启动与定时清理。

- [x] T31 真实视频生成期间的分镜编辑与 stale 验收
  - 依赖：T22、T26、T30及真实资源前置仍满足。交付：在示范集既有一个Clip发起新的真实生成，确认owned任务running后经真实UI改相关Shot文本；记录旧payload、新take、changed/stale和双维UI，保留原示范take。
  - R：R4；PRD §3.2、§3.3、§6.2、§11 M6；AC-23。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`；人工UI生成→确认真实running→编辑→终态，独立DB/REST逐字段比较，旧payload不变、产物保存而不回写normal/fresh；B `python -m pytest -q tests/task_system/test_c009_clip_video_commit.py`补齐Clip/Asset漂移与无变化既有分支。GPU失败不自动重跑。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 真实生成中的修订竞态。

- [x] T32 汇总发布操作说明与各层证据边界
  - 依赖：T31。交付：完善`backend/deployment/README.md`：安装/启动/四模板verify/显式恢复操作、示范媒体链接、环境与依赖实测结果、失败处理；完成报告按六段记录文件commit、spec追溯、取舍、自动验证、操作→观测、沉淀。明确未验证原生200%/动态reduced-motion与真模型随机性，不把受控证据升级为真实GPU。
  - R：无；PRD §10、§11 M6、§12；AC-01/25。
  - 验收：人工对照spec 26条AC及trace全部具体节点/原始日志；`git diff --check`；核验最终报告至少一条异常分支、示范库未清空、正式模板未被矩阵fixture覆盖；确认仅保留本轮需要资源，未知用户资源不动。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 范围与阶段回归及交付一致性。
  - 2026-09-13完成：更新 `backend/deployment/README.md`，修正当前 2026-09-13 批准正文、正式设置 API install/verify/重启回读、显式 DB/DATA_DIR、恢复失败规则、示范媒体入口、R/B/真实 GPU 证据边界与未验证限制；历史 T26 诊断状态均明确标注为历史。只读人工审计 `.work/c012/T32-manual-audit-20260913-corrected.stdout.log` exit 0：正式模板与批准输入逐字相等（10756 bytes，SHA-256 `2118b57d3472bd6a25247cb0ddad658e01e77a3539faf4963de08d33e569e3fd`）、模板无 tracked diff；示范库 project #2/episode #2 存在，4 项资产、28 条分镜、3 个 Clip、5 个视频、15 个 Task，active Task=0；API health/binding healthy/valid。审计首轮因错误假定 `assets.episode_id` 失败的原始输出 `.work/c012/T32-manual-audit-20260913.stdout.log` 与 exit=1 保留，修正后未修改生产数据；当前 Comfy/vLLM 只做 GET，未知资源未停止。未新增测试，未运行会触碰 vLLM sleep/wake 的 `preflight --real`，不以该未运行项冒充真实 GPU 验收；`git diff --check` 另存于 T32 文档验收证据。

- [x] T33 G2 最终完整回归与最终输入归属
  - 依赖：T32。交付：最终实现、测试、依赖、装置与配置的完整回归证据；若与G1相应输入完全相同，按AGENTS逐套引用实际原始结果，后加测试/部署驱动对应套件必须更新。真实M6专项失败不能用G2覆盖。
  - R：R1–R12（含R5a，回归覆盖）；PRD §3、§6、§7、§11 M6；AC-25。
  - 验收：在新隔离回归库B `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、`python -m pytest -q`；R `npm.cmd --prefix frontend run test`、`npm.cmd --prefix frontend run build`、`git diff --check`；原始exit全部0，记录实际数量与受测commit，不固定348/174，媒体示范库不参与pytest。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 范围与阶段回归及交付一致性。

## F. 2026-09-11 Astra 审查修复（luna_worker_6）

以 spec §11 和 `.work/c012/review-20260911.md` B1–B7 为准。默认按T37→T46执行；T47模板缺批准证据时留阻塞，可独立推进T48/T49并报告，不能进入T50/最终收尾。不要因旧任务重开而从T01重跑；旧通过记录保留但不能覆盖本轮缺陷。T37–T39内明确允许先运行新回归取得预期业务红测，再最小修复后运行绿测；其他未预期失败按装置/实现/需求归因处理。已提交测试和审查探针只读，新增独立回归文件；不派发其他worker，不使用真实GPU运行普通测试。

- [x] T37 修复合法 existing_id 的名称校验顺序（B1）
  - 依赖：本轮文档/追溯已登记。交付：新增 `backend/tests/task_system/test_c012_gen_assets_reuse.py`，生产handler+真实事务覆盖合法ID的空白/NUL/超长字符串不采用、原行全部字段不变、done/快照marker；同输入在null/非法/跨项目ID分支failed且无半批；warning比对真实复用ID。随后仅修 `services/gen_assets.py` 与直接必需的 `tasks/gen_assets.py`，不放宽新建/改名边界。完成后复核恢复T11。
  - R：R2；PRD §3.1、§6.2、§7；AC-07。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_gen_assets_reuse.py tests/task_system/test_c012_gen_assets_names.py tests/task_system/test_c005_gen_assets.py`；新回归业务红测→修复后全部绿测；运行原B1探针的合法ID分支，检查完整Task/marker与原资产，单次wake/chat，无retry。新库/DATA_DIR保存证据。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 R2 生成候选去重与冲突失败。

- [x] T38 修复锁后相同分镜绑定的 no-op（B2）
  - 依赖：T37。交付：新增 `backend/tests/task_system/test_c012_shot_binding_race.py`，双独立事务同集合/不同集合交错及视频提交期间状态验证；仅修 `services/shots.py` 锁后引用比较根因。完成后复核恢复T06。
  - R：无；PRD §3.2、§3.3、§11 M6；AC-04。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_shot_binding_race.py tests/task_system/test_c012_lock_order.py -k "binding or L3"`；以pg等待证据控制相同集合两请求，最终revision只+1、集合精确相等、无虚假级联；不同集合等于合法串行赢家。原B2探针期望revision2实得2，资源释放。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [x] T39 修复 send 在途时的 overflow 关闭（B3）
  - 依赖：T38。交付：新增 `backend/tests/task_system/test_c012_ws_send_overflow.py`，覆盖已阻塞send再overflow、无overflow超时、disconnect/退出与子任务结束；仅修 `api/tasks.py` 直接生命周期。完成后复核恢复T14。
  - R：无；PRD §6.1、§6.4、§11 M6；AC-10/11。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_ws_send_overflow.py tests/task_system/test_c012_ws_lifecycle.py tests/task_system/test_c012_event_bus.py`；原B3保持10秒生产常量，overflow后应由该事件关闭而非send timeout，精确原因/1013/await完成/订阅基线，Task不变。T37–39结束后R `python -X utf8 .work/c012/probe-review-races.py`；原脚本固定环境须显式核对隔离库，可仅另存运行配置副本，记录diff，不改断言。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 EventBus 有界订阅与慢连接释放。

- [x] T40 交付真实慢关闭页面验收装置（B5前置）
  - 依赖：T39。交付：仅扩展现有 `.work/c012/acceptance.py ws --case slow-page` 的参数、受控ASGI send闸门、生产进度发布和handler释放；独立默认app/DB/DATA_DIR与真实网络WS，外部服务stub，无新增生产端点/handler替换/第二runner。输出浏览器地址、任务ID、真实overflow/关闭原因/请求日志、终态独立回读与shutdown通路。
  - R：无；PRD §6.1、§6.4、§11 M6；AC-02/11/12。
  - 验收：R `python -m py_compile .work/c012/acceptance.py`、`python -X utf8 .work/c012/acceptance.py ws --case slow-page`；原生WS实际收到1013，任务终态来自生产handler，装置事件与DB身份可核查；故意失败非零，无owned进程/连接残留。先完成装置自检，再交T41实际浏览器消费；ASGI闸门不宣称TCP拥塞。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 验收装置生产通路与生命周期；C012 慢连接后的页面权威重建。

- [x] T41 完成真实慢连接后的展开详情重建（B5）
  - 依赖：T40。交付：沿用正式TasksPage，在T40批次打开running详情→触发慢关闭→生产任务到done/failed→自动重连；保存实际UI操作、网络GET/POST与DB精确字段证据。不得停后端/SQL造终态替代。完成后复核恢复T15。
  - R：无；PRD §6.1、§9、§11 M6；AC-12。
  - 验收：R `npm.cmd --prefix frontend run test -- src/features/tasks/taskSlowConsumerReconnect.test.tsx`；人工在输出的真实地址完成上述路径，观测断线提示、socket-first及列表/详情GET、进度/error/finished_at与DB一致、POST不增加；R `python -X utf8 .work/c012/probe-review-reconnect.py`。如需修改前端生产逻辑，先报告新定位，不扩改既有组件测试。
  - 计划测试层级：任务系统 mock。
  - 追溯行：C012 慢连接后的页面权威重建。
  - 2026-09-13旧批次证据修正：批次 `t41g_20260913_181000` 的 acceptance JSON 虽为 `status=passed`，但当时装置未完整记录实际关闭原因与关闭→重连→权威 GET 的事件链，且页面首轮健康轮询保留 `protocol_error`；该批仅保留历史/部分人工观察，不计为当前 B5 证据。其失败/不完整文件不删除。
  - 2026-09-13当前 B5 浏览器批次：仅扩展 `.work/c012/acceptance.py` 的 `slow-page-browser` 受控人工窗口，将该分支外部 `VLLMClient` 显式 timeout 与 release/confirmation deadline 设为 900 秒，生产默认120秒、WS 10秒、队列/handler/提交路径不变；修正后的 `python -X utf8 -m py_compile .work/c012/acceptance.py` exit 0。独立库 `ai_drama_studio_c012_t41i_20260913_181412`、DATA_DIR `D:\ai_drama_studio\.work\c012\t41i-data-20260913_181412`、后端 `65223`、前端 `5175`、外部 stub `50603`；正式 TasksPage 将任务数量设为100并展开 running 的 Task #41，释放一次 marker 后先记录 HTTP 200 的 running/progress=0，再 arm 闸门。真实同连接 WS 关闭码 `1013`（event sequence `1339`），在途 send 被取消；生产日志的实际原因是 `send_timeout`，不是 T40 的 `subscription_overflow`。页面按实际重连 socket `1391` 后首个列表 GET `1395`、目标详情 GET `1400`，观察到 `done/100%/error=—/finished_at=18:16:33`；确认 marker 在该 DOM 观察后创建，验收 JSON `status=passed`，`limit=100` 列表读取均为 HTTP 200，浏览器 mutation POST 为0（生成 POST 127 为受控任务建立记录），目标终态与独立 DB 精确一致。人工记录 `.work/c012/T41-browser-arm-manual-20260913_181412.md`，结构化证据 `.work/c012/probe-b5-browser-evidence.json`（`ws-acceptance.json` 为同批原始输出）；owned 后端/stub/临时目录及端口清理，默认生产端口保留。该批仍只证明 ASGI 背压引发真实应用层关闭和页面权威重建，不宣称 TCP 拥塞。

- [x] T42 补齐 L4/L5 实际操作对与双向锁等待（B6）
  - 2026-09-11窄修复裁决：L5 replace→delete已取得业务红测（串行404、并发500）；仅增加 `services/clips.py::delete_clip` 锁后目标存在性复核，严格按spec末尾T42裁决，不改锁顺序/空关系损坏校验/测试。红测不是T42通过。补跑 B `python -m pytest -q tests/api/test_c008_clip_delete.py`，与本项两文件矩阵全部通过后提交并进入T43；无需Astra代写实现。
  - 2026-09-11完成：生产仅增加 `services/clips.py::delete_clip` 在 Episode 锁后、候选关系读取前的目标 Clip 存在性复核；后续 Clip `FOR UPDATE` 及仍存在但关系损坏时的 500 保持不变。指定两文件矩阵与 `tests/api/test_c008_clip_delete.py` 均已取得真实 exit 0，红测保留。
  - 依赖：T38。交付：新增 `backend/tests/task_system/test_c012_lock_edit_pairs.py`；先列§2.1可达操作对/原测试节点，无缺口的精确复用；补create/slot/delete×Asset/Shot编辑和gen_shots覆盖×上述API的缺口。每行两种持锁方向、独立事务/真实SQL后屏障、完整赢家/引用/文件断言，不以参数名代替矩阵。完成后复核恢复T07/T08。
  - R：R3、R5、R5a、R7、R9、R12；PRD §3.2–§3.4、§6.4；AC-04。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_lock_edit_pairs.py tests/task_system/test_c012_lock_order.py`；每个操作对精确串行等价、无40P01/timeout、snapshot不漂移、媒体/引用闭合及连接释放。若发现新的实现根因，保留结果并提交具体最小修改范围给Astra，不扩大本测试任务实现范围。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [x] T43 交付缓存与模板级联验收分支（B6前置）
  - 依赖：T42。交付：仅扩展既有 `.work/c012/acceptance.py cascade --case cache`，支持同一隔离app中先生成并建立缓存，再经正式设置API改变风格/对应模板，随后调用生产四类生成handler，采集真实外部请求次数/内容、payload、缓存和下游前后行/文件。仅外部stub和释放屏障受控。
  - R：R2、R3、R4、R11；PRD §3.2、§3.3、§6.2、§7；AC-02/20。
  - 验收：R `python -m py_compile .work/c012/acceptance.py`、`python -X utf8 .work/c012/acceptance.py cascade --case cache`；图/视频第一次缓存、命中、失配有实际请求/存储证据；提取模板有渲染后请求及null hash；故意子进程失败非零，无假passed、无资源残留。交付后才进入T44。
  - 2026-09-11完成：受测提交 `5afff508d586af0923a608fa28dcebc9ee38c27d` 上 py_compile 与 cascade 均 exit 0；隔离库 `ai_drama_studio_c012_t43_20260911`、DATA_DIR `D:\ai_drama_studio\.work\c012\t43-data-20260911` 的任务 #80/#81/#84 为图 miss/hit/失配、#82/#83/#85 为视频 miss/hit/失配、#86/#87 为 script2assets/script2shots，外部 schema 次数 `zimage=2,minimaxh3=2,script2assets=1,script2shots=1`，图片行 `1→4`、视频行 `0→3`；故意子进程 returncode=17，生产进程退出且临时目录删除。原始 `.work/c012/T43-pycompile.*`、`.work/c012/T43-cascade-cache.*` 与 `.work/c012/cascade-acceptance.json`，此前 placeholder/output-node/video-duration/timeout/采集类型失败证据均保留。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 验收装置生产通路与生命周期；C012 M6 全级联矩阵。

- [x] T44 补齐 R4 与在途快照、不追溯矩阵（B6）
  - 依赖：T43。交付：新增 `backend/tests/task_system/test_c012_template_cascade.py`，风格/zimage/minimax分别触发图/视频的确切hash变化和单次重建、命中无chat；script2assets/script2shots新正文与null hash；四类在途payload固定、已有下游行/文件不追溯。补齐T27后恢复其checkbox，不改既有弱断言来换绿。
  - R：R2、R3、R4、R11；PRD §3.2、§3.3、§6.2、§7；AC-20。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_template_cascade.py tests/task_system/test_c012_cascade.py`；R `python -X utf8 .work/c012/acceptance.py cascade --case cache`；完整前后值、请求次数/内容及持久化快照，禁止startswith/非空代替；同时逐格核查T27其余子分支证据，缺项如实报告。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 M6 全级联矩阵（同时回填原§3.3风格/模板编辑行）。

  - 2026-09-11完成：新增 `backend/tests/task_system/test_c012_template_cascade.py`，覆盖 style/zimage/minimaxh3 的精确 hash 变化与单次重建、命中零 chat、script2assets/script2shots changed 正文与 `input_hash=null`，以及四类在途 payload 冻结和既有下游行/文件不追溯；并复用了已完成 T27 的九格回归与原始失败证据。隔离库 `ai_drama_studio_c012_t44_20260911` 经 Alembic head 后，B 命令 `python -m pytest -q tests/task_system/test_c012_template_cascade.py tests/task_system/test_c012_cascade.py` 为 `14 passed in 10.12s`、exit 0，日志 `.work/c012/T44-test-targeted-final.log`；R 在 T43 受测库 `ai_drama_studio_c012_t43_20260911`/DATA_DIR `D:\ai_drama_studio\.work\c012\t43-data-20260911` 重用同一生产入口，`python -X utf8 .work/c012/acceptance.py cascade --case cache` 输出 `status=passed`、exit 0，原始 `.work/c012/T44-cascade-cache.log` 与 `.work/c012/T44-cascade-acceptance.json`，T43 原始快照另存 `.work/c012/T43-cascade-cache-before-T44.json`。首轮错误日志（日志落点、DATABASE_URL、旧库迁移约束、测试基线）均保留；未改生产代码、模板、剧本或既有测试。

- [x] T45 交付进程恢复与心跳故障验收装置（B6前置）
  - 依赖：T44。交付：扩展现有 `.work/c012/acceptance.py recovery --case lifecycle`；隔离真实后端/队列/handler先形成running+合法queued，终止/重启后释放queued完成真实业务产物；外部stub账本与独立DB/文件核对次数；生产worker监督中的数据库连接故障，handler及资源退出，恢复连通后重启恢复原running。不得用空payload或始终锁住queued代替。
  - R：无；PRD §6.1、§6.4、§11 M6；AC-02/22。
  - 验收：R `python -m py_compile .work/c012/acceptance.py`、`python -X utf8 .work/c012/acceptance.py recovery --case lifecycle`；两个进程实际互斥、running→failed/server restarted、queued→done且副作用1、heartbeat失败真实非零/原因和资源清理；隔离故障不能影响用户数据库或GPU，清理本轮owned连接/端口。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 验收装置生产通路与生命周期；C012 取消心跳失败与重启资源恢复。
  - 2026-09-11完成：仅扩展 `.work/c012/acceptance.py`。隔离库 `ai_drama_studio_c012_t45_20260911`、DATA_DIR `D:\ai_drama_studio\.work\c012\t45-data-20260911` 上，`python -m py_compile .work/c012/acceptance.py` 与 `python -X utf8 .work/c012/acceptance.py recovery --case lifecycle` 均 exit 0；`recovery-acceptance.json` 记录真实 running task #7 与 queued task #8，第二进程自然 returncode=3、未请求终止，输出 `AdvisoryLockNotAcquired`/`task worker advisory lock is already held`；首进程终止后 running/queued 保持，重启后 #7 为 `failed/server restarted`、#8 为 `done` 且仅 1 条 `source=generated` 资产。第三任务的数据库 `default_transaction_read_only=on` 故障记录 heartbeat 不变、任务仍 running、handler=0、无新增资产；恢复 off 后再次重启为 `failed/server restarted`。最终 owned 进程/连接/HTTP handler 清理，临时目录不存在。原始日志 `.work/c012/T45-acceptance-pycompile.*`、`.work/c012/T45-recovery-lifecycle.*`、`.work/c012/recovery-acceptance.json`；CLI、JSONB读取、PostgreSQL诊断兼容性与目录证据修正前失败分别保留在 `T45-recovery-lifecycle-failure-01.*` 至 `failure-04.*` 与 `pass-01.*`。
  - 证据归属：`recovery-acceptance.json` 是共享固定输出名，后续 T46 已另存 `.work/c012/T46-recovery-acceptance.json` 并覆盖该共享路径；T45 的当批 stdout/exit 与所有 failure/pass 快照保留，T45 具体结构化状态以后续 T46 同一装置重验为补充，不把 T46 文件倒写成 T45 独立原始 JSON。

- [x] T46 补齐重启副作用及心跳监督回归（B6）
  - 依赖：T45。交付：新增 `backend/tests/task_system/test_c012_worker_recovery.py`，精确覆盖queued/完成先胜取消、真实进程重启后queued完成一次、心跳异常不吞/handler取消/DB不可达不假报failed/恢复后重启；保留原四个C012恢复测试。完成后复核恢复T29。
  - R：无；PRD §3.2、§6.1、§6.4；AC-22。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_worker_recovery.py tests/task_system/test_c012_recovery.py tests/task_system/test_task_queue.py`；R `python -X utf8 .work/c012/acceptance.py recovery --case lifecycle`；不只断言状态集合，要分别精确单赢家、产物数量/内容与请求次数，退出无泄漏。生产根因超授权范围则报告。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 取消心跳失败与重启资源恢复。
  - 2026-09-11完成：新增 `backend/tests/task_system/test_c012_worker_recovery.py` 四个独立用例，分别覆盖 queued 取消与完成先胜、取消安全点单赢家、重启后 queued 恰一次 handler/资产副作用、heartbeat 异常传播与 handler 取消，以及 DB 不可达时 running 不伪报 failed、恢复后 `server restarted` 收口。全新隔离库 `ai_drama_studio_c012_t46_20260911` 经 Alembic head 后，B 命令 `python -m pytest -q tests/task_system/test_c012_worker_recovery.py tests/task_system/test_c012_recovery.py tests/task_system/test_task_queue.py` 为 `11 passed in 1.42s`、exit 0，stderr 为空，日志 `.work/c012/T46-test-targeted.stdout.log`、`.work/c012/T46-test-targeted.stderr.log`、`.work/c012/T46-test-targeted.exit-code.txt`；R `python -X utf8 .work/c012/acceptance.py recovery --case lifecycle` 为 status passed、exit 0，完整事件 `.work/c012/T46-recovery-acceptance.json`，DATA_DIR `D:\ai_drama_studio\.work\c012\t46-data-20260911`，库/DATA_DIR及运行状态与 T45 证据一致，最终临时目录不存在、stub handler=0。未修改既有测试、生产代码、模板或剧本。

- [ ] T47 关闭最终交付模板与部署门槛（B4）
  - 2026-09-13 最新裁决：需求方于 2026-09-13 明确“确定为最终正文”：批准 `.work/c012/T47-deployment-proposal.txt` 的 10,756-byte、86 行正文作为历史批准基线。该正文从 `T26C-clip2-20260911_122039/request.json` 的实际请求恢复，只把 ACTUAL INPUT 的五项输入值还原为既有占位符；生产 renderer 使用该批冻结输入回放与原请求逐字相等。该批 `input-snapshot.json.template_content` 是历史旧模板，不能用它替换本次批准文件。其他三个模板保持原文；不改变五变量、schema、设置 API、R4 或不追溯语义。 本次解除最终正文批准门槛，按此正文继续 T47 正式安装与安装后/同库安全重启后逐字回读，不再要求与 C009 历史正文相同，也不重开模板优化循环。保留局部通用性限制及所有历史失败。T26/AC-19 已通过的需求方裁决保持，不为重新判定 T26 生成视频；本次批准不等于已安装、已重启核验或完整 AC-26 实际消费通过，未执行项仍须逐项取证，若剩余消费路径需改变则单独报告，不静默豁免。下列 2026-09-11 核对数据保留为历史，不表示本次正文仍待批准；随后授权的 T26C 修订及当前五点候选另行记录。
  - 依赖：既有 T21 证据与 2026-09-13 需求方对 10,756-byte 最终正文的明确批准（spec 外部依赖及 T47 批准段）。正文已确定，不再以 C009 差异或旧候选失败阻塞安装；先核实目标 DB/DATA_DIR、当前任务及进程归属，再按正式 API 安装。与 CPU 线独立。
  - 交付：按本次已批准正文及 spec 的最新执行顺序，经现有正式设置API安装/安装后及同库安全重启后逐字回读，其他三模板不变；复用有效T21新库证据并核对相关输入变化，补当前正文所缺实际消费证据。不得为T26重新生成；若剩余AC-26消费路径需改动，先交需求方裁决并同步spec，不能擅自取消T26C/D或整个AC。
  - R：R4、R11；PRD §3.2、§7、§11 M6、§12.2；AC-13/15/26。
  - 验收：B `python -m app.deploy_templates --base-url "$env:C012_BASE_URL" --input-dir deployment/templates --mode verify` 两次均0（正式安装后/安全重启后）；精确四key/正文与批准输入、DB/DATA_DIR身份、实际消费源相符。运行地址现场核实；真实模型/Comfy按既有§6.3批准边界且独占，无其他任务时才操作；遇产品取舍保持阻塞而非循环抽取或覆盖模板。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四份正式模板生产部署：全新生产等价库迁移后仅经设置 API 安装 `script2assets/script2shots/zimage/minimaxh3`，安装后及后端重启后四个 key 齐全、与批准输入逐字一致且无占位；C012 MiniMax 模板动作与逐镜保真。
  - 2026-09-11只读核对：当前候选 `backend/deployment/templates/minimaxh3.txt` 为 14245 bytes/92 行、SHA-256 `3bebbc2f0412610b465acd623aa89a79342f9d994e78723582092e022ebbdb9d`；D-014/C009 指定来源 `C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md` 为 13248 bytes/113 行、SHA-256 `e2a1638cf13e2853a263ebe7db383d2c7ce222780bc4a937ca38845c48d63f7a`。`git diff --no-index --unified=3` exit 1，完整差异保留于 `.work/c012/T47-candidate-approved-diff.stdout.log`，stderr/exit 同名文件；未以长度或摘要替代逐字比较。
  - 运行库只读回读实际为 `ai_drama_studio_c012_m6_20260910`、`127.0.0.1:5432`：四个 key 均非占位；运行库 `minimaxh3` 为 13248 bytes、SHA-256 `e2a1638cf13e2853a263ebe7db383d2c7ce222780bc4a937ca38845c48d63f7a`，其余三 key 与当前三份部署输入的 SHA-256 一致。T21 的同库/DATA_DIR 重启回读仍记录四 key 精确、无占位、verify 零 PATCH；完整本次数据库原始回读见 `.work/c012/T47-runtime-template-readback.stdout.log`，摘要见 `.work/c012/T47-read-only-summary.stdout.log`及stderr/exit。
  - `T26C-clip2-20260911_122039` 原始 prompt/request/response/checks 只读核对为 model=`Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`、temperature=`0.2`、`template_matches_request=true`、`raw_response_unchanged=true`、结构/映射/英文检查为 true；`video_generated=false`。本次 T47 未运行 install、重启后 verify、新模型调用或新生成任务。批准正文与当前候选的差异没有得到新的明确批准，故 T47/AC-26 仍阻塞，不自动部署或覆盖运行库。
  - 2026-09-13完成：现场复用 T21/T31 所属 8000 后端（旧 PID `23876`，同目标库/DATA_DIR、15 个任务且 active=0）经正式 CLI install，输出 `installed=script2assets,script2shots,zimage,minimaxh3`、exit 0；安装后 verify 与同库安全重启后 verify 均输出四 key、exit 0。只停止旧 PID 23876 并以同一 `ai_drama_studio_c012_m6_20260910`、`D:\ai_drama_studio\.work\c012\t21-m6-data` 启动新 PID `33148`；健康首检为 vLLM/Comfy healthy、workflow binding valid，15 个任务仍 active=0。最终 API/asyncpg 回读四 key 恰好齐全，四份正文逐字等于当前部署输入且均非占位；`minimaxh3` 为 10756 bytes/86 行、SHA-256 `2118b57d3472bd6a25247cb0ddad658e01e77a3539faf4963de08d33e569e3fd`；重启后日志中的模板 PATCH 次数为 0。原始证据为 `.work/c012/T47-ownership-preflight-20260913.stdout.log`、`T47-install-20260913.*`、`T47-verify-after-install-20260913.*`、`T47-restart-*.{stdout.log,exit-code.txt}`、`T47-verify-after-restart-20260913.*`、`T47-readback-after-restart-20260913.*`；首次命令解析/第二次 advisory-lock 启动失败证据保留在本轮 T47 启动日志/工具输出中。未调用模型或提交生成任务，未停止外部 Comfy/vLLM；正式平台 Task/take/current 对新正文的实际消费证据仍缺失，按最新裁决单独报告，不将 T26 既有替代视觉证据升级为 AC-26 完整消费。
  - 2026-09-13本轮修订约束：上述 install/verify/重启回读只针对旧10,756-byte正文；修订模板落盘后须重新完成 C 阶段，旧证据保留但不能作为修订正文当前部署通过。T47继续未勾选。
  - 2026-09-13当前候选补证：C阶段已对当前10,756-byte正文完成正式 API install、安装后 verify、同库安全重启后 verify 及 API/asyncpg 逐字回读，四 key 齐全、无占位、DB/DATA_DIR一致；证据 `.work/c012/T26C-formal-install-20260913.*`、`T26C-formal-verify-after-install-20260913.*`、`T26C-formal-verify-after-restart-20260913.*`、`T26C-formal-readback-after-restart-20260913.*`。随后正式页面仅一次 Clip2 task `#16` 已 done 并落入 take `#6`，但 prompt/媒体实际消费未满足 AC-26，且 raw vLLM response 未持久化，故不能把安装回读升级为 T47 完成；T47保持未勾选。
  - 2026-09-13当前五点候选补证：本候选从 HEAD 前 12,221-byte/88-line tracked 模板出发，当前工作树为 10,146 bytes/79 lines，尚未经正式 API 安装；selfcheck/preflight exit 0，Clip1 经 Astra 复核通过，Clip2 唯一一次 exit 1（`english_non_dialogue=false`，未译 `两侧`），诊断未进入平台 Task/Comfy/merge。证据见 `.work/c012/T47-template-five-point-20260913.txt`、`.work/c012/T47-template-five-point-diff-20260913.patch`、`.work/c012/T26C-five-point-clip{1,2}-20260913.*` 与对应诊断目录；按失败即停，T47继续未勾选，不执行重新部署、重启回读或正式视频。

- [x] T48 核查准确用例ID、修复证据与旧任务状态（B7）
  - 依赖：T37–T46，T47的实际状态已记录。交付：核对本轮文档已补的14个准确ID，再逐条追加新增回归真实nodeid/参数；逐条将B1–B7映射到修复commit/原始输出/AC，按各修复任务恢复旧checkbox；失败/未运行保持未勾选，T26裁决不撤销。
  - R：无；PRD §11 M6；AC-01/25。
  - 验收：B `python -m pytest --collect-only -q` 对照追溯，每个新增节点至少归属一行；人工对照 `.work/c012/review-test-id-coverage.json`、当前diff与实际日志；R `git diff --check`。不因文档回填重跑全量。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 范围与阶段回归及交付一致性。
  - 2026-09-11完成：`python -m pytest --collect-only -q` 收集 `414 tests collected in 0.88s`、exit 0，stdout/stderr/exit 保留于 `.work/c012/T48-collect-only.stdout.log`、`.stderr.log`、`.exit-code.txt`；`.work/c012/review-test-id-coverage.json` 中原审查遗留的14个准确 ID逐条在追溯表定位。T37–T46 新增节点、参数、对应追溯行已逐条补入 TRACEABILITY；B1→T37 `5e06ee9`/AC-07，B2→T38 `38e576d`/AC-04，B3→T39 `6eeb530`/AC-11，B4→T47 `77da604`/AC-13/15/26（阻塞），B5→T40 `dd15a74`+T41 `a5a5d59`/AC-12，B6→T42 `5afff50`、T43 `ca38fe8`、T44 `31ea5e2`、T45 `9717892`、T46 `a77e43c`/AC-04/20/22，B7→本次文档回填/AC-01/25；各项原始失败与通过日志保留。`git diff --check` exit 0；`backend/tests` 相对审查基线仅有本轮新增测试文件，无既有测试修改；T22/T26/T31 等既有任务状态按当前文档保留，T47阻塞不改写为通过。

- [x] T49 修复阶段完整回归
  - 依赖：T37–T46、T48；T47阻塞时允许仅完成CPU线阶段验证，不能宣称发布通过。交付：覆盖最终本轮实现/测试/装置的阶段证据；本项通过后恢复T33并注明受测边界。其后模板/文档变更只按影响面补验，不重复同一全量。
  - R：R1–R12（含R5a）；PRD §3、§6、§7、§11 M6；AC-25。
  - 验收：全新隔离库 B `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、`python -m pytest -q`；R `npm.cmd --prefix frontend run test`、`npm.cmd --prefix frontend run build`、`git diff --check`。前端无变化可按AGENTS完整记录受测commit/输入/日志复用T33；后端新用例/实现改变须实际完整复跑，记录真实数量/exit，不用业务库。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 范围与阶段回归及交付一致性。
  - 2026-09-11完成CPU线：全新数据库 `ai_drama_studio_c012_t49_20260911`、DATA_DIR `D:\ai_drama_studio\.work\c012\t49-data-20260911` 上，修正 DSN 后 `python -m alembic upgrade head`、`current`、`check` 均 exit 0，head=`c012_asset_name_unique`，原始证据分别为 `.work/c012/T49-corrected-alembic-upgrade.stdout.log`/`.stderr.log`/`.exit-code.txt`、`.work/c012/T49-corrected-alembic-current.stdout.log`/`.stderr.log`/`.exit-code.txt`、`.work/c012/T49-corrected-alembic-check.stdout.log`/`.stderr.log`/`.exit-code.txt`；`python -m pytest -q` 为 `414 passed in 206.68s (0:03:26)`、exit 0、stderr为空，原始证据 `.work/c012/T49-backend-pytest.stdout.log`、`.stderr.log`、`.exit-code.txt`。首次 wrapper 的 DSN 拼接错误命中 `ai_drama_studio_c005_acceptance_20260826`，已用精确 downgrade 回到 `6b8e3f0a1d24` 并只读核对无本次唯一约束；该失败/回滚及日志路径修正均保留于 `.work/c012/T49-accidental-config-db-*`、`.work/c012/T49-backend-pytest-logging-correction.log`，不计入 T49 通过。前端自 T33 受测 commit `8886e9f` 至当前 HEAD 无 diff，复用 T33 `35 files/175 tests` 和 `68 modules` 原始日志，复用审计 `.work/c012/T49-frontend-reuse.stdout.log`/`.stderr.log`/`.exit-code.txt` 为 exit 0；`git diff --check` exit 0，`.work/c012/T49-git-diff-check.stdout.log`/`.stderr.log`/`.exit-code.txt`。因 T47/AC-26 仍阻塞，本项仅关闭 CPU 阶段并恢复 T33，不宣称发布通过、不进入 T50/T32–T36。

- [ ] T50 交付修复完成报告与发布一致性核对
  - 依赖：T47、T49，B1–B7及原26条AC必需门槛均关闭。交付：`.work/c012/completion.md` 六段报告，分别列状态/commit、spec追溯、取舍边界、实际/复用测试、操作→观测（含异常）、NOTES/DECISIONS候选及未验证；审查问题逐项给修复commit与证据。恢复T32；报告给Astra，未经复审不自行archive/push/删证据。
  - R：无；PRD §0、§11 M6、§12；AC-01/25。
  - 验收：人工逐条核对报告、spec/TRACE、checkbox、提交内容和真实exit；R `git diff --check`、`git status --short --untracked-files=no`、`git log --oneline -n 20`。若T47待决定，提前给未完成报告并列已完成CPU项，不勾T50或收尾。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 范围与阶段回归及交付一致性。

- [ ] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）
  - 标识：T34；依赖：T50。本轮修复后重新核对，仅记录实际环境/依赖/失败根因和已验证结果，不复制旧库状态为当前事实。
  - R：无；PRD §10、§11 M6、§12；AC-25。
  - 验收：人工将新增事实逐项对到原始命令/日志；R `git diff --check`。文档改动不重跑G。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 范围与阶段回归及交付一致性。

- [ ] `DECISIONS.md` 候选项已在完成报告中列出（无则写「无」）
  - 标识：T35；依赖：T34。只提炼已经验证且适用于后续change的候选；R2产品规则已在PRD，不另造相互覆盖的版本合同。
  - R：无；PRD §11 M6；AC-25。
  - 验收：人工核对报告“候选/无”与DECISIONS无重复或冲突；R `git diff --check`。未采纳候选不冒称既有决定。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 范围与阶段回归及交付一致性。

- [ ] change 文档与 commit 状态一致
  - 标识：T36；依赖：T35。仅在本表前置全部完成、26条AC都有真假证据、外部依赖门槛解除后收口；保留失败记录/限制，不顺手archive/push或纳入AGENTS用户改动。
  - R：无；PRD §0、§11 M6；AC-01/25。
  - 验收：R `git status --short`、`git diff --check`、`git show --stat HEAD`、`git ls-tree -r --name-only HEAD openspec/changes/c012`；逐项核对PRD/spec/tasks/trace与受测commit，确保非文档输入变化都有相关新证据，完成报告明确提交状态。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 范围与阶段回归及交付一致性。
