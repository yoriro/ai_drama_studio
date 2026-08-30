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
