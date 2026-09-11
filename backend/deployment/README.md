# C012 正式模板部署输入

本目录只保存四个固定设置 key 的批准正文，供后续 T18 显式部署 CLI 使用；本 task 不安装模板、不修改数据库，也不在 lifespan 自动覆盖设置。

来源与逐字复核（2026-09-10）：

- `script2assets.txt`：C005 `openspec/changes/C005/spec.md` §5.1；1,253 个字符，正文不含 Markdown 围栏，文件使用 UTF-8/LF，末尾无换行。
- `script2shots.txt`：归档 C006 `openspec/archive/C006/spec.md` §5.1；1,181 个字符，正文不含 Markdown 围栏，文件使用 UTF-8/LF，末尾无换行。
- `zimage.txt`：归档 C007 §4.1 与 T13 批准的单一 `zimage` 正文；使用历史正式设置读回的 2,770 个字符原文恢复，正文不含 Markdown 围栏，文件使用 UTF-8/LF，末尾无换行，未按摘要或长度重写。
- `minimaxh3.txt`：`C:\Users\Administrator\Downloads\minimaxh3-流水线适配版模板.md`；与历史批准正文逐字符一致，7,340 个字符，保留批准正文内原有的两个示例代码围栏，文件使用 UTF-8/LF，末尾有一个换行。

四个文件名分别对应 `script2assets`、`script2shots`、`zimage`、`minimaxh3`，正文保留批准来源中的占位符、换行和末尾换行语义。正式安装与安装后/重启后回读由后续 task 执行。

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
python -X utf8 .work/c012/acceptance.py verify-inputs
python -X utf8 .work/c012/acceptance.py preflight --real
python -X utf8 .work/c012/acceptance.py observe --real
```

`preflight --real` 读取当前绑定、Comfy 节点/LoRA、队列和 vLLM sleep/wake 状态；`observe --real` 只做 GET 与数据库 SELECT，不创建任务、不生成、不写业务数据，也不接入生成重放器。
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

当前工作树中的 `minimaxh3.txt` 是 T26 诊断候选，T26C/T26D 仍未完成，不能把它写成已部署。T21/M6 之前的正式安装与回读证据只证明当时部署的输入；候选正文如需成为运行配置，必须重新满足上述 install、安装后 GET、同库重启后 GET 及 M6 消费门槛。

## 显式恢复与失败处理

恢复只针对本轮明确拥有的后端进程和数据库。先记录监听 PID、数据库名、`DATA_DIR` 与当前任务；不要终止未知用户的 vLLM、ComfyUI 或任务。

1. 后端异常退出后，以同一 `DATABASE_URL`、`DATA_DIR` 和外部服务地址启动一个后端实例。
2. 启动恢复会把遗留 `running` 任务置为 `failed`，`error_msg` 为 `server restarted`；`queued` 任务保持 `queued` 并由唯一 worker 后续消费。第二个同库后端因 advisory lock 拒绝启动，不得并行运行。
3. 使用正式 REST/DB 读取任务终态、队列和媒体，再执行 `python -X utf8 .work/c012/acceptance.py observe --real`；不要通过重新提交、复制 payload 或手工改库“恢复”任务。
4. vLLM/Comfy/绑定/数据库检查失败时停止当前验收并保留原始错误；任务失败、取消或媒体提交失败均按生产错误合同记录，不自动重试。

API 输入错误遵循统一合同：资源/任务冲突或前置条件使用 `409`，内容/业务校验使用 `422`，未知资源使用 `404`；错误体必须有非空 `detail.code` 与 `detail.message`。R5/R5a/R10 等生成前置失败是 `202` 加立即失败 Task，不改成 `409/422`，也不调用外部模型或媒体服务。

## 示范集媒体与实测环境

T31 当前真实示范库为 `ai_drama_studio_c012_m6_20260910`，`DATA_DIR=D:\ai_drama_studio\.work\c012\t21-m6-data`，后端 `8000`、vLLM `8001`、ComfyUI `8188`，模型为 `Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`，GPU 为 `cuda:0 NVIDIA GeForce RTX 4090`。T31 观察到 task #15 完成后无 active task、Comfy queue `0/0`、vLLM sleeping；原始只读证据见 `.work/c012/T31-observe-after-20260911.json` 与 `T32-observe-20260911.log`。

可由同源前端或正式 API 打开以下已存在媒体；这些链接只用于回读，不会触发生成：

- Director：`http://127.0.0.1:5173/projects/2/episodes/2/director`
- Clip #1 视频列表：`http://127.0.0.1:8000/api/clips/1/videos`
- Clip #1 原 current take #3：`http://127.0.0.1:8000/media/clip-videos/3`
- Clip #1 T31 新 take #5（非 current、用于 stale 复核）：`http://127.0.0.1:8000/media/clip-videos/5`
- Clip #2 T25 current take #4：`http://127.0.0.1:8000/media/clip-videos/4`

T31 的真实页面操作、task #15 旧 payload、Shot #2 `changed`、Clip #1 `ready/stale` 及 take #5 的媒体探针分别保存在 `.work/c012/T31-running-task-20260911.json`、`T31-edited-state-20260911.json`、`T31-final-state-20260911.json`。T22 task #1–#3 的失败证据、T26 历史失败与 T27–T30 受控失败证据必须继续保留。

## 证据边界与本轮限制

真实 M6 证据使用正式 UI/API/WS、真实 PostgreSQL、vLLM、ComfyUI、workflow、GPU 和 `DATA_DIR`；T27–T30 的 B/R 矩阵使用隔离数据库、隔离文件目录与受控 vLLM/Comfy stub，只能证明生产业务/任务/资源通路，不能证明真实模型质量或 GPU 结果。T26 指定 prompt 的直接 Comfy 证据不登记为平台 Task、ClipVideo、current 或模板部署。

截至本说明，T26C/T26D 与 AC-26 的完整部署/重启/两段正式新 take 门槛仍未完成；T33 G2 才执行最终隔离库完整回归。原生桌面 200%、动态 `reduced-motion`、真模型随机性/跨输入稳定性未验证；trash 的受控计时分支也不等于真实等待 24 小时。所有这些限制必须在发布报告中保留，不能用受控证据升级为真实 GPU 或发布结论。
