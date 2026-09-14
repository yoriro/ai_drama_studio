# C012 Astra 最终复审：PASS

> 归档说明（2026-09-14）：以下保留 2026-09-13 审查结论与过程。文中“未 archive、push”描述当时状态；本报告现已随 C012 归档。`.work/c012/` 原始日志、诊断与媒体保留在本地，未随报告批量上传。

最终结论时间：2026-09-13。审查范围为 `c0830c34c05bb53b3111d39eb52b05bebd11a8d3..bf7e0b2fee2aae6a37c1aedc0d615fdb437b43eb`。本轮已完成修复协调、独立完整 pytest、风险定向诊断、正式模板部署/消费核对、参考图及视频帧复核、最终文档与提交一致性检查。55 个 task checkbox 已完成，未勾选项 0。

本结论覆盖下方过程记录中的所有中间“待验收/阻塞”状态；历史失败和原始文件仍保留，不追认为当时通过。Astra 没有修改仓库实现、迁移或正式测试；仅写 `.work/c012/probe-*.py`、诊断输出和本报告。Luna 完成实现/模板/文档提交，未 archive、push 或删除证据。最终 tracked 工作树只剩用户原有 `AGENTS.md` 与 `docs/PRD-v1.2.md` 改动，未混入收尾提交。

## 四类结论

- **BLOCK：无未解决项。** B1–B7 已分别由修复、对应正式回归、专项原始证据及本轮独立诊断关闭，不能仅以 414 测试全绿解释通过。
- **SPEC-DEFECT：无未解决项。** 最终事实修正提交 `bf7e0b2` 已消除当前 T22 状态与旧失败记录混写，T26/AC-19 的既有用户裁决保持；AC-26 当前部署与消费独立完成。没有新增产品范围或在代码侧绕开规范。
- **DEFER：有明确保留限制，见下节。** 不构成本轮现行合同的发布阻塞，不宣称已经解决。
- **PASS：C012 可以按当前范围收口。** 当前 MiniMax 部署输入提交 `4f340cd`，任务/追溯收口 `b1018c3`，最终文档纠正 `bf7e0b2`。完成报告为 `completion.md`。

## 仍需保留的限制与后续触发条件

1. 模型输出和成片存在随机性，当前两个指定片段通过不证明任意剧本、seed、室外/旁白/多人对白的稳定性。模板仍有 `Inside` 等局部通用性限制；用户已允许局部通用性退化。实际制作进入这些输入时，应按新需求定向验证模板，不能自动重试或宣称泛化验收已完成。
2. 当前球馆 take7 没有显式剪回第三镜的芳嘉蔓转头调侃；宿舍 take8 门外出现类似球场的环境细节，非核心服装文字含 `sleeveless`。两段核心动作、主要人物/服装区分和主体所在地点满足 §6.2 第5项。若后续要求逐镜剪辑精确复刻或更严格环境连续性，应另立质量门槛；本次不将它们伪装成完美成片。
3. T22 task3 原始模型响应缺失，不能确定该任务未新增陈宁的具体根因；task4 完整捕获只证明 task4 模型漏提。按用户允许背景配角省略的新条件，T22 已完成；本批没有验证真实模型新增人物能力。后续需要归因时使用有明确任务关联的单次完整采集。
4. 单次数据库心跳异常仍执行既有失败/取消策略，无容错重试；项目/风格/模板行锁可能使入队与设置编辑等待。只有新增容错产品需求或出现可量化的等待问题时再评估，不能在本 change 擅自加入重试或锁框架。
5. 原生桌面 200% 与动态 reduced-motion 的既有未验证边界没有由本轮补齐；音频属于 v1 范围外。受控每日清理只验证生产定时分支，不声称实际等待24小时。以上均未包装为通过证据。

## 最终受测输入与实际结果

独立完整回归的受测提交为 `3f2913a75bce70c030e86f124d82bd75613f80aa`。最终 HEAD 与该提交之间，`backend/app`、正式后端测试、前端和依赖没有变化；后续模板、文档及临时浏览器装置变化由各自的新专项证据覆盖，不机械重跑 CPU 全量。

```text
根目录：python -X utf8 .work/c012/probe-review-suite.py
隔离库：ai_drama_studio_c012_review_20260913_170310
python -m alembic upgrade head                 exit=0
python -m alembic current                      c012_asset_name_unique (head), exit=0
python -m alembic check                        No new upgrade operations detected., exit=0
python -m pytest -q                            414 passed in 408.88s (0:06:48), exit=0
```

完整 stdout/stderr/退出码及环境身份在 `review-20260913_170310/`。Luna T49 的独立历史执行是 `414 passed in 206.68s`，与 Astra 此次执行分开归属。前端复用 T33 受测 `8886e9f` 的 `npm --prefix frontend run test`（35 files / 175 tests）及 `npm --prefix frontend run build`（68 modules），原始 `T33-frontend-{test,build}.*` 均 exit0；该提交到最终 HEAD 前端差异为空。最后 `git diff --check` exit0；LF/CRLF 提示不作为失败，未吞掉错误。

## 26 条 AC 的最终覆盖映射

下表正式后端测试均以 `backend/tests/` 为前缀。精确 nodeid/参数列表在 `openspec/TRACEABILITY.md` 与 `review-final-test-id-coverage.json`，本次核对46个新增后端测试函数均有准确名字归属，缺项0。原完整 diff/初审测试阅读记录见 `review-20260911.md`；下表给出最终修复后的结论。高风险 AC 均有实际定向诊断，单个探针只证明其明确分支，完整矩阵由所列正式测试/真实专项共同覆盖。

| AC | 正式测试或明确替代验收 | 独立诊断/最终结论 |
|---|---|---|
| 01 | 完整diff、55项tasks、TRACE、最终三次文档提交 | PASS；范围/提交/回填一致，只有用户AGENTS/PRD留在工作树 |
| 02 | T02A selfcheck的真实成功/失败/启动失败及T40/T41装置消费 | PASS；原子进程探针stderr+exit0、真实exit17、FileNotFoundError不启动后继；最终t41i释放owned资源 |
| 03 | `task_system/test_c012_lock_order.py::test_c012_lock_order[L1]` 两持锁方向 | PASS；`probe-final-boundaries.py`真实pg等待、前done/后queued、恰1 current正式视频 |
| 04 | 同文件L2–L5；`test_c012_lock_edit_pairs.py::test_c012_lock_edit_pairs_are_serial_equivalent`；`test_c012_shot_binding_race.py`两个完整用例 | PASS；独立双连接相同绑定竞争winner/contender/final revision均2；真实操作对双向等待与显式业务断言补齐 |
| 05 | `task_system/test_c012_asset_name_migration.py::test_c012_asset_name_migration_precheck_constraint_and_down_up` | PASS；完整迁移旧库矩阵随414复跑，独立新库SQLSTATE23505/uq_assets_project_name |
| 06 | `api/test_c012_asset_names.py::test_c012_asset_name_contract_for_create_and_patch` | PASS；独立空白/NUL/2001-byte与既有孤立surrogate API探针结构化422、无副作用 |
| 07 | `test_c012_gen_assets_names.py`候选去重/跨类型/边界；`test_c012_gen_assets_reuse.py::test_c012_gen_assets_reuse_skips_name_validation_for_existing_ids` | PASS；合法owned ID+不采用的空/NUL/长名称复用，真实worker原行不变/marker9/chat1；新增候选仍受校验 |
| 08 | `test_c012_asset_name_races.py::test_c012_api_name_races_have_one_winner_and_exact_conflict`、`test_c012_manual_generation_races_converge_by_unique_name` | PASS；独立真实API并发[201,409]，message=资产名称已存在，数据库唯一胜者 |
| 09 | `test_c012_asset_name_races.py::test_c012_gen_assets_cancel_and_done_keep_marker_atomic` | PASS；提交竞态正式回归；独立fresh夹具跨类型整批failed，原行/marker保留，chat1 |
| 10 | `test_c012_event_bus.py::test_c012_event_bus_bounds_slow_subscriber_and_preserves_healthy_order` | PASS；独立qsize256/第257触发overflow、subscriber0；健康序列257由正式精确断言覆盖 |
| 11 | `test_c012_ws_lifecycle.py`及`test_c012_ws_send_overflow.py`三个用例 | PASS；独立在途send+overflow实际0.06s以1013/subscription_overflow关闭，生产10秒不改；纯timeout及子任务释放独立回归 |
| 12 | 前端`taskSlowConsumerReconnect.test.tsx`；T41真实TasksPage/独立库 | PASS；生产协调器探针精确failed全字段；t41i真实1013/send_timeout后socket1391→list1395→detail1400，DOM/DB done，mutation0 |
| 13 | 四批准模板来源、当前6570正文及授权修订的逐字输入比较；不新增语义自动测试 | PASS；当前候选不是旧批准源冒名，三个其他模板不变；模板文字语义用人工逐项核对 |
| 14 | `api/test_c012_template_deployment.py::test_cli_rejects_invalid_input_before_any_http`、`test_cross_process_failure_leaves_only_prior_patches_committed`及其余七个完整用例 | PASS；独立空目录HTTP调用0且失败；真实只读CLI检测旧mismatch非零并在当前一致时0 |
| 15 | T21新库安装前占位/正式API安装/同库重启；当前T26C-formal-current各原始日志 | PASS；当前四key/API+独立DB全文相等，无占位；Astra另行正式CLI只读verify exit0 |
| 16 | T20/T21/历次正式M6 preflight、当前postobserve的现场身份/外部边界 | PASS；真实DB/DATA_DIR/Qwen/binding/LoRA核验，当前active0/Comfy0/0/vLLM睡眠/tmp无本批残留；只读探针不冒称重新运行GPU互斥 |
| 17 | T22 task1–3快照/集合、`T22-reassessment.md`、task4单次完整被动采集 | PASS按新门槛；独立回读修订2/2/3、三task done、原集合不变/新增0；保留task3 raw缺失，不外推task4根因 |
| 18 | T23–T25四类型正式生成/UI/媒体/独立DB；当前task17/18与take7/8 | PASS；`probe-final-consumption.py`真实REST+独立DB快照+完整解码：243帧10.125s、192帧8s，新take非current，旧4/3保留 |
| 19 | 用户原T26裁决；当前完整播放报告及逐时刻帧/真实参考图核对；不新增自动视觉测试 | PASS；球馆2.75s指向、3.5s后凝住；宿舍1.5s入门、3.5s抬眼、5.25s低头、7.9s饭入口；局部质量限制如上 |
| 20 | `test_c012_cascade.py::test_c012_cascade_matrix`及补充；`test_c012_template_cascade.py::test_c012_template_changes_rebuild_exact_r4_cache_once`和`test_c012_template_edits_freeze_all_inflight_payloads_and_do_not_retrofit_downstream`；T44真实进程矩阵 | PASS；独立资产编辑级联，T44八个正式任务/图片1→4/视频0→3，miss→hit→mismatch且hit chat_delta为空；不是只断言hash非空 |
| 21 | T28逐格错误矩阵指定的C006/C008/C009完整nodeid；C012名称/模型边界测试 | PASS；独立NUL/surrogate/长名称/撞名/模型非法候选等探针；结构化错误、409/422及立即failed边界无新漂移 |
| 22 | `test_c012_recovery.py`、`test_task_queue.py::test_restart_fails_running_and_continues_queued`、`test_c012_worker_recovery.py`四用例；T46真进程 | PASS；独立会话恢复/advisory诊断；T46崩溃恢复queued恰一次产物、第二进程exit3、心跳故障外部取消/handler0、恢复后server restarted且无retry |
| 23 | T31 running→真实UI编辑→final原始JSON/媒体；`test_c009_clip_video_commit.py`修订分支 | PASS；独立旧payload相等，task_started<edit<finished，Shot changed/Clip stale/new take非current；本轮新完成消费不倒写旧时刻状态 |
| 24 | `test_c012_trash_cleanup.py`三个完整用例及T30独立启动 | PASS；独立真实文件过期删、recent/outside bytes保留；cutoff/IO/关闭分支由正式回归覆盖 |
| 25 | T49执行者全量、Astra本次414完整回归、T33前端复用、最终T50/T34–36文档 | PASS；实际受测输入、原始命令/exit/复用边界明确，NOTES已更新，DECISIONS仅候选，最终提交一致 |
| 26 | 当前6570正文的两次raw prompt诊断、正式安装/重启、task17/18当前真实消费；不新增语义自动测试 | PASS；Clip2实际request逐字相等；Clip1仅既有T31说明尾注10字差异，未改变业务动作/对白且输出不带标记，按明确裁决记录exact=false；三/四镜prompt与核心动作、对白、引用满足，视频按AC19验收 |

AC13/19/26不用自动语义/审美测试，因为字符串存在性不能判定原文动作、参考身份和画面表现；替代方式为逐镜原文比对、原始响应保留、完整播放、时间点与参考图核对。没有因为追溯表缺行而跳过。所有高风险标记至少有一项独立定向结果，覆盖及不能证明的范围如表所列。

## 最后新增独立消费探针的原始输出摘要

实际命令 `python -X utf8 .work/c012/probe-final-consumption.py`，exit0；完整输出结构为 `probe-final-consumption.json`，不是自动视觉通过判定。读取live REST，比较已经保存的独立DB快照，并逐帧完整解码当前媒体，没有推理/生成调用。

```text
clip2 task17 take7: done/1.0/null; request_exact=true; template/model/temperature_exact=true
cached_prompt=null; built_equals_persisted_cache=true; current_ids=[4]; new_take_current=false
h264; decoded_frames=243; duration=api_duration=db_duration=10.125; passed=true
clip1 task18 take8: done/1.0/null; request_exact=false; only_prior_T31_observation_marker_diff=true
template/model/temperature_exact=true; marker_not_in_output=true; cached_prompt=null
built_equals_persisted_cache=true; current_ids=[3]; new_take_current=false
h264; decoded_frames=192; duration=api_duration=db_duration=8.0; passed=true
```

其余本轮独立探针的真实命令、原始输出和证据目录完整保留在下方过程记录。B5最终结构化证据**只引用 `probe-b5-browser-evidence.json` 的t41i批次**；`T41-browser-final-acceptance-3-20260913.json`是t41g旧不完整批，不计入最终通过。

## 必查清单最终结论

- 范围围栏、versioning、continuity：无新增候选分镜/增删拆合排序/资产别名合并/generation_runs/音频/模板版本机制。C012新增迁移只处理资产名唯一约束；工作流未改。枚举历史预留不等于运行时使用。
- 重试与错误：无任务自动重试、静默fallback或吞异常换默认；原子冲突插入是数据库竞争处理，不是任务重跑。错误体与409/422按照同类既有合同，任务失败保留完整原因。
- 快照与事务：实际锁后回读、单赢家、旧changed/stale不被旧任务清除、文件补偿和重启副作用已由对应测试/探针/真实任务证明。
- 外部输入：合法owned ID的无用名称与新增名称边界分开；敌意整数、字符串、媒体路径和schema边界沿既有测试及本轮探针核验，不把HTTP200或task done当语义质量通过。
- 测试强度/追溯：打开了新增用例的断言。原B6仅存在性/hash非空的覆盖不足由精确前后值/次数/内容和真实装置补齐；C011基线以来无既有后端测试M/D。新增测试至少归一追溯行。
- 验收装置：受控测试在外部模型边界替换，生产事件、存储、队列、handler及进程生命周期仍实际执行。B5 ASGI背压不宣称TCP拥塞；T46真进程补足mock证明边界；正式M6四类生成使用真实外部服务。没有用隔离假业务通路替代正式验收。
- 完成证据：六段完成报告已修正B5串批路径和B2/B3红绿证据归属，包含真实慢关闭异常路径；55/55、TRACE、当前模板、commit与运行证据一致。DECISIONS候选已列，未擅自采纳为既有决定。

---

# 审查过程记录（以下“当前/阻塞”仅指记录当时，不覆盖上述最终结论）

本记录不是发布通过。完整基线为 `c0830c34c05bb53b3111d39eb52b05bebd11a8d3`，前次独立审查为 `21c04f3aef5ce2159c0a67a35d0b2faace8051df`，本次 CPU 实际受测提交为 `3f2913a75bce70c030e86f124d82bd75613f80aa`。前次完整 diff / 26 条 AC 对照见 `review-20260911.md`；本次核对后续修复 diff、正式测试断言、原始输出及新增独立探针。Astra 未修改生产实现、迁移或正式测试，仅新增 `.work/c012/probe-*.py` 和审查证据。

## 当前问题状态

- B1 合法 existing_id 名称过度拒绝：修复与独立探针通过。正式回归 `test_c012_gen_assets_reuse.py` 保留新增候选边界，合法 owned ID 不采用的名称不影响复用。
- B2 绑定锁后 no-op：修复与独立双连接探针通过；等待者 revision 保持 2，未再次级联。独立正式回归 `test_c012_shot_binding_race.py` 包含相同和不同集合。
- B3 阻塞发送期间 overflow：修复与独立探针通过；生产 10 秒常量未缩短，实际 0.06 秒以 `subscription_overflow` / 1013 关闭。独立正式回归 `test_c012_ws_send_overflow.py` 同时覆盖溢出、纯超时、断开/取消的子任务释放。
- B4 最终模板与正式消费：待当前 T26C/D、T47/T50 新证据，不以旧 T26 的产品通过裁决替代部署与消费。
- B5 慢连接页面：当前 `6c809e1` 的 t41i 批次通过；旧 T41 详情加载中、提前关闭等证据缺口及修复过程在下文保留。当前已同时证明先展开running、实际慢关闭、自动socket-first和真实DOM终态，不仅是HTTP200。
- B6 矩阵/恢复：修复证据已核对。`test_c012_lock_edit_pairs.py` 逐操作对双向、实际 pg 等待、串行等价及显式业务语义；`test_c012_template_cascade.py` 与 T44 生产进程 HTTP/handler/DB/文件缓存 miss→hit→mismatch；`test_c012_worker_recovery.py` 与 T46 真进程退出/重启、queued 恰一次产物、心跳 DB 故障取消外部请求及恢复。受控 stub 位于外部客户端边界，不替代生产业务提交。模型/视频质量不能从这些受控结果推导。
- B7 准确测试 ID：本次 AST 核对 C012 新增的 46 个后端 test 函数均在 TRACE 有准确函数名，缺项 0。C011 基线以来没有修改既有后端测试文件。原始列表 `review-final-test-id-coverage.json`。

## 本次实际命令与结果

根目录命令：`python -X utf8 .work/c012/probe-review-suite.py`。独立新数据库 `ai_drama_studio_c012_review_20260913_170310`，独立 DATA_DIR；普通测试外部地址为关闭的本地端口，没有调用真实 GPU。子命令在 backend 执行：

```text
python -m alembic upgrade head: exit=0
python -m alembic current: c012_asset_name_unique (head), exit=0
python -m alembic check: No new upgrade operations detected., exit=0
python -m pytest -q: 414 passed in 408.88s (0:06:48), exit=0
```

完整 stdout/stderr/退出码/身份在 `review-20260913_170310/`。`git diff --check` 本次 exit 0。LF/CRLF 提示如实保留，不当作测试失败。

前端复用 T33 `8886e9f`：`npm --prefix frontend run test` 为 35 files / 175 tests，build 为 68 modules，原始两份 exit-code 均为 0。已核对该提交至本次受测 HEAD 的 frontend diff 为空；其原始日志为 `T33-frontend-test.stdout.log`、`T33-frontend-build.stdout.log`。不以全量复用豁免 B5 真实页面证据。

## 本次定向探针原始观测

`python -X utf8 .work/c012/probe-review-races.py`，exit 0；原始 `probe-results-20260913_170347/results.json`：

```text
AC04 blocked_connections=1 winner_revision=2 contender_revision=2 final_revision=2 passed=true
AC07 valid existing_id: blank / NUL / 2001-byte names all passed=true
AC10 qsize=256 overflow=true subscribers=0 passed=true
Task websocket closing code=1013 reason=subscription_overflow
AC11 closed_immediately=true seconds_until_close=0.06 codes=[1013] passed=true
```

`python -X utf8 .work/c012/probe-final-boundaries.py`，exit 0；原始 `final-boundaries-20260913_170728/results.json`。该一次性装置使用生产服务/队列/真实独立 PostgreSQL，模型在外部边界替换；未修改原审查脚本或正式测试：

```text
AC03: prior task done / next task queued / exactly one current video / real pg lock wait
AC05: SQLSTATE 23505, constraint uq_assets_project_name
AC06/21: blank, NUL, 2001-byte input -> exact structured 422
AC08: concurrent manual create -> [201,409], message=资产名称已存在
AC07: owned existing_id + blank name -> done, original row unchanged, marker=9, chat=1
AC09: fresh separate fixture cross-type conflict -> failed, original asset only, marker=null, chat=1
AC20: asset edit -> related shots revision=2/status=changed, clip stale
AC22: independent sessions running->failed/server restarted; queued retained; advisory acquire/refuse/release
AC24: expired removed, recent/outside bytes unchanged
all rows passed=true
```

`python -X utf8 .work/c012/probe-final-reconnect.py`，exit 0；同名前缀 stdout/stderr/exit-code 原始文件。此脚本仅改变原审查脚本输出文件名前缀，保留断言，使用生产 TS 观察协调器、受控 socket/REST；不是浏览器证据：

```text
AC12 disconnected=reconnecting
beforeOpen=[socket,GET list,GET detail914,socket]
calls=[socket,GET list,GET detail914,socket,GET list,GET detail914]
list/detail exact failed, progress=0.61, full error, finished_at; passed=true
```

AC14/15/16/17/18/21/23/26 的既有独立诊断及本次现场补充须与原始记录合并评估，禁止把一个子分支探针当完整 AC。此前真实 task3 模型响应缺失仍不能外推根因；T22/AC17 配角允许省略、T26/AC19 替代视频通过按用户裁决保留。

`python -X utf8 .work/c012/probe-final-deployment.py` 本次 exit0：空输入目录经生产部署函数实际拒绝，HTTP client 调用0；随后生产 CLI 对当前运行后端只读 verify 输出 `verified=script2assets,script2shots,zimage,minimaxh3`、exit0。原始 `probe-final-deployment.json` 和 `probe-final-deployment-verify.*`。该探针只证明此刻四正文相同与失败前置，没有替代同库重启和新 take。Luna `T26C-formal-readback-after-restart-20260913.stdout.log` 记录四 key exact_input 全 true / placeholder 全 false，minimaxh3 12221 bytes；新候选部署已经通过，B4 剩余是正式消费。

## 证据强度与边界

T44 原始独立产物为资产图 1→4、视频 0→3，八个实际 HTTP 任务均 API/DB done。image/video hit 的 chat_delta 均为空；六次 chat 按 schema 精确为 zimage=2、minimaxh3=2、script2assets=1、script2shots=1。修改模板后的新 hash 与旧值不同，新快照无缓存；模板/风格精确比对与在途快照不变由正式回归补齐。单纯 `input_hash` 非空断言不能取代这些证据。

T46 原始 PID 33784 被终止，第二竞争后端 PID18848 exit3；重启 PID35728 后 task16 failed/server restarted，原 queued task17 done/progress1，恰一行 generated 资产。外部请求 #1 随崩溃断开、#2 唯一成功。心跳数据库只读故障导致 #3 请求取消，task18 保持未能持久化的 running，asset 数仍1、handler 0；恢复数据库并再启动 PID22136 后 task18 failed/server restarted，chat 总数仍3，没有重新生成。最后 owned processes stopped、runtime directory removed。故意终止产生 exit1 是该故障触发的原始结果，不伪装为正常 shutdown exit0。

部分正式测试以 mock 检验监督分支，T46 负责真实进程与业务副作用；两者结合验收。并发矩阵不是只验证字符串标签：同时核对实际 pg 阻塞、两种顺序、完整状态和错误结果。新增测试无 skip/删改既有测试。未发现因当前五文件生产修复新增的范围外能力、版本机制、自动重试、静默 fallback 或错误体漂移。

本文件待 Luna 正式视频、B5 补验和最终文档提交完成后更新最终结论。原生 200%/动态 reduced-motion、音频和更广泛模板通用性不从本 change 的现有证据扩张宣称。

## 17:25 后正式消费反馈

T26D Clip2 经正式页面一次提交 task16，done/progress1、新 take6 可解码10.125秒且非 current；原 take4 current 未改。但新 built_prompt 漏掉 Shot1 对出场方向的明确指向、场景定义含 `两侧 spectator stands`、Shot4 追加绝对静止抵消嘴唇微颤；新视频也未观察到明确指向。因此 B4/AC26 仍未通过，Clip1 未提交。原始 `T26D-clip2-20260913/review.md`、`T26D-clip2-readback-20260913.json` 与媒体/提示词日志保留。

Astra 独立逐项比较已通过诊断 `T26C-clip2-20260913_165146/request.json` 与 task16：实际 user message 逐字相等，model/temperature/shots/references/style/user_note/schema/requested_duration 相等，cached_prompt 均 null。没有发现输入或部署漂移。诊断目录的旧 `input-snapshot.template_content/rendered_prompt` 不代表实际请求，须使用该目录 request.json/template.txt，不能据旧副本误报正式模板未生效。比较保存在 `probe-final-formal-input-comparison.json`。没有生产 raw vLLM HTTP 响应，不伪造该项；现有证据证明持久化 built_prompt 自身已缺项，不能将诊断通过当作正式输出通过。

已派发先补独立 B5，之后由 Luna 提交针对三项失败的具体模板最小补丁供 Astra 裁定，不执行同输入循环重跑、不改既有视频/current、不改实现/测试/参数/断言。失败不自动豁免。

## B5 补证仍有触发顺序缺口

Luna 提交 `8065879` 的 T41 最新批次，实际 DOM 的 done/100%/完整详情已在确认 marker 前观察；独立库为 `ai_drama_studio_c012_t41g_20260913_181000`。但不能据此关闭 B5：`T41-browser-final-3-20260913.stdout.log:218` 已发生 `code=1013 reason=send_timeout`，`:260` 才打印 browser-ready。ASGI 闸门从首次 WS 事件就拦截，因此在人工展开目标之前已经耗尽唯一一次慢关闭。`acceptance.py:3162` 的 `websocket_close_code=1013` 是写入的期望常量，JSON 的 `overflow_logs=[]`，而非独立记录出的关闭码；后续多次列表/详情 GET 也可能来自筛选和任务事件。

这属于原 B5 验收触发/归因不足，未发现新的生产前端缺陷。已要求保留8065879和全部原始失败，下一提交恢复未完成；仅浏览器装置在既有release marker后先arm闸门再释放模型，并记录实际ASGI关闭/连接/请求顺序；不能把首条连接、任意一次send取消与最终DOM拼成同一故障链。扩大人工窗口仅改变本隔离进程客户端timeout与装置deadline，生产默认120秒/WS10秒/队列256未改；stub自身旧180秒等待未修改，报告不能声称所有等待都已900秒。

## B5 当前关闭：修正后的真实因果链已通过

最新独立库 `ai_drama_studio_c012_t41i_20260913_181412`、后端65223/前端5175/stub50603 的批次已完成。Astra 逐字保留当前完整 JSON 为 `probe-b5-browser-evidence.json` 并独立抽取：

```text
pre-release target detail sequence=622, HTTP200 body status=running/progress=0
gate_arm_sequence=623
gated_connection_sequence=620
actual forwarded websocket.close code=1013 sequence=1339 (same connection620)
Task websocket closing code=1013 reason=send_timeout
new socket sequence=1391
first list GET after reconnect=1395; first target detail GET=1400
last target detail response status=done
```

Luna 在实际 DOM 的目标行及展开详情显示 done/100%/error为空后才创建 confirmation marker，独立 DB task41 为 done/progress1/error null/finished_at=2026-09-13T10:16:33.157617+00:00，owned 后端/stub/目录/连接均清理。生成 POST127 与装置127个受控任务一一对应，浏览器无重放，cancel POST0。当前健康页面亦显示连接成功，与同批 API 一致。

该批实际触发的是生产10秒 `send_timeout`，`overflow_logs=[]` 如实保留。AC12/T41要求真实慢关闭后的页面重建，并不限定必须overflow；强制overflow的中间装置断言误把B3条件带入B5，已纠正且中间失败保留，不追认为通过。B3/AC11关于“已发生overflow不能误等timeout”的独立测试/探针没有放宽。现有B5证据来自实际forwarded close及序列，已经移除硬编码1013和全局第二socket/第二GET的错误归因。B5可关闭；待修正文档提交编号回填，B4依然阻塞正式模板消费。

已提交为 `6c809e1`。独立回读 `T41-browser-arm-manual-20260913_181412.md` 第7/8步确认真实DOM finished time `2026/9/13 GMT+8 18:16:33` 与DB一致，confirmation晚于DOM；已明确当前原因send_timeout。该提交后端生产和正式测试无改动，CPU414回归不失效。

## 当前模板修订诊断

从12221-byte现用候选定向减少重复规则、原名加引号与英文分句、逐句保留动作、去掉对白必须在动作之前的策略，并以无关miniature示范多动作和身体静止/局部运动共存。五变量、schema、模型参数和冻结输入不变。此为用户授权持续定向修订，不冒充用户逐字批准了后续候选；10756-byte批准源仍是历史来源，不能据旧T47文字把后续已授权变更误判为新产品冲突。

新 Clip1 诊断 `T26C-clip1-20260913_183540` 的实际 request/response/prompt/三镜输入已由Astra逐字读取：核心入门、抬眼回应、继续吃饭、两条完整对白、三镜顺序/时间/Subject-Picture/英文/空对白均满足。Luna初判的两条措辞偏离保留，但不作产品失败：`scene maintains stillness ... quiet, composed expression` 指整体静态场景及平静神情，正文明确嘴部微动/咀嚼/夹米，没有取消动作；summary的 `chewing slowly` 是输入“继续吃饭，嘴部微动”的表演概括，不是新增重要事件。模板禁止补总结句是提示策略，不是新增AC；同此前对白排序裁决，不将策略遵循升级为独立产品门槛。已允许同一候选一次Clip2诊断，未重跑Clip1或宣称视频通过。

## 19:30 当前6570-byte候选：诊断与部署已经核验

本轮压缩规则并保留完整无关格式示例的6570-byte/60-line正文，在 `T26C-clip1-20260913_191926` 与 `T26C-clip2-20260913_192116` 两次单次诊断均满足现行核心合同。Astra逐字读两份raw prompt，并独立比较两个template.txt与磁盘正文byte相等，response中的prompt与提取prompt逐字相等。两份完整对白/核心动作/镜头顺序/Subject-Picture映射/英文描述与空对白均通过。宿舍sleeveless相对输入短袖有非核心服装措辞偏离，保留此限制，并要求正式视频对真实参考图检查身份/主要服装；不宣称所有描述逐字无偏。

Luna经正式CLI完成该6570正文安装、安装后verify、同库安全重启后verify/API+独立asyncpg全文回读，`T26C-formal-current-readback-after-restart-20260913.stdout.log` 四key exact_input全部true、placeholder全部false，DB=`ai_drama_studio_c012_m6_20260910`、DATA_DIR=`.work/c012/t21-m6-data`，minimaxh3=6570 bytes。Astra随后从backend独立运行正式CLI `python -m app.deploy_templates --base-url http://127.0.0.1:8000 --input-dir deployment/templates --mode verify`，原始输出 `verified=script2assets,script2shots,zimage,minimaxh3`、exit0，证据 `probe-6570-deployment-verify.*`。旧12221/10756的回读仅为历史，不能替代本段当前正文。正式平台新视频消费仍在执行，B4仍待其结果，未提前判定通过。

## Task17球馆消费裁决：按现行视频合同检查，不新增剪辑门槛

正式UI唯一提交的task17 done/progress1/error null，新take7 10.125秒/H.264/960x544且非current，take4仍current。Astra独立解析 `T26D-clip2-formal-readback-current-20260913.json`：真实rendered_prompt与192116诊断request.messages[0].content原始字符串相等（两者CRLF计数0），model/temperature相同，cached_prompt=null，当前6570模板与快照相等。四镜built_prompt保留指向、静止、转头调侃和嘴唇轻颤，兩条完整中文对白在对应镜头，非对白描述英文。不是诊断文本替代正式prompt。

Astra查看take7的0/2.75/3.5/5.25/8/10秒六帧及实际三张参考图：2.75秒芳嘉蔓向后方球场明确伸臂指向，3.5秒后乔彦茜睁眼张口凝住；两人物脸型/发型可区分、粉色裙+米色开衫与白T恤无互换，羽毛球馆可辨。Luna完整播放报告未见第三镜切回芳嘉蔓转头调侃，此事实保留为成片质量限制。

该限制不能自行升级为AC-19失败：AC-19明确引用§6.2第5项，球馆要求指向球员与乔彦茜静止反应及身份/场景/异常检查；没有要求成片逐镜精确重现四次剪辑，也不要求配音/精确口型。AC-26逐镜保真约束输出prompt，视频按AC-19记录。已要求Luna依原项补完整播放逐项检查表，若原定核心项通过则继续唯一一次Clip1；不重生成Clip2，不隐瞒镜头缺失，不豁免原动作。最终PASS仍待宿舍消费及文档收口。
