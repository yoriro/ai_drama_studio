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
