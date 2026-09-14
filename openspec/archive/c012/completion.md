# C012 完成报告

> 归档说明（2026-09-14）：以下保留执行者完成报告。文中 `openspec/changes/c012/` 为原执行路径，现迁至 `openspec/archive/c012/`；最终独立审查结论见同目录 `review.md`。`.work/c012/` 原始证据与媒体保留在本地，未随报告批量上传。

## 1. 改动文件清单与 commit hash

功能/部署输入提交为 `4f340cde7745dfbbcf7d8c0816875c64e617b24c`（`C012 T26C T26D T47 current formal acceptance`），包含：

- `backend/deployment/templates/minimaxh3.txt`
- `backend/deployment/README.md`
- `openspec/changes/c012/spec.md`
- `openspec/changes/c012/tasks.md`
- `openspec/TRACEABILITY.md`
- `NOTES.md`

T50/T34/T35/T36 checkbox 与追溯收口提交为 `b1018c3`（`C012 T50 T34 T35 T36 completion and consistency`）；Astra 复核后的 spec/tasks 事实修正提交为 `bf7e0b2`（`C012 T50 correct closure evidence mapping`）。本报告文件按 T50 要求保存在 `.work/c012/completion.md`，未把 `.work` 日志批量加入 git。引用的既有阶段提交包括 T22 `eac4e26`、T23 `8c9e2db`、T30 `1d19d47`、T31 `91d8068`、T32 `1ce81c4`、T49 `1dbf008`、T41 当前受控浏览器证据 `6c809e1`（`8065879`仅为历史不完整证据）。`AGENTS.md` 与 `docs/PRD-v1.2.md` 的工作树改动未纳入本次提交。

## 2. 实现的 spec 条款与追溯表回填

- T22/AC-17：沿用既有 task #1–#3 及 task #4 单次诊断证据；三次任务终态与集合比较满足“第三次新增 0 或仅陈宁 character +1”的当前门槛。task #3 完整 raw response 缺失、task #4 不替代 task #3 的限制已写入报告和追溯。
- T23–T26/AC-16、AC-18、AC-19：独立示范项目 #2/episode #2 的四项既有资产、分镜和两个动作段证据保留；T26 沿既有需求方裁决采用宿舍与球馆视觉证据。
- T26C/AC-15、AC-16、AC-26：当前 6570-byte 模板的 Clip1/Clip2 各一次诊断、正式设置 API install、安装后 verify、同库安全重启后 verify 及 API/asyncpg 回读已回填。
- T26D/AC-18、AC-19、AC-26：正式页面 Clip2→Clip1 各一次，task #17/#18、take #7/#8、built prompt、数据库、媒体和播放证据已回填；旧 task #16 失败证据保留。
- T47/AC-13、AC-15、AC-26：当前四 key 部署闭环及实际消费源已回填；旧 10756/12221/10146/10385/10283/5266 批次明确标为历史。
- T32、T48、T49、T50及T34–T36：发布说明、追溯、阶段回归、完成报告和文档状态核对按本报告收口；不新增自动测试。

B1–B7 修复闭环与原始证据对应如下：

| 审查项 | 修复任务/当前来源 | 修复 commit | 原始输出/证据 | 追溯 AC |
|---|---|---|---|---|
| B1 | T37 | `5e06ee9` | `.work/c012/T37-test-targeted.*` 及 B1 原始探针 | AC-07 |
| B2 | T38 | `38e576d` | `.work/c012/T38-test-red-business-real.*`（修前红测）与 `.work/c012/T38-test-targeted.stdout.log`、`.stderr.log`、`.exit-code.txt`（修复后） | AC-04 |
| B3 | T39 | `6eeb530` | `.work/c012/T39-test-red.*`（修前红测）与 `.work/c012/T39-test-targeted.stdout.log`、`.stderr.log`、`.exit-code.txt`（修复后） | AC-11 |
| B4 | T47 当前正式闭环 | `4f340cd` | `.work/c012/T26C-formal-current-install-20260913.*`、`T26C-formal-current-verify-after-install-20260913.*`、`T26C-formal-current-restart-health-20260913.*`、`T26C-formal-current-verify-after-restart-20260913.*`、两次 readback | AC-13/15/26 |
| B5 | T41 当前慢关闭复核 | `6c809e1` | `.work/c012/probe-b5-browser-evidence.json`（identity=`t41i_20260913_181412`）、`.work/c012/T41-browser-arm-20260913_181412.stdout.log`、`.stderr.log`及人工记录 `.work/c012/T41-browser-arm-manual-20260913_181412.md`；`8065879`仅为证据不完整的历史提交 | AC-12 |
| B6 | T42/T43/T44/T45/T46 | `5afff50`、`ca38fe8`、`31ea5e2`、`9717892`、`a77e43c` | 各任务 `.work/c012/T42-*` 至 `T46-*` 原始 stdout/stderr/exit 与定向回归 | AC-04/20/22 |
| B7 | T48 | `4bc6354` | `.work/c012/T48-collect-only.*`、`.work/c012/review-test-id-coverage.json` | AC-01/25 |

该表把 8065879 保留为 B5 历史证据，不将其与当前 6c809e1 并列为当前通过来源。

## 3. 实现取舍与偏离

- 当前 6570-byte format-example 模板是 Astra 授权后由 B/C/D 证据闭环确认的部署输入，不把旧 10756-byte 用户批准基线冒称为当前正文，也不声称用户对 6570 bytes 逐字审批。
- Clip2 的正式视频未显式回切 Shot3，按 Astra 对 AC-19 §6.2 第 5 项的裁决记录为剪辑/质量限制，不新增四镜回切门槛；Clip1 的正式 rendered request 与早期诊断 request 不逐字相等，唯一差异是既有 T31 尾注 `（T31生成中编辑）` 十字符，已明确记录 `exact=false`。
- Clip1 built prompt 出现非核心 `sleeveless dress` 措辞，且抽帧观察到局部环境细节幻觉；主体、主要服装区分、宿舍与三项核心动作仍按当前 AC-19 记录，未把限制静默抹除。
- 正式 task payload 未保存独立 raw vLLM response，因此 task #3 的模型漏提、错误 ID 复用、后端丢弃不能从现有后端日志补证；当前正式 task 的 built prompt、Comfy prompt ID、落库 take 证明本批未观察到后端丢弃，但不替代 raw response 证据。没有重试、fallback、响应改写或额外模型调用。

## 4. 自动测试

实际执行的关键命令及结果如下；完整 stdout/stderr/exit 文件均留在 `.work/c012/` 对应前缀下。

- `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 1`：当前批 wrapper exit 0；`.../T26C-clip1-20260913_191926`。
- `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 2`：当前批 wrapper exit 0；`.../T26C-clip2-20260913_192116`。
- `python -m app.deploy_templates --base-url http://127.0.0.1:8000 --input-dir deployment/templates --mode install`：exit 0，关键输出 `installed=script2assets,script2shots,zimage,minimaxh3`。
- 同命令 `--mode verify`：安装后和同库重启后均 exit 0，四 key 均回读。
- 显式导出目标 `DATABASE_URL`/`DATA_DIR` 后 `python -X utf8 .work/c012/acceptance.py observe --real`：exit 0，任务/Comfy 队列为空、vLLM sleeping；未配置显式 `DATABASE_URL` 的一次命令 exit 1，关键断言为 `DATABASE_URL must be explicitly exported for C012; refusing .env fallback`，失败原文保留。
- `git diff --check`：exit 0。
- T49 已在无新增生产代码/测试改动的受测输入上完成隔离库 `python -m pytest -q`：`414 passed in 206.68s (0:03:26)`、exit 0；本轮只修改模板与文档，不机械重跑完整 pytest。迁移 `upgrade/current/check` 和前端 test/build 的既有原始日志见 T49。
- 前端复用基线为 T33 受测 commit `8886e9f`；`.work/c012/T49-frontend-reuse.stdout.log` 记录 `frontend_diff_8886e9f_to_HEAD=empty`、T33 `35 files/175 tests`、`68 modules`，test/build 均 exit 0。T49 后至最终 HEAD，`frontend`、`backend/app`、`backend/tests`及依赖文件无变化；仅有部署模板/README 文档输入变化。Astra 作为审查者另以 `3f2913a75bce70c030e86f124d82bd75613f80aa` 运行隔离 `python -m pytest -q`：`414 passed in 408.88s (0:06:48)`、exit 0；该结果与执行者 T49 的 `206.68s` 证据分开归属。

保留的失败项包括：当前正式输入前一次 `verify-inputs` 因工作树 CRLF exit 1、历史 T26C 候选诊断失败、旧 task #16 视频消费失败，以及 task #3 raw response 缺失；修正后的命令和后续成功结果没有覆盖这些原始文件。

## 5. 人工/UI 走查

- 操作：核对 8000 后端、8001 vLLM、8188 Comfy、目标 PostgreSQL 与 DATA_DIR；观测：health/binding 为 healthy/valid，数据库为 `ai_drama_studio_c012_m6_20260910`，DATA_DIR 为 `D:\ai_drama_studio\.work\c012\t21-m6-data`，active task=0，Comfy queue=0/0，vLLM sleeping=true（预期：真实服务、库、目录、空队列和模型状态一致）。
- 操作：经正式设置 API 安装当前四模板并在同库后端重启后再次 verify/readback；观测：四 key 齐全、正文逐字等于部署输入、均无 `[占位]`、重启无自动 PATCH（预期：安装和重启前后同一部署正文）。
- 操作：在真实 Director 页面选择 Clip #2，点击 Generate video 一次；观测：创建 task #17，终态 `done/progress=1/error=null`，生成 take #7，10.125s、H.264 960x544、`is_current=false`，旧 take #4 仍 current（预期：一次正式 Clip2 新 take，不切换 current）。
- 操作：播放 take #7，从页面显示 0:00 播放到显示 0:10；观测：播放器到达末尾并停止；抽帧观测 0.0s 球馆内芳嘉蔓、2.75s 指向出场方向、3.5s后乔彦茜近景僵住，无抽样额外肢体或主体消失（预期：球馆、入场/指向与僵住核心画面及异常检查）。
- 操作：在真实 Director 页面选择 Clip #1，点击 Generate video 一次；观测：创建 task #18，终态 `done/progress=1/error=null`，生成 take #8，8.0s、H.264 960x544、`is_current=false`，旧 take #3 仍 current（预期：一次正式 Clip1 新 take，不切换 current）。
- 操作：播放 take #8，从页面显示 0:00 播放到显示 0:08；观测：播放器到达末尾并停止；抽帧观测 0.0s 宿舍、1.5–2.75s 芳嘉蔓入门、3.5s乔彦茜抬眼、5.25–7.9s恢复用筷子吃饭，无抽样额外肢体或主体消失（预期：宿舍、入门/抬眼/继续吃饭核心画面及异常检查）。
- 操作：在受控正式 TasksPage `http://127.0.0.1:5175/tasks` 选择数量 `100`、展开 Task #41，确认 running 后只创建一次 release marker；观测：同一慢连接以 WS close code `1013`/`send_timeout` 关闭且在途 send 被取消（预期：慢连接按生产超时路径关闭，不伪造外部网络原因）。
- 操作：等待浏览器自动重连并保持 #41 详情展开；观测：socket sequence `1391` 后先出现列表 `GET /api/tasks?limit=100` sequence `1395`，再出现详情 `GET /api/tasks/41` sequence `1400`，页面列表与展开详情均为 `done/100%`、error `—`、完成时间有值（预期：socket-first 后列表/详情按服务端终态重建）。
- 操作：终态 DOM 已观察后只创建一次 confirmation marker，并读取独立终态；观测：Task #41 为 `done/1.0/error_msg=null`，`generation=0`、`cancel=0`，无生成/取消 POST 重放，临时后端、端口、目录和连接随后清理（预期：确认晚于页面终态观察，DB 与 UI 一致且不重放 mutation）。证据：`.work/c012/T41-browser-arm-manual-20260913_181412.md`、`.work/c012/probe-b5-browser-evidence.json`。
- 操作：只读比较 task #1–#3 的输入 snapshot、数据库/API集合和 task #4 被动采集；观测：task #1/#2/#3 script revision=2/2/3，最终原四项资产未变；task #3 raw response无法恢复，task #4只返回四个合法既有 ID，未出现陈宁新增（预期：保留失败证据并区分模型漏提、错误 ID 复用、后端丢弃，不以 task #4 代替 task #3）。

## 6. 沉淀

本次追加到 `NOTES.md` 的五行已验证事实：当前 6570-byte 模板及 SHA-256；正式 install/verify/回读；task #17/#18 与 take #7/#8；Clip2 exact 与 Clip1 T31 尾注差异；目标库/DATA_DIR、资产数、空队列和质量限制。

`DECISIONS.md` 候选：

- 正式模板部署应把 install、安装后 verify、同库重启后 verify、API/asyncpg 逐字回读和实际消费源作为同一闭环证据组。
- prompt 字节精确性与既有 stale/编辑观察标记应分开记录；非核心 marker 导致的 `exact=false` 不应被改写成 `exact=true`。
- 若需区分模型漏提、错误 ID 复用和后端丢弃，诊断装置应一次性保存完整模型 request/response、解析资产和合并前后快照，失败即停且不循环重跑。

未修改 `DECISIONS.md`，等待 Sol 决定是否收录；对 `AGENTS.md` 无修订建议。
