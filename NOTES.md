# 操作事实（截至 2026-08-28）

## 1. 确切命令

以下命令均在 PowerShell 实际执行过；数据库创建脚本从 `backend/.env` 读取 DSN，不打印密码。

```powershell
Start-Service -Name postgresql-x64-18
Test-NetConnection -ComputerName 127.0.0.1 -Port 5432 -InformationLevel Quiet

Set-Location D:\ai_drama_studio\backend
$databaseLine = Get-Content .env | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
$sourceUrl = $databaseLine.Substring('DATABASE_URL='.Length)
$notesDb = 'ai_drama_studio_notes_20260828'
$env:DATABASE_URL = $sourceUrl
$env:NOTES_DB = $notesDb
@'
import asyncio, os
from urllib.parse import urlsplit, urlunsplit
import asyncpg
async def main():
    p = urlsplit(os.environ['DATABASE_URL'].replace('+asyncpg', '', 1))
    admin = urlunsplit((p.scheme, p.netloc, '/postgres', p.query, p.fragment))
    c = await asyncpg.connect(admin)
    try:
        exists = await c.fetchval('SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname=$1)', os.environ['NOTES_DB'])
        if not exists:
            await c.execute(f'CREATE DATABASE "{os.environ["NOTES_DB"]}"')
    finally:
        await c.close()
asyncio.run(main())
'@ | python -
$env:DATABASE_URL = $sourceUrl -replace '/[^/]+$', ('/' + $notesDb)
python -m alembic upgrade head
python -m alembic downgrade base
python -m alembic upgrade head
python -m alembic current
python -m alembic check

python -m pytest -q tests/api          # 17 passed in 8.24s
python -m pytest -q tests/task_system   # 15 passed in 9.19s
python -m pytest -q                    # 32 passed in 16.88s（另一全新隔离库）

Start-Process -FilePath 'python.exe' -ArgumentList '-m uvicorn app.main:app --host 127.0.0.1 --port 8000' -WorkingDirectory 'D:\ai_drama_studio\backend' -WindowStyle Hidden
Set-Location D:\ai_drama_studio\frontend
npm run dev -- --host 127.0.0.1
npm run build
```

## 2. 环境依赖

- PostgreSQL Windows 服务：`postgresql-x64-18`，`127.0.0.1:5432`；本机账号/密码由 `.env` 使用，未写入此文件。
- 后端：`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`；`/api/system/health` 实测 200。
- vLLM：`http://127.0.0.1:8001`；模型 `Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`；权重目录 `D:\llm_models\Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`，WSL 路径 `/mnt/d/llm_models/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`。

```powershell
wsl.exe -d Ubuntu -- env VLLM_SERVER_DEV_MODE=1 VLLM_USE_FLASHINFER_SAMPLER=0 /root/vllm-env/bin/vllm serve /mnt/d/llm_models/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit --served-model-name Qwen3-30B-A3B-Instruct-2507-AWQ-4bit --max-model-len 16384 --gpu-memory-utilization 0.90 --port 8001 --generation-config vllm --enable-sleep-mode
```

- 实际存在并使用的环境键：`DATABASE_URL`、`VLLM_BASE_URL`、`VLLM_MODEL`、`VLLM_TEMPERATURE`；数据目录为从 backend 启动时的 `backend/data`，其下已有 `projects`、`tmp`、`trash`。
- ComfyUI 配置默认地址为 `http://localhost:8188`；本轮未启动、未健康检查，启动方式未验证。`backend/workflows` 当前不存在。
- 需预先可用：上述 PostgreSQL 服务、独立空数据库、vLLM 权重目录；媒体子目录由运行时创建。

## 3. 坑

- `KeyError: 'DATABASE_URL'` → 测试直接读 `os.environ`，不会把 `.env` 自动导出到 pytest 进程 → 运行 pytest 前显式设置 `$env:DATABASE_URL`。
- `AdvisoryLockNotAcquired: ... advisory lock is already held` → 同一数据库已有 uvicorn worker 持有 advisory lock → 测试前停止后端，或改用隔离数据库。
- `assert 20 == 0` → 复用了有历史任务的数据库，测试的空库前提已破坏 → 每轮新建库并 `alembic upgrade head`。
- `Grammar error: Unimplemented keys: ["uniqueItems"]`（HTTP 400）→ 当前 vLLM grammar 不支持该 schema 关键字 → 请求/快照移除 `uniqueItems`，重复 asset id 仍由后端硬校验。
- `AttributeError: 'coroutine' object has no attribute 'raise_for_status'` → 诊断脚本在 await HTTP 请求前使用响应对象 → 先 await 请求，再检查响应。
- `postgresql://audit:S3CRET@localhost/db` 出现在 Pydantic 校验错误 → 校验错误默认显示输入 → 使用 `SecretStr` 与 `hide_input_in_errors=True`。
- `The -replace operator allows only two elements to follow it, not 3.` → PowerShell 把替换字符串拼接解析成第三个操作数 → 将替换表达式写成 `('/' + $db)`。

## 4. 当前实际目录状态

- 实际业务目录：`backend/app/{api,core,db,models,schemas,services,tasks}`、`backend/tests/{api,task_system}`、`backend/alembic/versions`、`frontend/src/{api,components,pages,routes}`、`openspec/{archive,changes/C001..C007}`。
- 与 `project.md` 的差异：规范列出的 `frontend/src/features` 实际不存在；C007 T1 已创建并验证 `backend/app/integrations`、`backend/tests/unit` 与 `backend/workflows`。
- 运行产物/数据目录：根目录 `.runtime`、`backend/data/{projects,tmp,trash}`、`backend/.pytest_cache`、各处 `__pycache__`、`frontend/node_modules`、`frontend/dist`；这些不在规范目录树中，是当前实际存在的生成或运行目录。

- C007 T3 在新隔离数据库上验证健康接口：定向用例 6 passed，全量 pytest 51 passed；输出保存在 `.work/c007/T3-test.log`。
- 默认测试库当时被正在运行的 8000 端口后端持有 advisory lock，未停止该进程，改用隔离数据库完成 T3 验收。
- C007 T4 定向 `tests/unit/test_c007_asset_image_inputs.py` 最终 17 passed，隔离数据库完整 pytest 68 passed；原始输出保存在 `.work/c007/T4-test.log`。
- C007 T4 首次定向运行暴露新测试固定哈希期望值错误，校正期望值后定向测试通过；`alembic upgrade head` 在 `ai_drama_studio_c007_t4_full_20260828` 成功。
- C007 T5 定向请求合同测试 2 passed，隔离数据库完整 pytest 70 passed；原始输出保存在 `.work/c007/T5-test.log`。
- C007 T5 在 `ai_drama_studio_c007_t5_api_20260828` 完成 `alembic upgrade head`；测试替换并恢复 zimage 模板，POST 请求未新增 vLLM/Comfy 健康探测调用。
- C007 T6 在 `ai_drama_studio_c007_t6_races_20260828` 完成 `alembic upgrade head`；竞态定向 3 passed，完整 pytest 73 passed，原始输出保存在 `.work/c007/T6-test.log`。
- C007 T6 新增用例跨多个 `asyncio.run()` 时须在每个用例清理后 `engine.dispose()`，否则 asyncpg 连接池会报告事件循环已关闭或并发操作错误。
- C007 T7 在 `ai_drama_studio_c007_t7_commit_20260828` 完成迁移；定向最终 7 passed，完整 pytest 80 passed，原始输出保存在 `.work/c007/T7-test.log`。
- C007 T7 首轮新增测试因 asyncpg JSONB 返回字符串导致 1 项失败，按现有测试模式解码为 dict 后重跑通过；正式 PNG 事务测试使用隔离 DATA_DIR 验证 rename/trash。
- C007 T8 在 `ai_drama_studio_c007_t8_20260828` 完成迁移；定向 13+1 passed，完整 pytest 94 passed，原始输出保存在 `.work/c007/T8-test.log`。
- C007 T8 验证时 `.env` 数据库有运行中的 uvicorn worker，改用隔离数据库后任务系统资源顺序测试稳定通过。
- C007 T9 在 `ai_drama_studio_c007_t9_20260828` 完成迁移；定向 5 passed，完整 pytest 99 passed，原始输出保存在 `.work/c007/T9-test.log`。
- C007 T10 在 `ai_drama_studio_c007_t10_20260828` 完成迁移；定向 1 passed，完整 pytest 100 passed，原始输出保存在 `.work/c007/T10-test.log`。
- C007 T11 生产 build 成功，隔离数据库完整 pytest 100 passed；真实 `/settings` 走查覆盖 healthy、ComfyUI 停止后的 unhealthy/message、后端停止后的 API 错误、设置编辑保留与恢复刷新；原始 build/pytest 输出在 `.work/c007/T11-test.log`。
- C007 T12 2026-08-30：设置 API 写入并逐字读回人物四视图模板；真实资产 `林晚` 任务 `#233/#234` 均完成，生成版本 29/30 产生不同 seed，30 current，29 删除后进入 `backend/data/trash/projects/4/assets/48/29.png`；debug false/true 字段实测符合约定；T12 build/pytest 输出见 `.work/c007/T12-test.log`。
- C007 T13 2026-08-30：设置 API 写入并逐字读回人物/场景单一 `zimage` 正式模板；当前正文长度 2770，唯一占位符顺序为 `asset,style,user_note`，包含 `character`/`scene`、`1344×1024` 和封闭 JSON `prompt` 合同；复核输出见 `.work/c007/T13-test.log`。
- C007 T14 2026-08-30：真实 ComfyUI 使用 127.0.0.1:8188 与 workflow hash e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa；health 返回 vLLM/Comfy healthy、binding valid。
- C007 T14：林晚资产修订 4 生成图片 31/32/33；相同意见第二次任务 248 命中已缓存 prompt，描述修改后任务 249 生成新 prompt；三张 PNG 均为 1344×1024。
- C007 T14：场景资产 279 的任务 250 完成，图片 34 自动 current，PNG 为 1344×1024；debug false 不返回 built_prompt/input_snapshot，debug true 返回。
- C007 T14 最终隔离库 `ai_drama_studio_c007_t14_final_20260830` 定向测试 68 passed、完整 pytest 100 passed，frontend build 与 Alembic current/check 均成功；原始输出见 `.work/c007/T14-test.log`。
- 2026-08-30 C007 Sol 审查修复使用隔离库 `ai_drama_studio_c007_review_repair_20260830`；`alembic current` 为 `6b8e3f0a1d24 (head)`，`alembic check` 为 `No new upgrade operations detected.`。
- 2026-08-30 C007 审查新增回归定向为 `9 passed in 4.21s`，完整 C007 定向为 `77 passed in 14.96s`，完整 backend 为 `109 passed in 68.02s`；原始输出见 `.work/c007/C007-sol-review-*.log`。
- 2026-08-30 最新 SettingsPage 清理诊断旧状态后 `npm run build` 通过：55 modules、JS `215.70 kB`、CSS `7.90 kB`、`426ms`。
- 2026-08-30 资产页/设置页人工走查时 vLLM 保持停止，页面显示 vLLM unhealthy、ComfyUI healthy、Z-Image binding valid；设置页刷新期间旧 health 不显示。
- 2026-08-30 按既有 vLLM 启动命令重启 `/mnt/d/llm_models/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit`；8001 `/health` 实测 HTTP 200、空 body，原始输出见 `.work/c007/Sol-vllm-restart-20260830-*.log`。
- 2026-08-30 隔离库 `ai_drama_studio_c007_seed_20260830` 上公开 seed API 用例 `1 passed`，63-bit seed 原样返回十进制字符串；内部 seed 整数用例未改且通过。
- 2026-08-30 全量 backend 为 `109 passed, 1 failed`；唯一失败是 `test_health_timeout_is_unhealthy_without_gpu_mutation` 实际访问已启动的 8001 并收到 healthy，原始输出见 `.work/c007/C007-seed-contract-full-backend.log`。
- 2026-08-31 C007 final repair：生产任务查询为空，Comfy `http://127.0.0.1:8188/queue` 实测 `queue_running=0`、`queue_pending=0`；原始前置检查见 `.work/c007/final-repair-vllm-preconditions.log`。
- 2026-08-31 按既有 vLLM 命令仅将 `gpu-memory-utilization` 改为 `0.91` 启动；因 `Free memory ... 21.31/23.99 GiB` 小于所需 `21.83 GiB` 失败，原始日志见 `.work/c007/final-repair-vllm-091.*.log`。
- 2026-08-31 vLLM 进程最终未运行，`8001/health` 无响应；未执行 sleep/wake/chat，未降低 `max-model-len` 或继续猜参数。
- 2026-08-31 第二次按既有命令仅将 `gpu-memory-utilization` 设为 `0.91` 成功启动 vLLM；保留 `max-model-len=16384`、`--enable-sleep-mode`、原模型/served name/generation-config 与 `VLLM_USE_FLASHINFER_SAMPLER=0`。
- 2026-08-31 真实 vLLM `/health` 为 HTTP 200 空 body；`/sleep?level=1` 与 `/wake_up` 为 200，`/is_sleeping` 依次为 true/false。
- 2026-08-31 真实最小 structured chat 为 HTTP 200，封闭 JSON 输出 `{"answer":"ok"}`；后端 `/api/system/health` 的 vLLM 为 `healthy/null`。
- 2026-08-31 最终 vLLM `/is_sleeping` 为 `{"is_sleeping":true}`，进程保持运行；Comfy `/queue` 最终为 200 且 running/pending 均为空。
- 2026-08-31 T24 按 `F:\ComfyUI\venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188` 启动 ComfyUI；本轮未提交 workflow，最终 `/queue` 仍为 200 且 running/pending 均为空。
- 2026-08-31 C008 T13 使用隔离库 `ai_drama_studio_c008_t0_20260831`；`alembic current` 为 `6b8e3f0a1d24 (head)`，`alembic check` 为 `No new upgrade operations detected.`。
- 2026-08-31 C008 T13 定向套件 `39 passed in 60.53s`，完整 backend `156 passed in 140.17s`；原始输出保存在 `.work/c008/T13-test.log`。
- 2026-08-31 C008 T13 `npm run build` 成功，Vite 报告 `55 modules transformed`、`built in 448ms`；migration/frontend working diff 为空。
- 2026-08-31 C008 T13 首次定向命令因 PowerShell `.Substring(14)` 生成非法 DSN，改为 `.Substring(13)` 后同一隔离库定向通过；失败与修正输出均保留在 `.work/c008/T13-test.log`。
- 2026-08-31 C008 T14-T23 使用全新隔离库 `ai_drama_studio_c008_final_20260831`；Alembic current 为 `6b8e3f0a1d24 (head)`，check 为 `No new upgrade operations detected.`。
- 2026-08-31 C008 复审定向套件 `51 passed`、完整 backend `168 passed`；原始输出见 `.work/c008/T23-targeted.log` 与 `.work/c008/T23-full-pytest.log`。
- 2026-08-31 C008 T21 新测试首次结束清理触发 `asset_images_asset_id_fkey`；补充先删图片再删资产后重跑为 `1 passed`，两次原始输出均保留在 `.work/c008/T21-test.log`。
- 2026-08-31 C008 `npm run build` 成功，Vite 报告 `55 modules transformed`；迁移与前端 working diff 均为空，原始输出见 `.work/c008/T23-frontend-build.log`。
- 2026-08-31 C008 T25 使用全新隔离库 `ai_drama_studio_c008_t25_20260831_01`；Alembic upgrade/current/check 均成功，current 为 `6b8e3f0a1d24 (head)`。
- 2026-08-31 C008 T25 定向错误合同集 `7 passed`，完整 backend `169 passed`；原始输出见 `.work/c008/T25-targeted-pytest.log` 与 `.work/c008/T25-full-pytest.log`。
- 2026-08-31 C008 T25 `npm run build` 成功，Vite 报告 `55 modules transformed`；backend/app、migration、frontend 相对 `1e21f55` 的 diff 均为空。
- 2026-08-31 C008 T25 测试 diff 相对 `1e21f55` 只有 `backend/tests/api/test_c008_review_error_codes.py` 为 `A`，无 `M`/`D`。
- 2026-09-01 C009 T17 真实验收使用全新库 `ai_drama_studio_c009_t17_20260901_02`；生产 Uvicorn/vLLM/Comfy 地址为 `127.0.0.1:8000/8001/8188`，health 返回双 workflow hash valid。
- 2026-09-01 C009 T17 给定 MiniMax 模板正式 PATCH/GET 逐字相等；真实 1-reference 与 2-reference 任务均产生 `requested_duration=5`、`actual_duration=5.166667` 的可下载 MP4。
- 2026-09-01 C009 T17 无 current 图片的活资产经正式 API 产生 R10 immediate failed task：未 claim、无视频/缓存；结束时 vLLM sleeping=true、Comfy queue running/pending 均为空。
- 2026-09-01 C009 T18 新库 `ai_drama_studio_c009_t18_20260901_01` 的 Alembic current 为 `6b8e3f0a1d24 (head)`、check 无新操作，完整 pytest 为 `323 passed`。
- 2026-09-01 C009 T18 `npm --prefix frontend run build` 实测通过；C009 本轮未交付前端 UI。
- 2026-09-02 C009 T20 设置页真实走查读取 `workflow_bindings.status=valid`，并逐字展示 `zimage=e9790bece3462691ebaf63d849bf1940beec62f9149fb6d475be859c47e41eaa` 与 `minimaxh3=bfa1fbfffecf1665309b01234621bc32cd29f86fd3dfa40f12605cbf3eb3f780`；同次 health 观测到 vLLM/Comfy 不可达时分别返回 `unhealthy` 与连接失败 message，原始证据见 `.work/c009/T20-health-response.log`、`.work/c009/T20-settings-browser.log`。
- 2026-09-02 C009 T26 rerun-04 使用全新库 `ai_drama_studio_c009_t26_20260902_05`、隔离 `DATA_DIR=D:\ai_drama_studio\.work\c009\T26-rerun-04-data`、request_id `t26-rerun-04-20260902`；Comfy `127.0.0.1:8188` 的 PID `32056` 自 `2026-09-02T17:48:56.7702477+08:00` 存活。只有在 `/queue` 的 `queue_running` 精确唯一匹配 payload `prompt_id` 后才直接 `/interrupt`，该请求 HTTP 200 一次；Task 最终 failed，原因包含 `RuntimeError: Comfy execution_interrupted without cancellation intent`，无 ClipVideo/cache/formal/temp 产物，应用 `/free` HTTP 200 一次，vLLM sleeping=true，最终 Comfy queue 为空。原始证据见 `.work/c009/T26-rerun-04-preflight.log`、`.work/c009/T26-rerun-04-openapi-precheck.log`、`.work/c009/T26-rerun-04-poll-01.log`、`.work/c009/T26-rerun-04-terminal.log`、`.work/c009/T26-rerun-04-cleanup.log`。
- 2026-09-02 C009 T27 使用全新库 `ai_drama_studio_c009_t27_20260902_01` 与显式 `DATABASE_URL`、隔离 `DATA_DIR`；Alembic current 为 `6b8e3f0a1d24 (head)`、check 无新操作，完整 backend 为 `345 passed in 237.72s (0:03:57)`，frontend build 为 55 modules、`built in 482ms`。这些 T27 Alembic/pytest/build 日志属于历史 wrapper，缺少本轮要求的原生 stdout/stderr，不作为最终隔离通过证据；最终证据由 T29 日志取代。隔离测试前停止本轮 Uvicorn 以避免 advisory lock 干扰，用户 Comfy 进程保持运行；历史证据见 `.work/c009/T27-database-create.log`、`.work/c009/T27-alembic-upgrade.log`、`.work/c009/T27-alembic-current.log`、`.work/c009/T27-alembic-check.log`、`.work/c009/T27-full-pytest.log`、`.work/c009/T27-frontend-build.log`。
- 2026-09-03 C009 T28 使用全新库 `ai_drama_studio_c009_t28_20260903_01` 显式执行 Alembic；参考媒体回归定向为 `22 passed in 5.64s`，完整 backend 为 `346 passed in 257.40s (0:04:17)`，均以 `T28-*` Tee 原生输出并追加 `EXIT_CODE=0`；T28 独立提交为 `799b7d2`。测试使用真实临时文件、Windows `spawn` writer、事件屏障与原子替换，证明同一份已读 bytes 同时决定 hash 与上传内容。
- 2026-09-03 C009 T29 使用全新库 `ai_drama_studio_c009_t29_20260903_01` 并显式导出 `DATABASE_URL`；Alembic current 为唯一 `6b8e3f0a1d24 (head)`，check 为 `No new upgrade operations detected.`，完整 backend 为 `346 passed in 238.78s (0:03:58)`，frontend build 为 55 modules、`built in 434ms`。最终原生证据见 `.work/c009/T29-alembic-upgrade.log`、`T29-alembic-current.log`、`T29-alembic-check.log`、`T29-full-pytest.log`、`T29-frontend-build.log`、`T29-scope.log`、`T29-migration-diff.log`；migration diff 为空，所有日志含真实 `EXIT_CODE`。
- 2026-09-03 PowerShell 将 `(Get-Content .work/c009/<sha-file>)..HEAD` 解析为范围表达式，传给 Git 会输出 usage；跨 commit 范围审计应先执行 `$baseline = (Get-Content -Raw .work/c009/<sha-file>).Trim()`，再使用 `"$baseline..HEAD"` 作为单一参数，并立即检查 `$LASTEXITCODE`。
- 2026-09-03 只读核对新库 `ai_drama_studio_c010_t12_rerun_20260903_170851`：`prompt_templates` 精确有 4 行；`script2assets/script2shots/zimage` 仍为 migration 占位，`minimaxh3` 为经设置 API 安装的正式正文（PostgreSQL `length=7340`）。当前 `GET http://127.0.0.1:8000/api/prompt-templates` 返回同样四项，故“正式内容未随新库出现”是运行配置未部署，不是缺表或缺 seed 行。
- 2026-09-03 四份正式模板均已有前序 change 来源：`script2assets` 以 C005 spec §5.1 冻结正文为准，不能采用旧验收库后来被改为仅三个占位符的 40 字符值；`script2shots` 的 C006 正式正文为 1181 字符；C007 单一 `zimage` 正文为 2770 字符；C009/C010 使用的流水线适配版 `minimaxh3` 正文为 7340 个 PostgreSQL 字符。需求方裁决 C012 在全新生产等价库通过设置 API 自动部署四份、安装后和后端重启后逐字回读，并由 M6 全链路实际消费；不修改 schema/migration。
- 2026-09-04 C010 T12 使用全新库 `ai_drama_studio_c010_t12_rerun_20260904_140538` 与隔离 `DATA_DIR`；Task #2/#4 为 done，Task #3 的 Comfy 故障与重启后空 history 证据保留，未重试旧任务。
- 2026-09-04 C010 T12 在确认 Task #4 running、payload `comfy_prompt_id` 与唯一 `queue_running` prompt 精确一致后，经正式 Shot PATCH 将 Shot #1 revision 1→2/status=changed；任务完成后新 take 保存且 Clip freshness=stale。
- 2026-09-04 C010 T12 终态观测 Comfy `/queue` running/pending 均为空、vLLM `is_sleeping=true`、健康 binding valid；正式临时目录不存在且文件计数为 0。
- 2026-09-04 C010 T13 最终库 `ai_drama_studio_c010_final_20260904_150611` 迁移到 `6b8e3f0a1d24 (head)`，backend `346 passed`、frontend `39 passed`、build 成功，`alembic check` 无新操作。
- 2026-09-04 C010 T13 首次 workflow scope 检查因相邻 Python 字符串的源码字面量断言失败，原始 `.work/c010/T13-workflow-scope.log` 保留；修正验收脚本后 `T13-workflow-scope-rerun.log` 三项精确 PASS。
- 2026-09-07 C011 T18 生产 TasksPage 已改由 `frontend/src/features/tasks/taskObservation.ts` 协调 REST/WS；真实挂载测试使用 jsdom、fetch 账本和 FakeSocket，定向 5 passed。
- 2026-09-07 C011 T18 G 前端 17 files/103 tests、build 64 modules、Alembic upgrade/current/check 与完整 backend `347 passed in 142.80s` 均 exit 0；证据见 `.work/c011/T18-taskobservation20260907_1840-test.log`。
- 2026-09-07 C011 T19 定向 `taskBoundary.test.tsx` 修正测试文本匹配与未使用 import 后为 14 passed；首轮 2 个断言失败及 G 首次 `TS6196` 失败证据均保留在 `.work/c011/`。
- 2026-09-07 C011 T19 G 前端 18 files/117 tests、build 64 modules、Alembic upgrade/current/check 与完整 backend `347 passed in 138.10s` 均 exit 0；证据见 `.work/c011/T19-taskboundary20260907_1930-test.log`。
- 2026-09-07 C011 T20 新增 `cancelTask` 无 body POST 与 TasksPage 取消状态；挂载测试 3 passed，实际账本确认 queued/running 状态与 detail/list 回读。
- 2026-09-07 C011 T20 G 前端 19 files/120 tests、build 64 modules、Alembic upgrade/current/check 与完整 backend `347 passed in 139.74s` 均 exit 0；证据见 `.work/c011/T20-taskcancel20260907_2030-test.log`。
- 2026-09-07 C011 T21 挂载竞态测试 6 passed，覆盖终态迟到响应、409/404、网络未知结果及筛选/展开/卸载 identity；证据见 `.work/c011/T21-taskcancelraces-targeted-20260907_2110.log`。
- 2026-09-07 C011 T21 G 前端 20 files/126 tests、build 64 modules、Alembic upgrade/current/check 与完整 backend `347 passed in 142.92s` 均 exit 0；证据见 `.work/c011/T21-taskcancelraces20260907_2120-test.log`。
- 2026-09-07 C011 T22 定向新库 `ai_drama_studio_c011_t22_target_20260907_181653_4908` 仅执行 Alembic upgrade 后运行独立跨进程取消观察测试，`1 passed in 2.99s`、退出码 0；测试进程已退出，证据见 `.work/c011/T22-targeted-20260907_181653-4908.log`。
- 2026-09-07 C011 T22 G 使用新的 target/full PostgreSQL 与独立 DATA_DIR；target `1 passed`，前端 `126 passed`/build `64 modules`，full Alembic upgrade/current/check、完整 backend `348 passed in 144.01s`、git diff check 均 exit 0；证据见 `.work/c011/T22-t22crossprocess20260907_1820-test.log`。
- 2026-09-07 C011 T23 浏览器批次使用 `http://127.0.0.1:5194`→T04 `127.0.0.1:53002`、数据库 `ai_drama_studio_c011_t23_browser_20260907_183050_42501`；真实 TasksPage 观察 queued/running 取消、过滤、详情、WS 重连和来源回跳。
- 2026-09-07 C011 T23 独立只读 DB 查询确认 #122 done、#123/#125/#126 canceled、#124 failed，#125 的 `cancel_requested_at` 与进度 `0.5` 与浏览器一致；53002/5194 停止后无监听。
- 2026-09-07 C011 T23 G 前端 `126 passed`、build `64 modules`、Alembic upgrade/current/check、完整 backend `348 passed in 139.80s`、git diff check 均 exit 0；原始证据见 `.work/c011/T23-t23browser20260907_183050_42501-test.log`。
- 2026-09-07 C011 T23 asyncpg 读取不能直接接受 SQLAlchemy `postgresql+asyncpg` DSN；改用 `postgresql://` 后只读查询 exit 0，失败 traceback 与修正输出均保留。
- 2026-09-08 C011 T24 使用普通 fixture 批次 `T03-rerun-20260908_110151-34220`、后端 `53003`、前端 `5195`；四视口及默认高密度浏览器视口走查记录在 `.work/c011/T24-browser-acceptance-20260908_110151.log`，53003/5195 走查后无监听。
- 2026-09-08 C011 T24 定向 Director 为 12 files/66 tests passed；G 使用新库 `ai_drama_studio_c011_t24_full_20260908_112524_32664` 与独立 DATA_DIR，完整 pytest `348 passed in 143.90s`，前端全量 `126 passed`、build 64 modules、Alembic current/check、git diff check 均 exit 0。
- 2026-09-08 C011 T24裁决更正：上述普通走查与G仅为部分证据，原生桌面200%、动态reduced-motion及四类生成按钮到受控handler尚未齐备，T24未完成；`68ca536c169491b2eb030f8d83a265dfd7fe78aa` 的完成标题不替代验收。`.work/c011/T24-controlled-generation-failure-20260908.log` 记录generate-assets在迁移占位模板变量校验处409、无task_id/barrier；T24A按spec §7.4准备人工模板前置，正式模板部署仍归C012。本轮只读确认@oai/sky可加载并列出Chrome/Edge窗口，未执行项目缩放/媒体偏好补验。
- 2026-09-08 C011 T24B 静态审计与新G：`styles.css` 亮色令牌/组件消费/焦点/reduced-motion检查通过；修正DEBUG预格式文本的主题前景/背景后，前端126 passed、完整pytest 348 passed，Alembic与git diff check均exit=0，证据见`.work/c011/T24B-static-audit-20260908_2.log`与`.work/c011/T24B-t24bstatic20260908-test.log`。
- 2026-09-08 C011 T24C 自动测试/G已通过；正式浏览器批次53103/5203启动后，CUA仅列出内置IAB，Chrome/Edge均返回不可用，未执行视觉检查；进程清理后归属进程数为0，失败记录见`.work/c011/T24C-browser-control-failure-20260908_130719.log`。
- 2026-09-08 C011 T24C 新普通批次后端53104/前端5204、数据库`ai_drama_studio_c011_t03_ui_20260908_110151_34220`；IAB正式按钮双主题、同源刷新/新标签恢复、320px矩阵/键盘/状态保持及实际截图/计算样式记录于`.work/c011/T24C-browser-acceptance-20260908_131806.log`；IAB未提供原生200%/动态reduced-motion/localStorage直接读数，Chrome/Edge失败证据保留。
- 2026-09-08 C011 T24D 新普通 fixture 后端8014、隔离 Vite 5183、数据库`ai_drama_studio_c011_t03_ui_20260908_141708_30844`；fixture prepare/verify 与迁移退出码均为0，vLLM health 为 unhealthy、ComfyUI healthy。
- 2026-09-08 C011 T24D 首次 BackNavigation 构建因联合类型收窄失败，失败日志保留；修正为 `props.to !== undefined` 后 build 与 `returnLocation.test.ts` 各退出0，未修改既有测试。
- 2026-09-08 C011 T24D G 前端22 files/136 tests、build67 modules、Alembic upgrade/current/check、完整 backend `348 passed in 143.96s`、git diff check 均退出0；IAB 动态非法 Router state 因公开 evaluate 不暴露 history 未验证，证据见`.work/c011/T24D-browser-acceptance-20260908_142513.log`。
- 2026-09-08 C011 T24E：`.form-grid` 文本输入选择器与三类勾选行修正后 build/G 均 exit 0；新普通批次 8015/5184 的双主题四视口浏览器采集记录18×18、8px、首行中心差0px、正式GET回读与清理无监听，详见`.work/c011/T24E-browser-acceptance-20260908_145851.log`。
- 2026-09-08 C011 T24F：新增共同轨道宽度纯函数及三轨共同宽度接线，定向6/6、director72/72、前端全量142/142、build、Alembic与完整pytest348均exit0；修正前IAB首列191.992px的浮点舍入证据保留，修正后默认1280×720 IAB最短列192.039px、三轨边界差0、根无溢出，详见`.work/c011/T24F-browser-acceptance-20260908_1715.log`。
- 2026-09-08 C011 T24F：当前公开CUA只返回IAB且`iab.capabilities={}`，无Chrome/Edge或viewport/native-zoom/reduced-motion入口；四视口、原生200%和动态reduced-motion未验证，T24F及其后T24/T25未勾选/未提交。
- 2026-09-08 C011 T24F视口补验：`browser.capabilities.list/get("viewport")`提供正式覆盖；新批次后端52426、前端52427、tab38完成320×800/390×844/768×1024/1440×900双主题，DPR均1，最短列192.039px、三轨边界/宽度差0、gap8px，局部滚动、键盘选中镜头18与主题切换保持；已调用`viewport.reset()`并清理归属进程，原生200%仍未验证。
- 2026-09-08 C011 T24F槽位边界修正：IAB 320×800初始根`scrollWidth=360/clientWidth=305`，修正`.director-slot-row`子项、上传框/file input及图片宽度后双主题根均`305/305`，390/768/1440也无根溢出；新G前端142、完整pytest348与Alembic均exit 0，证据见`.work/c011/T24F-slot-overflow-fix-browser-20260908.log`和`.work/c011/T24F-t24fslotfix20260908-test.log`。
- 2026-09-08 C011 T24F：调用方确认原生桌面200%人工审查通过，确认记录见`.work/c011/T24F-native200-user-confirmation-20260908.log`；该确认不扩展为T24全页或动态reduced-motion通过。
- 2026-09-08 C011 T24A：受控服务使用新库`ai_drama_studio_c011_t24a_controlled_20260908_180251`、端口52428、独立DATA_DIR且启动前`DEBUG_PROMPTS=true`；fixture prepare/verify、正式四次模板PATCH 200、集合GET逐字回读、独立current_database与DEBUG字段检查均exit 0。
- 2026-09-08 C011 T24A：Alembic必须在`backend` CWD运行；仓库根目录调用缺少script_location，重复拼接backend路径也失败；两次命令构造/证据查询失败均保留在`.work/c011/`，未改生产代码、迁移或重发PATCH。
- 2026-09-08 C011 T24A G：`T24A-t24aconfig20260908-test.log`记录前端142 passed、build 68 modules、全新full迁移库upgrade/current/check exit 0、完整backend `348 passed in 236.78s`、diff check exit 0。
- 2026-09-09 C011 T24最终普通IAB矩阵实际覆盖8类页面×2主题×4 CSS视口共64格；根/body无水平溢出，原生桌面200%与动态reduced-motion仍未验证，原始证据见`.work/c011/T24-final-browser-matrix-20260908.log`。
- 2026-09-09 C011 T24 reduced-motion源码审计确认`styles.css:1944`的reduce规则覆盖现有悬浮位移、缩短transition并限制animation iteration；动态媒体切换未验证，证据见`.work/c011/T24-reduced-motion-static-audit-20260909.log`。
- 2026-09-09 C011 T25基线审计相对`1ef70e5d5fad245d6e38e1472eaa16ffb523aa59`的`backend/app`、`backend/alembic`、`backend/workflows`为空，C011追溯行17行且无待填项，证据见`.work/c011/T25-scope-audit-20260909.log`。
- 2026-09-09 C011 T25 G使用新库`ai_drama_studio_c011_t25_full_20260909_102444_34840`，前端142 passed、build 68 modules、完整backend `348 passed in 237.54s`、Alembic与git diff check均exit 0，证据见`.work/c011/T25-t25scopefinal20260909_1015-test.log`。
- 2026-09-09 C011 T26 G使用新库`ai_drama_studio_c011_t26_full_20260909_103418_6744`，前端142 passed、build 68 modules、完整backend `348 passed in 235.98s`、Alembic与git diff check均exit 0，证据见`.work/c011/T26-t26notesfinal20260909_1100-test.log`。
- 2026-09-09 C011 T23 当前IAB批次使用后端53021、前端52021、数据库`ai_drama_studio_c011_probe_20260909_150722_36700`，初始独立读取143条混合任务，证据见`.work/c011/T23-current-browser-20260909.log`。
- 2026-09-09 C011 T23 官方入队#144/#145后真实页面取消与屏障放行终态均与独立DB读回一致；服务显式shutdown退出码0，四个验收端口无监听，证据见`T23-current-browser-20260909.log`与`T23-cleanup-20260909.log`。
- 2026-09-09 C011 T24 当前主题定向套件13 tests、Director套件72 tests均exit 0，reduced-motion源码审计记录动态媒体响应未验证，证据见`.work/c011/T24-final-revalidation-20260909.log`与`T24-reduced-motion-static-audit-20260909.log`。
- 2026-09-09 C011 T25 基线审计确认`backend/app`、`backend/alembic`、`backend/workflows`相对`1ef70e5d5fad245d6e38e1472eaa16ffb523aa59`无diff，AC合同31条、C011主追溯17行，证据见`.work/c011/T25-final-scope-audit-20260909.log`。
- 2026-09-10 C011 T45：`taskObservation.ts`在连接/过滤重建时将旧ready详情置为idle；独立回归覆盖断线、过滤、取消确认目标与当前展开任务，定向3 tests/3 passed，证据见`.work/c011/T45-targeted-test-final-20260910.log`。
- 2026-09-10 C011 T45：前端全量34 files/174 tests、build 68 modules、git diff check均exit 0；修复前3项B16断言失败保留于`.work/c011/T45-pre-fix-red-20260910.log`。
- 2026-09-10 C011 T45：Astra七发探针、runtime/template两批及closed-detail批次均RESULT PASS/exit 0，精确文件名见`.work/c011/probe-runtime-20260910_102734_25900.log`、`.work/c011/probe-template-contract-20260910_102734_20260.log`与对应probe日志。
- 2026-09-10 C011 T23 B16：同一IAB tab与Vite前端保持在线，隔离数据库`ai_drama_studio_c011_t23_t45_20260910_103500`的任务127取消/重连详情经REST、WS、独立只读DB逐字段一致；清理后监听端口关闭、验收进程消失。
- 2026-09-10 C011 T24：主题3 files/13 tests与Director 13 files/72 tests均exit 0；64格双主题四正式视口、四类受控按钮与异常矩阵有日志，原生全页200%和动态reduced-motion仍未动态验证。
- 2026-09-10 C011 T25：基线审计确认`backend/app`、`backend/alembic`、`backend/workflows`无diff，既有测试仅一处AGENTS授权`do_POST`修改，C011主追溯17行且无待填标记。
- 2026-09-10 C011最终G：权威日志`.work/c011/T39-astrafinal20260909loop-test.log`使用库`ai_drama_studio_c011_t39_full_20260909_183354_38988`记录完整pytest `348 passed in 239.87s`，迁移三步、前端/build与diff check均exit 0。
- 2026-09-10 C011归档：最终审查基线`2acf32a`之后实现、测试和依赖无变化，无需重复完整复审。spec/tasks及最终审查、完成报告保存在`openspec/archive/c011/`；来源返回合同已采纳为DECISIONS D-015。历史报告中的“候选未采纳”为当时状态；原始验收输出继续保留于`.work/c011/`。
- 2026-09-10 C011清理未执行：针对`.work/c011/`临时媒体、缓存、checkbox补丁的删除命令被自动审批审查以`blocked by policy`拒绝；未绕过、未删除文件。永久回归测试的删除范围仍待需求方明确，当前全部保留。
- 2026-09-10 C011清理范围已确认：需求方明确保留正式回归测试、只删除临时文件。已核对拟清理的`.work/c011/data/`、`__pycache__/`、T06–T11 checkbox补丁和5张ui-fixture图片共656个文件（6061648字节），均在C011工作目录内且无reparse point、无对应活动验收进程；按明确路径提交的删除命令仍被安全层以`blocked by policy`拒绝，未执行删除。原始日志、验收装置、正式测试和其他change文件全部保留。
- 2026-09-10 C012开工准备：C011已归档，当前归档提交`7597d47`；尚无C012 proposal/spec/tasks。先按PRD §11 M6、§12与D-014规划四份已批准模板的正式API部署/安装后及重启后逐字回读，再规划真实一集链路、§3.3全级联矩阵、§6.1恢复、trash清理及§3.2竞态。`docs/前置依赖清单.md`仍有C006时期“zimage/minimaxh3待提供”等旧记录，与当前PRD §7/§12及D-014的已确认来源不符；后续需据真实来源更新，不能把旧表当成需用户重新创作模板的依据，也不能把已确认内容当成当前服务已验证在线。
- 2026-09-10 M6首轮已由需求方确认采用“宿舍＋球馆”，完整该范围走资产/分镜生成，再分别选择连续同场景分镜生成两个片段：①芳嘉蔓进门催促，乔彦茜抬眼回应后继续吃饭；②芳嘉蔓指向出场球员，乔彦茜从平静变为僵住。童年回忆段不纳入首轮；真人物/场景/动作视频验收属于C012，C011受控结果不能替代。当前尚未核验C012真实外部服务、创建新验收库或触发GPU生成。
- 2026-09-10 C012 T07 在 T01 隔离库`ai_drama_studio_c012_t01_regression_20260910`与`D:\\ai_drama_studio\\.work\\c012\\t01-regression-data`运行 L4 `1 passed`、C009 入队锁`13 passed`、`locks --case L4`子进程退出0；L4覆盖create冲突、slot变化、delete媒体赢家双向交错，原始证据见`.work/c012/T07-L4-final3.stdout.log`、`T07-C009-final.stdout.log`、`locks-acceptance.json`。
- 2026-09-10 C012 T08 在同一 T01 隔离库运行指定后端定向回归`23 passed in 27.80s`、退出码0；`locks --case all`五格子进程均退出0且未超时/占位，生产分镜覆盖失败与成功媒体通路使用隔离 DATA_DIR，原始证据见`.work/c012/T08-targeted-final.stdout.log`、`.work/c012/T08-acceptance-all.stdout.log`、`.work/c012/locks-acceptance.json`。
- 2026-09-10 C012 T09 在独立临时数据库覆盖空库、合法旧库、名称碰撞/空白预检及down/up；迁移回归`1 passed`，migration acceptance与Alembic upgrade/current/check均exit 0，T01隔离库已升级至`c012_asset_name_unique`，原始证据见`.work/c012/T09-test.log`、`.work/c012/T09-acceptance.stdout.log`、`.work/c012/T09-alembic.log`。
- 2026-09-10 C012 T10 在 T01 隔离库运行资产创建/改名合同回归`1 passed`、退出码0；精确409、跨项目/大小写/内部空格、strip/no-op及空白/NUL/超长422与失败改名下游无损均有断言，证据见`.work/c012/T10-test.log`。
- 2026-09-10 C012 T11 在 T01 隔离库运行 gen_assets 新旧回归`11 passed`、退出码0；一次生产handler mock调用覆盖合法existing_id、候选去重/warning、跨类型整批回滚及生成名称边界，证据见`.work/c012/T11-test.log`。
- 2026-09-10 C012 T12 在 T01 隔离库运行指定 B `4 passed`、退出码0；两个正式 API 竞争及手动/生成竞争均由独立 PostgreSQL 连接观察到 `Lock/transactionid` 等待，取消分支保留原 marker 且零本批资产，done 分支提交两项新资产与 marker，证据见`.work/c012/T12-test.log`。
- 2026-09-10 C012 T12 R `python -X utf8 .work/c012/acceptance.py names` 退出码0；自检记录实际库与 T01 DATA_DIR，子进程 `3 passed`，测试后独立数据库连接仍可用，证据见`.work/c012/T12-acceptance.log`与`.work/c012/names-acceptance.json`。
- 2026-09-10 C012 T13 EventBus 定向回归`1 passed`、退出码0；慢订阅在第257条溢出并通知/注销，健康订阅持续消费257条且顺序与五字段内容保持，重复unsubscribe及新订阅无历史回放，证据见`.work/c012/T13-test.log`。
- 2026-09-10 C012 T14 定向 B `6 passed in 0.54s`、退出码0；受控 WS 覆盖溢出/发送超时/发送异常的1013关闭和子任务清理，双真实网络连接各收到取消五字段事件，独立任务仍`running`且`error_msg=null`；R `ws`退出码0，证据见`.work/c012/T14-test.log`、`.work/c012/T14-acceptance.log`和`.work/c012/ws-acceptance.json`。
- 2026-09-10 C012 T15 前端单文件1 test、任务目录60 tests、build 68 modules均退出码0；T02受控后端停止/恢复期间真实页面从`running/0.4`重建为`done/1`，后端info日志为WS接受→列表GET→详情GET且无cancel/generate-video POST，fixture与监听清理完成，证据见`.work/c012/T15-browser-acceptance.md`。
- 2026-09-10 C012 T16 G1 在新库`ai_drama_studio_c012_g1_20260910`与`D:\ai_drama_studio\.work\c012\t16-g1-data`完成迁移、后端`369 passed`、前端`35 files/175 tests`、build`68 modules`及diff check，全部exit 0；原始日志见`.work/c012/T16-*.log`。
- 2026-09-10 C012 T17 四个模板文件按批准源恢复并逐字核验：script2assets 1253、script2shots 1181、zimage 2770、minimaxh3 7340 字符；UTF-8/LF，前三者无末尾换行、MiniMax 保留一个；迁移/workflow diff exit 0，证据见`.work/c012/T17-source-check-02.log`。
- 2026-09-10 C012 T18 CLI 定向回归最终`13 passed in 18.16s`、exit 0；覆盖输入前置校验、install 顺序/停止/部分提交、verify 零 PATCH、真实后端/CLI 进程与独立 DB 回读，首次装置连接上下文错误保留在`.work/c012/T18-test.log`，修正结果见`.work/c012/T18-test-02.log`。
- 2026-09-10 C012 T19：`backend/deployment/m6-script.txt`按`openspec/changes/c012/spec.md`§6.1逐字保存，999字符/2883 UTF-8 bytes、无末尾换行，`SCRIPT_CHAR_LIMIT=2000`；`verify-inputs`与同一驱动`selfcheck`最终均exit 0，首次脚本换行错误保留于`.work/c012/T19-verify-inputs.log`，最终输出见`.work/c012/T19-verify-inputs-final.log`、`.work/c012/T19-selfcheck-final.log`。
- 2026-09-10 C012 T20：vLLM缺失时按既有启动命令以`gpu-memory-utilization=0.91`启动，模型加载后8001监听；真实preflight最终记录 DB`ai_drama_studio_c012_t01_regression_20260910`、DATA_DIR`D:\ai_drama_studio\.work\c012\t01-regression-data`、vLLM模型/health、Comfy object_info绑定LoRA与空queue、sleep/wake最终sleeping=true；首次10秒超时失败与修正后通过输出分别见`.work/c012/T20-preflight.log`、`.work/c012/T20-preflight-02.log`。
- 2026-09-10 C012 T21：新库`ai_drama_studio_c012_m6_20260910`仅经Alembic到`c012_asset_name_unique`，DATA_DIR为`D:\ai_drama_studio\.work\c012\t21-m6-data`；正式CLI安装四模板，后端重启后verify仍四key通过，独立API/asyncpg回读无占位且逐字等于批准文件，重启日志prompt-template PATCH计数为0；证据见`.work/c012/T21-*.log`。
- 2026-09-10 C012 T23：project 2/episode 2 经正式UI保存脚本并生成四项核心资产；task #5 `gen_assets` 与 task #6–#9 `gen_asset_image` 均 `done`，四项 PNG 均 `source=generated` 且 current，未手工补资产/上传媒体。
- 2026-09-10 C012 T23：`preflight --real`、`observe --real` 均 exit 0；现场回读库`ai_drama_studio_c012_m6_20260910`、DATA_DIR`D:\ai_drama_studio\.work\c012\t21-m6-data`、vLLM/Comfy健康且队列空，完整证据见`.work/c012/T23-*`。
- 2026-09-10 C012 T24：正式 task #10 `gen_shots` 生成28条连续分镜；导演台正式预检并创建 Clip #1（shots 1–3、宿舍）与 Clip #2（shots 25–28、球馆），API/DB/slot均回读一致。
- 2026-09-10 C012 T24：未提交视频生成任务；`observe --real` exit 0，真实库仍为`ai_drama_studio_c012_m6_20260910`、DATA_DIR为`D:\ai_drama_studio\.work\c012\t21-m6-data`且队列为空。
- 2026-09-10 C012 T25：task #11/#12 经正式 UI 分别生成 Clip #1/#2；真实 MP4 均可解码且 DB sha256、current take、REST/DB 槽位回读一致，`preflight --real`/`observe --real` exit 0。
- 2026-09-10 C012 T25：独立只读核对 `DATA_DIR\tmp` file_count=0；AX 重渲染后额外空 Clip #3（shots 4–6、无 task/video）保留原状并单独留证，未删除或补生成。
- 2026-09-10 C012 T22：按最新 AC-17 只读复核 task #1/#2/#3，第二次新增0、第三次最终新增0且原集合不变；task #3 原始模型响应缺失，task #4 完整采集仅证明该次模型漏提陈宁，边界见 `.work/c012/T22-reassessment.md`。
- 2026-09-10 C012 T24 重开：Chrome PID 24020 的外部 Comfy 长链停止后 `/history` 为 `execution_interrupted`、`/queue` 回到0/0；正式 UI 仅修改 Shot 2/25 description，revision 各+1、相关 Clip 各 stale，`observe --real` exit 0，证据见 `.work/c012/T24-reopen-*`。
- 2026-09-10 C012 T25 重开：正式 UI 仅新提交 task #13/#14，分别生成 Clip #1/#2 的 video #3/#4 并切为 current；旧 video #1/#2 保留，REST/DB/媒体探针与 payload 修订证据见 `.work/c012/T25-reopen-*`。
- 2026-09-10 C012 T26 重开：正式导演台播放 video #3/#4；Clip #1 抬眼/继续吃饭可定位，Clip #2 僵住可定位但未观察到明确指向，故 T26 保持未勾选；期间 Comfy 8188 曾无监听，恢复后只读 observe exit 0。
- 2026-09-10 C012 T26 只读诊断补充：task #14/video #4 的 Shot25 input_snapshot 同时保留“双手高举”旧描述与追加的明确指向句，rendered_prompt 含追加句但 detailed_description 仍为举臂且无逐Shot指向标签；未重生成，T26失败保留。
- 2026-09-11 C012 T29：隔离库 `ai_drama_studio_c012_t29_luna_20260911` 上定向恢复测试 4 passed；受控 recovery 启动进程把 running task #6 置为 `failed/server restarted`、保留 queued task #7，第二实例因 advisory lock returncode 3，owned 临时目录与连接退出后释放。
- 2026-09-11 C012 T30：隔离库 `ai_drama_studio_c012_t30_luna_20260911` 的生产 trash 启动/每日/IO 受控验收返回 passed；旧文件删除、cutoff 及 trash 外文件保留，`NotADirectoryError` 原样可见，受控进程退出后无残留监听。
- 2026-09-11 C012 T31：真实库`ai_drama_studio_c012_m6_20260910`/DATA_DIR`D:\ai_drama_studio\.work\c012\t21-m6-data`正式UI一次生成Clip#1得到task#15；running期间编辑Shot#2后任务done，Shot为revision3/changed、Clip为ready/stale，新take#5非current且原take#3与参考PNG未变；observe前后与隔离库B定向测试均exit0，证据见`.work/c012/T31-*-20260911.*`。
- 2026-09-11 C012 T33 G2：新库`ai_drama_studio_c012_g2_20260911`/DATA_DIR`D:\ai_drama_studio\.work\c012\t33-g2-data-20260911`完成Alembic upgrade/current/check（head=`c012_asset_name_unique`，均exit0）、完整backend `399 passed in 215.83s`、frontend `35 files/175 tests`、build `68 modules`与`git diff --check`（均exit0）；初始setup的`New-Item -LiteralPath`参数错误已按实际cmdlet改为`-Path`并复核目录/数据库存在，未使用示范库。
