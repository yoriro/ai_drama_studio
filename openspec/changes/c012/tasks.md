# C012 执行任务

规划基线 `c0830c3`；本表全部待执行。先读本 change spec 与已修订 PRD R2。依赖是完成门槛，不以“已写代码”代替。不得修改任何既有测试；新回归文件一次写清本 task 的全部用例。红测仅在明确的诊断 task 中按预期失败验收，不得把装置启动失败冒充缺陷复现。

## 命令与执行纪律

- `B:` 表示 CWD=`D:\ai_drama_studio\backend`，`R:` 表示 CWD=`D:\ai_drama_studio`；下列命令省略该前缀时仍按明确标注的 CWD 执行。
- B命令前由T01提供本批显式DATABASE_URL/DATA_DIR；CLI的C012_BASE_URL为实际已核验的后端地址，不提供虚构常量。pytest不能使用真实M6库，正式模板与GPU不得由pytest连接。
- `.work/c012/acceptance.py` 及所有 `test_c012_*.py`、`taskSlowConsumerReconnect.test.tsx` 都是计划新交付文件，不代表当前存在。命令运行必须保存原始stdout/stderr/exit；运行元数据列出commit、库名和DATA_DIR但隐藏DSN凭据。
- G1=T16，G2=T33。完整回归不逐task运行；前端/后端/文档分开按影响面验收。同受测输入按AGENTS列commit、差异、环境、命令、原日志和exit后复用。失败或输入改变后的旧结果不得充当最终通过。
- task内发现工具参数、依赖初始化、工作目录、进程调用、事件循环或日志采集缺陷，允许在当前授权装置范围诊断修复并另批运行相关检查；保留首次失败。不得改断言/业务语义、重试生产失败任务、跳过必需门槛或绕过安全层。产品语义/PRD冲突仍停止上报。

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

- [ ] T07 对齐片段创建及相关关系行锁顺序
  - 依赖：T06。交付：`services/clips.py`中create/slot/delete与同一锁环有关的查询顺序和FOR UPDATE锁表范围；其余业务原样。不得删除必要归属/占用校验。
  - R：R5、R5a、R7、R9、R12；PRD §3.3、§3.4、§6.4；AC-04。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_lock_order.py -k L4`、`python -m pytest -q tests/task_system/test_c009_enqueue_locks.py`；R `python -X utf8 .work/c012/acceptance.py locks --case L4`；同时验证create冲突、slot变化与删除后的引用/媒体赢家。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [ ] T08 对齐分镜覆盖的锁顺序并关闭全部锁探针
  - 依赖：T07。交付：`tasks/gen_shots.py`既有覆盖事务的Asset/Shot/Clip及媒体关系锁按spec排列，源快照与R3失败无损保持；更新锁图的实际边与证据，不扩大队列并行度。
  - R：R3；PRD §3.2、§3.3、§6.1/6.4；AC-03/04。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_lock_order.py tests/task_system/test_c006_gen_shots.py tests/task_system/test_c006_cancel_commit_race.py tests/task_system/test_c009_enqueue_locks.py`；R `python -X utf8 .work/c012/acceptance.py locks --case all`。全格无40P01/超时且原断言保持；失败不得进入真实GPU步骤。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 生成提交与入队及编辑锁顺序。

- [ ] T09 交付资产名称旧库预检与唯一约束迁移
  - 依赖：T08。交付：一条新Alembic revision、ORM唯一约束；迁移内只读冲突/非规范名称预检及明确报错，downgrade仅移除本约束；新增`backend/tests/task_system/test_c012_asset_name_migration.py`。历史两条migration不改。
  - R：R2；PRD §3.1、§4、§5资产名称约束；AC-05。
  - 验收：R `python -X utf8 .work/c012/acceptance.py migration`；B `python -m pytest -q tests/task_system/test_c012_asset_name_migration.py`、`python -m alembic current`、`python -m alembic check`。空库、合法旧库、精确/规范化碰撞、空白/非规范名、失败数据无损与down/up逐项检查；不操作真实旧业务库。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 资产名称唯一约束迁移与旧库预检。

- [ ] T10 实现手动创建与重命名的名称合同
  - 依赖：T09。交付：`services/assets.py`/既有schema边界，结构化409与输入422、no-op、预期唯一约束异常映射；新增`backend/tests/api/test_c012_asset_names.py`。不改前端业务逻辑或通用错误体结构。
  - R：R2；PRD §3.1、§3.2、§5资产；AC-06。
  - 验收：B `python -m pytest -q tests/api/test_c012_asset_names.py`；覆盖同项目跨类型、其他项目、strip、大小写/内部空格、改名撞名、自身no-op、空白/NUL/索引超长；读回revision及下游确保失败无副作用。
  - 计划测试层级：API 集成。
  - 追溯行：C012 手动资产名称冲突与输入边界。

- [ ] T11 实现 R2 新增候选去重与整批失败
  - 依赖：T10。交付：`services/gen_assets.py`模型边界与`tasks/gen_assets.py`候选处理、名称唯一冲突收敛、warning及原子marker；新增`backend/tests/task_system/test_c012_gen_assets_names.py`。不改正式模板，不把合法existing_id返回名称写入资产。
  - R：R2；PRD §3.1、§3.2、§6.2/6.4、§7；AC-07。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_gen_assets_names.py tests/task_system/test_c005_gen_assets.py tests/task_system/test_c005_invalid_existing_id.py`。逐项断言新增数量/精确内容、合法ID优先、两个warning可并存、同批首项、跨类型回滚、一次真实mock调用、marker不漂移；使用独立数据库连接核验 task 终态与 marker 同一提交，不仅断言 mock 返回。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 R2 生成候选去重与冲突失败。

- [ ] T12 验证名称竞争与取消/提交原子性
  - 依赖：T11。交付：独立`backend/tests/task_system/test_c012_asset_name_races.py`，覆盖两个正式API写入、手动与生成竞争、取消与marker提交；如失败只修T10/T11归属的根因，保留原失败且不改既有测试。
  - R：R2；PRD §3.1、§3.2、§6.1/6.4；AC-08/09。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_asset_name_races.py tests/task_system/test_c005_cancel_commit_race.py`；R `python -X utf8 .work/c012/acceptance.py names`。实际独立连接锁等待、一胜一409/生成同类型复用、异类型failed及精确DB行/marker必须有原始结果。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 资产名称并发与任务原子提交。

## B. 慢客户端保护与阶段回归

- [ ] T13 实现有界订阅及溢出通知
  - 依赖：T12。交付：`tasks/events.py`的256容量、溢出注销/owner通知，健康发布顺序及非阻塞不变；新增`backend/tests/task_system/test_c012_event_bus.py`。沿用既有EventBus，不加第二通道或事件表。
  - R：无；PRD §5任务、§6.1/6.4；AC-10。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_event_bus.py`；发布256/257、两个订阅、重复unsubscribe、无QueueFull泄漏与无业务回放逐项精确断言。
  - 计划测试层级：任务系统 mock。
  - 追溯行：C012 EventBus 有界订阅与慢连接释放。

- [ ] T14 实现 WS owner 超时关闭和子任务释放
  - 依赖：T13。交付：`api/tasks.py`发送10秒上限、溢出/发送异常关闭、同时完成事件处理、取消后await；新增`backend/tests/task_system/test_c012_ws_lifecycle.py`。不修改Task REST或事件JSON字段。
  - R：无；PRD §5任务、§6.1/6.4；AC-11。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_ws_lifecycle.py tests/task_system/test_c012_event_bus.py`；R `python -X utf8 .work/c012/acceptance.py ws`。受控ASGI慢send与真实网络WS分开记录，1013/日志、连接基线、零pending子任务、Task不误failed及健康订阅均验证。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 EventBus 有界订阅与慢连接释放。

- [ ] T15 验证慢连接关闭后的真实页面重建
  - 依赖：T14。交付：新增`frontend/src/features/tasks/taskSlowConsumerReconnect.test.tsx`，挂载生产TasksPage验证关闭→重连→列表/展开详情权威GET。现有协调器若有缺陷，只修该实际路径并补记录，不改旧测试。
  - R：无；PRD §5任务、§6.1、§9；AC-12。
  - 验收：R `npm.cmd --prefix frontend run test -- src/features/tasks/taskSlowConsumerReconnect.test.tsx`、`npm.cmd --prefix frontend run test -- src/features/tasks`、`npm.cmd --prefix frontend run build`；真实浏览器在T02受控后端经现有页面展开任务、观察连接异常/终态重建，记录该页面自己的详情GET与生成/取消POST零增加。
  - 计划测试层级：任务系统 mock。
  - 追溯行：C012 慢连接后的页面权威重建。

- [ ] T16 G1 前置修复阶段完整回归
  - 依赖：T15。交付：锁顺序/唯一约束/慢连接修复后的一次完整回归与阶段报告，确认没有未完成必需门槛再进入模板/真实M6。
  - R：R1–R12（含R5a，既有全套回归）；PRD §3、§6、§11 M6；AC-01/25。
  - 验收：新隔离仅迁移库，B `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、`python -m pytest -q`；R `npm.cmd --prefix frontend run test`、`npm.cmd --prefix frontend run build`、`git diff --check`。实际计数/exit/受测输入完整记录，旧C011全量不能替代本次。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 范围与阶段回归及交付一致性。

## C. 正式输入、部署与真实 M6

- [ ] T17 整理四份批准模板为正式部署输入
  - 依赖：T16及spec外部依赖中的批准正文。交付：`backend/deployment/templates/`四个固定key的UTF-8 txt与`backend/deployment/README.md`批准来源说明；恢复C007单一zimage原文，逐字核对，不根据长度或spec概述重新创作。
  - R：R11；PRD §7、§11 M6、§12.2；AC-13。
  - 验收：人工逐字对照原批准正文与四文件，记录换行/末尾换行及来源；R `git diff -- backend/alembic backend/workflows`确认此task无迁移/workflow变化；缺原文保持阻塞，不提交伪造文件。模板部署驱动验收尚未到本task。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 四份正式模板生产部署：全新生产等价库迁移后仅经设置 API 安装 `script2assets/script2shots/zimage/minimaxh3`，安装后及后端重启后四个 key 齐全、与批准输入逐字一致且无占位。

- [ ] T18 交付显式模板部署 CLI 与失败合同
  - 依赖：T17。交付：`backend/app/deploy_templates.py`、独立`backend/tests/api/test_c012_template_deployment.py`；复用正式设置API/httpx，install/verify、预检先于PATCH、部分提交说明与无retry按spec §5；完善部署README的实际命令。
  - R：R11；PRD §5设置、§7、§11 M6、§12.2；AC-14。
  - 验收：B `python -m pytest -q tests/api/test_c012_template_deployment.py`；输入缺失/未知/非法UTF8/占位/缺变量、HTTP失败、内容不一致、verify零PATCH全部精确计数与错误；另在独立后端/CLI进程间令第三个PATCH在进入写入前显式失败，独立DB回读前两项已提交、后两项保持基线，进程非零且没有后续PATCH；CLI无自动重启、无SQL写入、无lifespan seed。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四份正式模板生产部署：全新生产等价库迁移后仅经设置 API 安装 `script2assets/script2shots/zimage/minimaxh3`，安装后及后端重启后四个 key 齐全、与批准输入逐字一致且无占位。

- [ ] T19 交付真实输入与被动验收观测能力
  - 依赖：T18。交付：同一`.work/c012/acceptance.py`扩展spec §8的preflight --real/verify-inputs/observe --real；从spec §6.1逐字保存`backend/deployment/m6-script.txt`，记录三连跑追加句与两个动作片段目标。只新增观测能力，不接入生成重放器。
  - R：无；PRD §7、§10、§11 M6、§12；AC-02/16/18。
  - 验收：R `python -X utf8 .work/c012/acceptance.py verify-inputs`、`python -X utf8 .work/c012/acceptance.py selfcheck`；全文与spec逐字相等且不超实际SCRIPT_CHAR_LIMIT，observer无mutation、无DB种业务数据，来源/失败/清理自检通过。自检使用隔离端点，不冒充真实服务通过。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 验收装置生产通路与生命周期；C012 真实外部依赖与GPU资源归属。

- [ ] T20 现场验证真实外部依赖与资源归属
  - 依赖：T19；外部依赖实际满足。交付：本轮DB/DATA_DIR/配置、vLLM模型/sleep、Comfy队列/节点/绑定/LoRA和端口进程归属报告。只启动缺失且明确属于本轮的服务，不终止用户未知任务。
  - R：无；PRD §6.3、§8、§10、§12.1/12.3/12.4；AC-16。
  - 验收：R `python -X utf8 .work/c012/acceptance.py preflight --real`；实际health、object_info、queue、sleep(level1)/wake/is_sleeping和独立DB身份逐项记录；地址/模型/权重缺失保持spec外部依赖阻塞，不修改workflow或猜参数绕过。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 真实外部依赖与GPU资源归属。

- [ ] T21 全新生产等价库安装四模板并重启回读
  - 依赖：T20。交付：新M6库仅迁移、默认后端启动、部署与两次verify证据；记录原始4占位key基线与实际输入逐字比对，禁止复制旧库。该库此后专供真实示范链路。
  - R：R11；PRD §7、§11 M6、§12.2；AC-15。
  - 验收：B `python -m alembic upgrade head`；`python -m app.deploy_templates --base-url "$env:C012_BASE_URL" --input-dir deployment/templates --mode install`、同参数`--mode verify`；显式关闭并重启同库后端，再执行同一verify命令。两次集合GET全文一致、无占位、verify PATCH0；记录部分失败原始结果，不自动重装。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四份正式模板生产部署：全新生产等价库迁移后仅经设置 API 安装 `script2assets/script2shots/zimage/minimaxh3`，安装后及后端重启后四个 key 齐全、与批准输入逐字一致且无占位。

- [ ] T22 真实模型三次资产提取验收
  - 依赖：T21。交付：独立检验项目的三次任务、请求快照、集合A与三次DB/API回读；从正式浏览器录入同一原文、两次生成，再仅添加spec追加句后第三次生成。
  - R：R2；PRD §3.1、§3.2、§7、§11 M6；AC-17。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`被动记录；人工按spec §6.2逐步操作；断言第二次新增0/A逐字段相同、第三次仅陈宁character+1且A不变。真实模型失败、同义重命名或额外新增均如实失败，不直接SQL/修改模板/重新跑到绿。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 真模型三次资产提取。

- [ ] T23 示范集真实生成资产及参考图
  - 依赖：T22。交付：通过真实UI创建新示范项目/集、选定并记录风格、录入spec全文、完整资产提取；为两个动作段所需参考人物/场景出图并选择current，保存真实任务与媒体/快照证据。
  - R：R2、R4、R9、R11；PRD §2.1、§3.1/3.5、§6.2/6.3、§11 M6；AC-18（前半）、AC-16。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`；人工逐个正式生成按钮→task→PNG画廊/current→独立DB回读；至少人物、场景各一条真实Z-Image；两个链路分别消费script2assets/zimage正式正文，无后台补资产/上传假图代替生成。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback。

- [ ] T24 示范集真实生成整集分镜并预检创建两个片段
  - 依赖：T23。交付：真实script2shots任务、整集分镜、两个目标连续同场景片段的preview/request/slots/current参考证据；记录精确Shot/Asset/Clip ID，不硬编码历史ID。
  - R：R1、R3、R5、R5a、R6、R7、R8、R9；PRD §3.1/3.4、§7、§9、§11 M6；AC-18（中段）。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`；真实UI“生成分镜”→分镜内容核对→A/B分别preview/create；回读顺序、候选、1..9引用、duration与固定slot映射；两个动作段缺失不能直接种分镜或把场景混为一个。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback。

- [ ] T25 示范集两个真实片段视频与 take 回读
  - 依赖：T24。交付：A/B分别真实生成、可播放MP4、actual_duration、画廊/current和四模板消费全链证据；记录每个task的正式请求、payload/进程/GPU/文件通路。
  - R：R4、R6、R9、R10、R11；PRD §3.2/3.4/3.5、§6.2/6.3/6.4、§11 M6；AC-18（完成）、AC-16。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`；人工真实UI生成两次、打开take/切current、媒体播放；独立只读DB和正式REST逐字段一致、视频可解码且actual>0、当前take引用正确；结束queue空/sleeping/temp0。此task只证明链路与文件，视觉语义由T26判定。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback；C012 真实外部依赖与GPU资源归属。

- [ ] T26 人工核验两个片段的人物、场景及动作
  - 依赖：T25。交付：spec §6.2第5项逐项真假表、参考图/MP4链接、可定位时间点；每项记录实际观测，不使用“符合预期”替代内容。
  - R：无；PRD §11 M6；AC-19。
  - 验收：人工打开T25实际两段MP4与current参考图，分别检查身份无互换、宿舍/球馆、A入门/抬眼/继续吃饭、B指向/僵住，以及主体消失/额外肢体；缺项记失败，声音/字幕不要求；不新增像素或LLM自评自动测试。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 四模板生产消费：M6 一集剧本→资产→出图→分镜→两个片段视频全链路分别实际读取四份正式模板且无后台人工干预或 fallback。

## D. 级联、恢复与发布收口

- [ ] T27 验证 M6 九行全级联及所有明确子分支
  - 依赖：T26。交付：新增`backend/tests/task_system/test_c012_cascade.py`按spec §7完整九行分参数，复用生产服务/独立连接/实际媒体；在隔离受控浏览器逐格记录UI变化，不能破坏真实示范集。只补跨链路覆盖，不复制纯规则用例。
  - R：R2、R3、R4、R9、R12；PRD §3.2、§3.3、§6.4、§11 M6；AC-20。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_cascade.py`；R `python -X utf8 .work/c012/acceptance.py cascade`；精确行/ID/revision/current和文件bytes对照，编辑/换图/绑定增删/模板变更分支逐项记录；R3成功和模型失败都验证。实施后向既有九条§3.3追溯行追加实际节点。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 M6 全级联矩阵。

- [ ] T28 复核错误矩阵与外部输入边界
  - 依赖：T27。交付：spec §7错误格与当前既有用例节点对照、真实页面至少一条409/422及202立即failed的操作→观测记录。默认复用既有测试；若发现新的M6跨链路缺口，仅新增`backend/tests/task_system/test_c012_error_paths.py`并登记节点，不修改旧断言。
  - R：R1、R3、R5、R5a、R6、R8、R10、R11、R12；PRD §3、§5、§6.4、§7；AC-21。
  - 验收：B `python -m pytest -q tests/api/test_c006_generate_shots.py tests/api/test_c008_review_error_codes.py tests/api/test_c009_generate_video.py tests/task_system/test_c009_review_precheck_matrix.py`；新缺口有文件时另运行`python -m pytest -q tests/task_system/test_c012_error_paths.py`；人工错误体/POST次数/任务未claim/媒体错误路径检查。所有格必须有具体节点或人工证据。
  - 计划测试层级：任务系统 mock。
  - 追溯行：C012 M6 错误与敌意输入回归。

- [ ] T29 验证取消、心跳DB失败、崩溃恢复和单进程互斥
  - 依赖：T28。交付：新增`backend/tests/task_system/test_c012_recovery.py`，真实应用进程/DB/文件；queued/running取消与成功竞争、心跳错误/DB不可用时的真实限制、同库重启和第二实例拒绝。不加入心跳重试或伪造failed。
  - R：无；PRD §3.2、§6.1、§6.4、§11 M6；AC-22。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_recovery.py`；R `python -X utf8 .work/c012/acceptance.py recovery`。确定性进程屏障验证running→failed、queued保留/claim一次、副作用一次、advisory锁释放/拒绝、temp与连接退出；只使用本轮owned隔离进程。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 取消心跳失败与重启资源恢复。

- [ ] T30 验证生产 trash 启动和每日清理
  - 依赖：T29。交付：新增`backend/tests/task_system/test_c012_trash_cleanup.py`，真实文件/启动进程和每日调用路径；cutoff前/恰好/之后、trash外媒体、IO失败与shutdown。仅验证生产清理，发现越界/生命周期缺陷先报告定位，不顺手扩大清理范围。
  - R：无；PRD §6.4、§10、§11 M6；AC-24。
  - 验收：B `python -m pytest -q tests/task_system/test_c012_trash_cleanup.py`；R `python -X utf8 .work/c012/acceptance.py trash`；记录精确保留/删除文件与bytes，受控计时等待与真实启动证据分开，明确不是实际24小时长跑。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 trash 启动与定时清理。

- [ ] T31 真实视频生成期间的分镜编辑与 stale 验收
  - 依赖：T30及真实资源前置仍满足。交付：在示范集既有一个Clip发起新的真实生成，确认owned任务running后经真实UI改相关Shot文本；记录旧payload、新take、changed/stale和双维UI，保留原示范take。
  - R：R4；PRD §3.2、§3.3、§6.2、§11 M6；AC-23。
  - 验收：R `python -X utf8 .work/c012/acceptance.py observe --real`；人工UI生成→确认真实running→编辑→终态，独立DB/REST逐字段比较，旧payload不变、产物保存而不回写normal/fresh；B `python -m pytest -q tests/task_system/test_c009_clip_video_commit.py`补齐Clip/Asset漂移与无变化既有分支。GPU失败不自动重跑。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 真实生成中的修订竞态。

- [ ] T32 汇总发布操作说明与各层证据边界
  - 依赖：T31。交付：完善`backend/deployment/README.md`：安装/启动/四模板verify/显式恢复操作、示范媒体链接、环境与依赖实测结果、失败处理；完成报告按六段记录文件commit、spec追溯、取舍、自动验证、操作→观测、沉淀。明确未验证原生200%/动态reduced-motion与真模型随机性，不把受控证据升级为真实GPU。
  - R：无；PRD §10、§11 M6、§12；AC-01/25。
  - 验收：人工对照spec 25条AC及trace全部具体节点/原始日志；`git diff --check`；核验最终报告至少一条异常分支、示范库未清空、正式模板未被矩阵fixture覆盖；确认仅保留本轮需要资源，未知用户资源不动。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 范围与阶段回归及交付一致性。

- [ ] T33 G2 最终完整回归与最终输入归属
  - 依赖：T32。交付：最终实现、测试、依赖、装置与配置的完整回归证据；若与G1相应输入完全相同，按AGENTS逐套引用实际原始结果，后加测试/部署驱动对应套件必须更新。真实M6专项失败不能用G2覆盖。
  - R：R1–R12（含R5a，回归覆盖）；PRD §3、§6、§7、§11 M6；AC-25。
  - 验收：在新隔离回归库B `python -m alembic upgrade head`、`python -m alembic current`、`python -m alembic check`、`python -m pytest -q`；R `npm.cmd --prefix frontend run test`、`npm.cmd --prefix frontend run build`、`git diff --check`；原始exit全部0，记录实际数量与受测commit，不固定348/174，媒体示范库不参与pytest。
  - 计划测试层级：跨进程/资源生命周期。
  - 追溯行：C012 范围与阶段回归及交付一致性。

- [ ] `NOTES.md` 已更新（无可更新内容则在完成报告中写「无」）
  - 标识：T34；依赖：T33。仅记录本轮实际环境/依赖/失败根因和已验证结果，不复制旧库状态为当前事实。
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
  - 标识：T36；依赖：T35。仅在本表前置全部完成、25条AC都有真假证据、外部依赖门槛解除后收口；保留失败记录/限制，不顺手archive/push或纳入AGENTS用户改动。
  - R：无；PRD §0、§11 M6；AC-01/25。
  - 验收：R `git status --short`、`git diff --check`、`git show --stat HEAD`、`git ls-tree -r --name-only HEAD openspec/changes/c012`；逐项核对PRD/spec/tasks/trace与受测commit，确保非文档输入变化都有相关新证据，完成报告明确提交状态。
  - 计划测试层级：不新增自动测试。
  - 追溯行：C012 范围与阶段回归及交付一致性。
