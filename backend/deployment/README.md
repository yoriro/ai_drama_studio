# C012 正式模板部署输入

> 路径整理（2026-09-14）：验收驱动现位于 `backend/scripts/c012_acceptance.py`，锁顺序记录现位于 `openspec/archive/c012/lock-order.md`。下文相应入口已更新；历史原始日志中的旧路径不改写，证据输出仍位于本地 `.work/c012/`。

本目录只保存四个固定设置 key 的批准正文，供正式部署 CLI 读取；安装动作与数据库写入必须经正式设置 API 完成，不在 lifespan 自动覆盖设置。

## 当前状态与历史来源（2026-09-13）

当前唯一部署输入是 `minimaxh3.txt` 的 6570 UTF-8 bytes、60 lines、SHA-256 `13e271e8b59a1a507f0286c43ae9399bbb3ae9d78aa42a221787e0614055c8d8`。它已在目标库 `ai_drama_studio_c012_m6_20260910`、DATA_DIR `D:\ai_drama_studio\.work\c012\t21-m6-data` 经正式设置 API install；安装后 verify、同库后端安全重启后 verify 与 API/asyncpg 回读均 exit 0，四个固定 key 齐全、正文逐字等于部署输入、均无 `[占位]`，重启无自动 PATCH。对应证据为 `.work/c012/T26C-formal-current-*`。

当前正式消费是同一示范项目/集的 Clip2 task `#17`→take `#7` 与 Clip1 task `#18`→take `#8`，两 task 均 `done/progress=1/error=null`，两 take 均为非 current，旧 current take 保留；Clip2 视频10.125s、Clip1视频8.0s，均为 H.264 960x544。Clip2 formal rendered request 与诊断 request 逐字相等；Clip1 仅差既有 T31 尾注 `（T31生成中编辑）` 十字，exact=false。两段 built prompt、Comfy prompt ID、REST/DB、媒体探针、完整播放和抽帧证据见 `.work/c012/T26D-clip{1,2}-formal-*`；raw vLLM response 未单独持久化。Clip2未回切Shot3、Clip1有局部环境细节幻觉及非核心服装措辞，均是已记录的质量限制，不是额外验收门槛。

需求方于 2026-09-13 明确“确定为最终正文”：批准 `.work/c012/T47-deployment-proposal.txt` 的 10,756-byte、86 行正文，作为本轮三处修订前的历史部署基线。该正文从 `T26C-clip2-20260911_122039/request.json` 的实际请求恢复，只把 ACTUAL INPUT 的五项输入值还原为既有占位符；此前生产 renderer 使用该批冻结输入回放与原请求逐字相等。该批 `input-snapshot.json.template_content` 是历史旧模板，不能用它替换当前6570-byte输入。其他三个模板保持原文；不改变五变量、schema、设置 API、R4 或不追溯语义。

该批准对应历史10,756-byte批次；其后实际运行批次已按授权切换为当前6570-byte输入。历史批次的安装、失败、task #16与所有原始证据继续保留，不与当前状态混写。

下列 2026-09-10 来源及后续诊断段落是历史记录；涉及 MiniMax 当前正文的旧状态由本节覆盖。
为避免状态混淆，本节以下历史段落中的“当前候选/当前 B 阶段”只指当时记录的候选，不指当前6570-byte部署输入；当前状态只以上方两段为准。

2026-09-13 后续窄修订授权（历史规则记录）：本轮工作树的 `minimaxh3.txt` 仅允许改动时间轴说明、非对白英文描述、连续场景非核心承接和既有逐镜对白/动作规则；时间只需大致参考 `duration_est` 权重，不以精确比例或毫秒四舍五入作为通过门槛，但仍检查镜头数量/顺序、Shot1起点、后续起点可解析递增且不超请求片长。非对白的 subject/retention/summary/detailed_description/soundscape 用英文，合法 asset_name、对白和明确屏幕文字保留原语言；每镜核心动作、方向/目标/结果仍须在对应段落，空对白不得出现 speech-related placeholder，不做响应后处理。该规则已用于当前6570-byte批的 A/B/C/D 证据。

本轮 A 阶段 renderer selfcheck 与模板人工审计均 exit 0；较早 B 阶段 Clip1 修订模板诊断的时间观察为 `[3.6,6.1]`、旧装置期望为 `[3.2,5.867]`，该精确比较现已由用户撤销，不写成模型数学能力已修复；该批描述混入中文服装词。输入 Shot2 本身提到门口的芳嘉蔓，输出 Subject1 门口目标有输入依据，但 retention 中该主体的画面可见性依据不确定，不能定性为身份引用错误。完整较早证据为 `.work/c012/T26C-clip1-20260913_145948`。

当前 B 阶段唯一一次 Clip1 修订模板诊断命令 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 1` wrapper exit 0，证据为 `.work/c012/T26C-clip1-20260913_152658`；结构/时间轴/非对白英文检查均为 true，观察起点 `[3.0,5.5]` 满足当前时间合同，两条对白逐字存在。原人工复核记录 Shot2 未重复“坐在书桌前”；Astra依据用户最新连续场景裁决确认该非核心姿态可由前镜/整体场景承接，不作为本批阻塞，原始响应未被改写，后续视频仍须实际观察姿态/空间衔接。未见错误 ID 复用；诊断不进入平台 Task、Comfy 或合并路径，不能归因后端丢弃。后检 tasks=15/active=0、Comfy=0/0、vLLM sleeping=true；完整记录见同目录 `review.md` 与 `post-diagnostic-observation.json`。按裁决继续一次 Clip2 诊断；两批通过前不进入当前候选正文 install/verify/重启或正式视频。

当前 B 阶段唯一一次 Clip2 修订模板诊断命令 `python -X utf8 .work/c012/prompt_diagnostic.py run --clip 2` wrapper exit 1，证据为 `.work/c012/T26C-clip2-20260913_154409`；结构检查的 headings/shot labels/time labels/time_axis 为 true，但 `english_non_dialogue=false`，场景定义混入“两侧设有观众席”。时间起点 `[3.0,5.5,8.0]` 合法；人工核对还发现 Shot1 详细段落漏掉球员出场方向注视及明确指向动作，summary不能替代该镜核心动作，且空对白的 Shot2/Shot4 各输出了模板禁止的 `No dialogue.` 占位。两条对白逐字存在，3个Subject/Picture参考映射有输入依据，未见错误 ID 复用；诊断不进入平台 Task、Comfy 或合并路径，不能归因后端丢弃。后检 tasks=15/active=0、Comfy=0/0、vLLM sleeping=true；完整记录见同目录 `review.md` 与 `post-diagnostic-observation.json`。按失败即停，不进入当前候选正文 install/verify/重启、T26D或正式视频。该批与下列基线重建前状态均为历史记录。

2026-09-13本轮新候选 A/B 记录：基线核对 `.work/c012/T26C-baseline-validation-20260913.*` exit 0 后，从基线只改授权措辞，候选为12,043 bytes/87行；Clip1 仅执行一次，结构检查为 true，但人工核对确认输入 Shot1 的完整对白被模型漏提，故 B 阶段失败即停，Clip2、重新部署/回读和正式视频未执行。完整证据目录 `.work/c012/T26C-clip1-20260913_161430`、`review.md` 及对应 `T26C-candidate-clip1-20260913.*`；终态观察为 `T26C-candidate-clip1-postobserve-20260913.*`。上一版12,478-byte候选及所有失败记录保留；该批未进入平台 Task/Comfy/合并路径，不能归因后端丢弃。

来源与逐字复核（2026-09-10，历史）：

- `script2assets.txt`：C005 `openspec/changes/C005/spec.md` §5.1；1,253 个字符，正文不含 Markdown 围栏，文件使用 UTF-8/LF，末尾无换行。
- `script2shots.txt`：归档 C006 `openspec/archive/C006/spec.md` §5.1；1,181 个字符，正文不含 Markdown 围栏，文件使用 UTF-8/LF，末尾无换行。
- `zimage.txt`：归档 C007 §4.1 与 T13 批准的单一 `zimage` 正文；使用历史正式设置读回的 2,770 个字符原文恢复，正文不含 Markdown 围栏，文件使用 UTF-8/LF，末尾无换行，未按摘要或长度重写。
- `minimaxh3.txt`：10,756 UTF-8 bytes、86 行正文是 2026-09-13 的历史批准基线；随后已授权 T26C 修订使 HEAD `6c809e1` 中的 tracked 文件在本轮五点候选前为 12,221 bytes、88 行。当前五点候选仅在工作树中，快照为 `.work/c012/T47-template-five-point-20260913.txt`、10,146 bytes/79 行，尚未经正式设置 API 安装；上一版12,478-byte候选及其 SHA-256 `2e635a84735ad267112b430f74fee25fab00f97c83693101409185d12bc3be48` 仅作为历史来源和失败证据保留。D-014/C009 下载文件及其正文仅作为历史来源证据保留。

四个文件名分别对应 `script2assets`、`script2shots`、`zimage`、`minimaxh3`，正文保留批准来源中的占位符、换行和末尾换行语义。T47 已经针对历史批准正文通过正式设置 API 完成安装，并在安装后及同库后端重启后逐字回读；当前五点候选尚未重新安装，迁移占位符只用于新库安装前核对。

2026-09-13 当前五点候选 B 阶段：A `python -X utf8 .work/c012/prompt_diagnostic.py selfcheck` exit 0，真实 `python -X utf8 backend/scripts/c012_acceptance.py preflight --real` exit 0；Clip1 仅一次 `.work/c012/T26C-clip1-20260913_183540`，结构与核心逐镜内容经 Astra 复核通过，原始疑点与裁决保留；Clip2 仅一次 `.work/c012/T26C-clip2-20260913_184107`，wrapper exit 1，唯一结构失败是场景定义未译 `两侧`，其他结构/对白/空对白/时间检查为 true。两次 `observe --real` exit 0；诊断未进入平台 Task/Comfy/merge，未见错误 ID 复用，不进入重新安装、重启回读或 T26D 正式视频。

## 显式部署命令

命令在 `backend` 目录执行，必须显式提供后端地址和输入目录：

```powershell
$env:C012_BASE_URL = "http://127.0.0.1:8000"
python -m app.deploy_templates --base-url "$env:C012_BASE_URL" --input-dir deployment/templates --mode install
python -m app.deploy_templates --base-url "$env:C012_BASE_URL" --input-dir deployment/templates --mode verify
```

`install` 先完整读取并校验四个文件，再按 `script2assets`、`script2shots`、`zimage`、`minimaxh3` 顺序各 PATCH 一次，最后 GET 逐字核对；任一步失败立即非零，不重试、不回滚已成功的独立提交，也不自动重启后端。`verify` 只 GET 和逐字比较，不发送 PATCH。

## M6 真实输入与观察命令

`m6-script.txt` 与 C012 spec §6.1 的 `text` 代码块逐字保存，当前 `SCRIPT_CHAR_LIMIT` 由验收驱动读取并检查。三连跑的唯一追加句为“球馆内，工作人员陈宁走到芳嘉蔓身边递给她一张入场券。”；两个片段目标依次为“芳嘉蔓进门催促、乔彦茜抬眼回应后继续吃饭”和“芳嘉蔓指向出场球员、乔彦茜由平静变为僵住”。

```powershell
python -X utf8 backend/scripts/c012_acceptance.py verify-inputs
python -X utf8 backend/scripts/c012_acceptance.py preflight --real
python -X utf8 backend/scripts/c012_acceptance.py observe --real
```

`preflight --real` 读取当前绑定、Comfy 节点/LoRA、队列和 vLLM sleep/wake 状态；`observe --real` 只做 GET 与数据库 SELECT，不创建任务、不生成、不写业务数据，也不接入生成重放器。

## 历史 T26 动作诊断记录（不代表当前部署状态）

最终T26裁决（2026-09-11，历史）：需求方接受宿舍既有take#3复核与指定122039原始prompt的真实Comfy球馆视频组合验收，T26通过。证据 `.work/c012/T26-selected-video-20260911_140139/verdict.md`。该历史视频不等于当前6570-byte批的完整 AC-26 消费证据；当前T26C/D的正式页面消费以本说明开头的 task #17/#18 记录为准。独立小样的非压实 reference_name 不符合生产快照约束，其编号失败不证明生产编号缺陷，详见通用性报告开头校正。

历史通用性复验（2026-09-11，覆盖下述历史结果）：室外/空镜/多人对白/独立旁白规则已修正，但当时同一模板的球馆与独立小样均未完整通过。球馆仍有未译词和空对白占位，小样仍重排引用身份；证据 `.work/c012/T26-generalization-review.md`。该记录不用于否定 2026-09-13 批准正文的部署事实，也不把历史单次通过升级为稳定性证明。

历史诊断状态（2026-09-11）：需求方授权模板诊断循环后，第11轮球馆输入的原始 prompt 通过结构与逐镜人工检查，见 `.work/c012/T26C-clip2-20260911_122039/review.md`。最终正文使用英文转写流程、独立逐镜对白复制和与本剧本无关的完整格式示例；累计11轮含1次超时，失败记录保留；仅一次球馆 prompt 通过，不代表稳定性、宿舍输入或视频质量。以下保留此前修订过程记录，当前6570-byte批不由该历史批次替代。

2026-09-11 历史最近一次修订采用统一逐镜结构与空对白显式分支，主体明确后允许无歧义代词。单次模型诊断仅修复了部分缺项，时间及对白/人物引用仍失败；当时文件尚未部署，证据见 `.work/c012/T26C-clip2-20260911_104820/review.md`。

需求方授权将 `minimaxh3.txt` 改为忠实逐镜转写、明确动作与时间的正文（UTF-8/LF）；上文 7,340 字符来源记录描述历史批准输入，旧正文由 git 保留。2026-09-11 继续明确同号 Subject/Picture 定义句式、逐镜主体引用和画风位置。该历史记录中的文件及绑定失败证据保留；其余三模板不变。当前6570-byte批的正式安装、task/take/current边界与AC-26实际消费见本说明开头，不修改 schema、生产代码或迁移，不增加模板版本机制。

## 启动与运行前检查

以下命令是本机已实际核对过的启动/检查路径。启动 acceptance 或正式后端时，必须在当前 shell 显式提供 `DATABASE_URL` 与 `DATA_DIR`；DSN 密码不写入日志。不要用 backend/.env 的默认业务库或未知进程代替本轮指定实例。

```powershell
Start-Service -Name postgresql-x64-18
Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 -InformationLevel Quiet

Set-Location D:\ai_drama_studio\backend
$env:C012_BASE_URL = "http://127.0.0.1:8000"
# DATABASE_URL、DATA_DIR、VLLM_BASE_URL、VLLM_MODEL、VLLM_TEMPERATURE、COMFY_BASE_URL
# 由部署环境显式注入；不要把包含密码的值提交或打印。
Start-Process -FilePath "python.exe" `
  -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" `
  -WorkingDirectory "D:\ai_drama_studio\backend" -WindowStyle Hidden
```

本机已验证的外部服务入口是 vLLM `http://127.0.0.1:8001`、ComfyUI `http://127.0.0.1:8188`。vLLM 使用带 `--enable-sleep-mode` 的既有 WSL 启动命令，ComfyUI 使用 `F:\ComfyUI\venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188`；启动后先检查真实 `/health`、模型、Comfy `/system_stats`/`/queue`、workflow binding 和监听进程归属，再进入 M6。端口可用不等于模型/节点已注册，不能跳过这些检查。

## 四模板安装、verify 与重启回读

模板安装只走正式设置 API，不直接写数据库、不在 lifespan 自动覆盖设置。新生产等价库迁移到 head 后，先确认四个固定 key 仍是 migration 的 `[占位]` 内容，再在 `backend` 目录执行：

```powershell
python -m alembic upgrade head
python -m alembic current
python -m alembic check
python -m app.deploy_templates --base-url "$env:C012_BASE_URL" --input-dir deployment/templates --mode install
python -m app.deploy_templates --base-url "$env:C012_BASE_URL" --input-dir deployment/templates --mode verify
```

`install` 会先完整校验恰好四个 UTF-8 文件及占位符，再按 `script2assets`、`script2shots`、`zimage`、`minimaxh3` 各 PATCH 一次并 GET 逐字核对；`verify` 只 GET，必须显示四个 key 且 PATCH 次数为 0。安装后停止并仅重启本轮拥有的后端进程，在同一数据库和 `DATA_DIR` 下再次执行 `--mode verify`。任一步失败都保存 stdout/stderr/exit 和已成功 key，不重试、不自动回滚或用旧库结果冒充通过。

历史 T47 安装与诊断状态：修订前工作树中的 `minimaxh3.txt` 是 2026-09-13 的旧部署正文；T47 曾针对该旧正文完成 install、安装后 GET、同库重启后 GET，且四 key 逐字回读一致。上一版12,478-byte、12,043-byte及其他候选的失败证据仍保留；历史安装/回读不等于当前6570-byte批部署或正式消费证据，T21/M6之前的回读只证明当时输入。

本轮定向修复前只读对照 `.work/c012/T26C-clip1-20260913_161430` 与 `.work/c012/T26C-clip1-20260913_152658`：当前 rendered request 含 Shot1 完整对白，原始 response 与生产 `_built_prompt` 结果均缺该对白；`finish_reason=stop`、completion `937`、total `4198`，请求未带 `max_tokens`，GET `/v1/models` 报 `max_model_len=16384`，没有截断或提取丢失证据。152658 的请求、raw response 与提取 prompt 均含该对白。唯一候选变更限于 COPY DIALOGUE 局部：非空对白在既有镜号/时间、景别/运镜/场景 lead-in 后立即写入同一段落并先于动作句；空对白和其余规则不变。只读根因记录为 `.work/c012/T26C-targeted-root-cause-20260913.*`，本轮一次 Clip1 复验尚未执行。
上述三段为历史批次，原始停止、Astra验收解释更正及 Clip2 诊断证据均保留；当前6570-byte批的B/C证据见本说明开头和 `.work/c012/T26C-formal-current-*`，不与历史候选混写。

2026-09-13 历史候选 C/D 记录：旧候选的 `verify-inputs` CRLF失败、安装/回读及 task #16 失败消费证据全部保留；它们不表示当前6570-byte批状态。当前批次状态见本说明开头。

## 显式恢复与失败处理

恢复只针对本轮明确拥有的后端进程和数据库。先记录监听 PID、数据库名、`DATA_DIR` 与当前任务；不要终止未知用户的 vLLM、ComfyUI 或任务。

1. 后端异常退出后，以同一 `DATABASE_URL`、`DATA_DIR` 和外部服务地址启动一个后端实例。
2. 启动恢复会把遗留 `running` 任务置为 `failed`，`error_msg` 为 `server restarted`；`queued` 任务保持 `queued` 并由唯一 worker 后续消费。第二个同库后端因 advisory lock 拒绝启动，不得并行运行。
3. 使用正式 REST/DB 读取任务终态、队列和媒体，再执行 `python -X utf8 backend/scripts/c012_acceptance.py observe --real`；不要通过重新提交、复制 payload 或手工改库“恢复”任务。
4. vLLM/Comfy/绑定/数据库检查失败时停止当前验收并保留原始错误；任务失败、取消或媒体提交失败均按生产错误合同记录，不自动重试。

API 输入错误遵循统一合同：资源/任务冲突或前置条件使用 `409`，内容/业务校验使用 `422`，未知资源使用 `404`；错误体必须有非空 `detail.code` 与 `detail.message`。R5/R5a/R10 等生成前置失败是 `202` 加立即失败 Task，不改成 `409/422`，也不调用外部模型或媒体服务。

## 示范集媒体与实测环境

T31 实测快照使用真实示范库 `ai_drama_studio_c012_m6_20260910`、`DATA_DIR=D:\ai_drama_studio\.work\c012\t21-m6-data`，后端 `8000`、vLLM `8001`、ComfyUI `8188`，模型为 `Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`，GPU 为 `cuda:0 NVIDIA GeForce RTX 4090`。T31 观察到 task #15 完成后无 active task、Comfy queue `0/0`、vLLM sleeping；原始只读证据见 `.work/c012/T31-observe-after-20260911.json` 与 `T32-observe-20260911.log`。当前部署回读与重启证据见 `.work/c012/T47-readback-after-restart-20260913.stdout.log`。

可由同源前端或正式 API 打开以下已存在媒体；这些链接只用于回读，不会触发生成：

- Director：`http://127.0.0.1:5173/projects/2/episodes/2/director`
- Clip #1 视频列表：`http://127.0.0.1:8000/api/clips/1/videos`
- Clip #1 原 current take #3：`http://127.0.0.1:8000/media/clip-videos/3`
- Clip #1 T31 新 take #5（非 current、用于 stale 复核）：`http://127.0.0.1:8000/media/clip-videos/5`
- Clip #2 T25 current take #4：`http://127.0.0.1:8000/media/clip-videos/4`

T31 的真实页面操作、task #15 旧 payload、Shot #2 `changed`、Clip #1 `ready/stale` 及 take #5 的媒体探针分别保存在 `.work/c012/T31-running-task-20260911.json`、`T31-edited-state-20260911.json`、`T31-final-state-20260911.json`。T22 task #1–#3 的失败证据、T26 历史失败与 T27–T30 受控失败证据必须继续保留。

## 证据边界与本轮限制

真实 M6 证据使用正式 UI/API/WS、真实 PostgreSQL、vLLM、ComfyUI、workflow、GPU 和 `DATA_DIR`；T27–T30 的 B/R 矩阵使用隔离数据库、隔离文件目录与受控 vLLM/Comfy stub，只能证明生产业务/任务/资源通路，不能证明真实模型质量或 GPU 结果。T26 指定 prompt 的直接 Comfy 证据不登记为平台 Task、ClipVideo、current 或模板部署。

截至本说明，T47 的四模板安装、安装后及同库重启回读已完成，但仅针对三处修订前正文；上一版修订候选的 Clip1/Clip2失败证据保留，本轮12,043-byte候选 Clip1 单次诊断因模型漏提 Shot1 对白失败，Clip2、重新部署回读未执行。T26C/T26D 与 AC-26 的正式平台消费/两段正式新 take 门槛仍未完成。T49 已在新隔离库完成最终 CPU 回归；原生桌面 200%、动态 `reduced-motion`、真模型随机性/跨输入稳定性未验证；trash 的受控计时分支也不等于真实等待 24 小时。所有这些限制必须在发布报告中保留，不能用受控证据升级为真实 GPU 或发布结论。

## T41 B5 浏览器批次与证据修正（2026-09-13）

旧批次 `t41g_20260913_181000` 的 acceptance JSON 虽为 `status=passed`，但旧装置未完整记录实际关闭原因与关闭→重连→权威 GET 的事件链，且页面首轮健康轮询保留 `protocol_error`；该批仅保留历史/部分人工观察，不作为当前 B5 通过证据，原始文件不删除。

当前一次人工批次复用正式 `TasksPage` 与生产 `app.main:app`/lifespan/`TaskQueue`/`gen_assets_handler`/`EventBus`/WS/DB，独立库为 `ai_drama_studio_c012_t41i_20260913_181412`，DATA_DIR 为 `D:\ai_drama_studio\.work\c012\t41i-data-20260913_181412`，隔离后端 `65223`、Vite `5175`，仅外部模型 stub 为 `50603`。页面将任务数量设为100并展开 Task #41 的 running 详情；release marker 后先得到 HTTP 200 的 running/progress=0 详情，再 arm ASGI send gate；同一 gated connection `620` 的真实 WS close 为 `1013`（event sequence `1339`），在途发送取消，生产日志实际原因是 `send_timeout`。该原因是本项合法慢关闭证据，不替代 T40/AC-11 的 `subscription_overflow`。实际重连 socket sequence `1391` 后首个 `limit=100` 列表 GET 为 `1395`，目标详情 GET 为 `1400`；页面终态观察为 `done/100%/error=—/finished_at=18:16:33`，结构化验收 `.work/c012/probe-b5-browser-evidence.json` 为 `status=passed`（`ws-acceptance.json` 为同批原始输出），浏览器 mutation POST 为 `0/0`（生成 POST 127 为装置建立受控任务的生产入口记录），独立 DB/HTTP 200 详情一致，confirmation marker 在终态 DOM 观察后创建。人工记录为 `.work/c012/T41-browser-arm-manual-20260913_181412.md`；owned 后端、stub、临时目录和端口清理，默认生产端口保留。

该批只在 acceptance.py 的 `slow-page-browser` 分支为人工准备窗口设置外部 `VLLMClient` timeout/deadline 900 秒；生产 vLLM 默认120秒、WS 10秒、队列/handler/提交路径未改，不证明 TCP 拥塞或真实模型120秒超时。页面首轮健康轮询留下 `protocol_error`，隔离后端直接 health 为 HTTP 200 JSON；该观测保留为 UI 限制。验收结束后隔离后端、stub、端口和临时 DATA_DIR 均清理，生产端口未触碰。
