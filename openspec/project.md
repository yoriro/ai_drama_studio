# 项目约定

## 需求与范围

`docs/PRD-v1.2.md` 是最高需求真相。`AGENTS.md` 是每次会话的硬约束，`openspec/ROADMAP.md` 只确定 change 顺序与边界，具体实现只由当前 change 的 `proposal.md`、`spec.md` 和 `tasks.md` 授权。

## 技术栈

- 后端：Python、FastAPI、SQLAlchemy 2、Alembic、asyncpg、httpx。
- 数据库：PostgreSQL。
- 前端：React 18、Vite、TypeScript。
- 测试：pytest；需要验证数据库约束、事务或 claim 语义时使用 PostgreSQL，不以 SQLite 代替。

## 目录约定

当前冷启动仅创建顶层空目录；下列子目录由对应 change 在确有内容时创建，不预建空架构。

```text
backend/
  app/
    api/             # REST、WebSocket 与请求边界
    core/            # 配置、日志和进程级基础设施
    db/              # 会话、事务与数据库连接
    models/          # SQLAlchemy 模型
    schemas/         # API 输入输出模型
    services/        # 业务用例与强制规则
    integrations/    # vLLM、ComfyUI 等外部客户端
    tasks/           # 数据库队列、worker 与任务流水线
  alembic/           # 数据库迁移
  tests/
    unit/            # 纯函数层
    api/             # API 集成层
    task_system/     # 任务系统 mock 层
frontend/
  src/
    api/             # REST/WS 客户端与传输类型
    components/      # 跨功能复用的展示组件
    features/        # 按业务能力组织的状态与组件
    pages/           # 路由页面
    routes/          # 路由定义
openspec/
  changes/{change编号}/
    proposal.md
    spec.md
    tasks.md
  archive/{change编号}/
prompts/             # Sol/Luna 可复用提示词
docs/                # PRD 与项目依赖文档
```

Python 模块和 TypeScript 文件使用职责名，不带 `v2`、`new`、`final`、`improved` 等版本或修订含义。媒体文件只保存系统生成路径，API 不接受用户路径输入。

## 测试约定

pytest 测试只分三层：

1. **纯函数**：校验排序、时长、hash 输入组装、状态判定等无数据库和外部 I/O 的确定性逻辑。
2. **API 集成**：通过 FastAPI 边界验证请求、响应、PostgreSQL 事务/约束、级联和 `409`/`422` 语义。
3. **任务系统 mock**：保留真实任务状态机、payload 快照和数据库交互，只 mock vLLM、ComfyUI 与不可控媒体处理边界，验证成功、失败、取消及竞态。

所有自动测试必须先对应 `openspec/TRACEABILITY.md` 的一行，并在 change 实施时回填用例 ID；同一用例允许覆盖多行。没有追溯行的基础设施 task 采用命令或人工验收，不新增自动测试。

## 正式模板部署约定

全新 PostgreSQL 只由 Alembic migration 建立 schema 和四个明确占位模板，不从 spec、旧数据库或本机设置历史复制运行数据。四份正式模板是已经在 C005-C009 确认、由设置 API 管理的运行配置；C012 必须在全新生产等价库上通过正式 API 自动安装，安装后及后端重启后逐字回读，并由 M6 全链路实际消费。不得修改 migration seed、直接写库、克隆旧库或要求 E2E 操作者临时补模板。

## Change 工作流

1. **proposal**：Sol 根据 ROADMAP、当前代码与 PRD 相关章节，写清目标、边界、影响和外部依赖。
2. **spec**：把该 change 的可观察行为、错误语义、数据/API/UI 约束与验收标准定稿；歧义未解决不得进入 tasks。
3. **tasks**：拆成可独立验收的有序任务，每项标注 PRD/R 规则、验收方式、计划测试和追溯行。
4. **执行**：Luna 一次只完成一个指定 task，不得越出 spec；运行计划测试与完整 pytest 后才可勾选并提交。
5. **审查**：Sol 按 spec 审查 diff、围栏、错误码、追溯回填和真实测试证据；发现问题退回执行阶段。
6. **archive**：change 全部验收并获确认后，完整移动到 `openspec/archive/{change编号}/`，不保留双份活动文档。
