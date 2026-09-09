import { useEffect, useRef, useState } from "react";

import type { Task } from "../api/tasks";
import { ApiErrorMessage } from "../components/ApiErrorMessage";
import { AuxiliaryPageReturn } from "../components/AuxiliaryPageReturn";
import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";
import {
  createTaskObservation,
  createTaskObservationInitialState,
  type TaskDetailState,
  type TaskObservationController,
  type TaskObservationState,
} from "../features/tasks/taskObservation";
import {
  buildTaskListQuery,
  groupTasksByStatus,
  TASK_LIMIT_OPTIONS,
  TASK_STATUS_FILTER_OPTIONS,
  TASK_TYPE_FILTER_OPTIONS,
  type TaskListLimit,
  type TaskStatusFilter,
  type TaskTypeFilter,
} from "../features/tasks/taskList";

function formatTaskTime(value: string | null): string {
  return value === null
    ? "—"
    : new Date(value).toLocaleString(undefined, { timeZoneName: "short" });
}

export function TasksPage() {
  const [statusFilter, setStatusFilter] =
    useState<TaskStatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<TaskTypeFilter>("all");
  const [taskLimit, setTaskLimit] = useState<TaskListLimit>(50);
  const [observation, setObservation] = useState<TaskObservationState>(() =>
    createTaskObservationInitialState(),
  );
  const [expandedTaskId, setExpandedTaskId] = useState<number | null>(null);
  const observationController = useRef<TaskObservationController | null>(null);

  useEffect(() => {
    const controller = createTaskObservation({
      query: buildTaskListQuery({
        status: statusFilter,
        type: typeFilter,
        limit: taskLimit,
      }),
    });
    observationController.current = controller;
    const unsubscribe = controller.subscribe(setObservation);
    controller.start();
    return () => {
      unsubscribe();
      controller.dispose();
      if (observationController.current === controller) {
        observationController.current = null;
      }
    };
  }, []);

  useEffect(() => {
    observationController.current?.setQuery(
      buildTaskListQuery({
        status: statusFilter,
        type: typeFilter,
        limit: taskLimit,
      }),
    );
  }, [statusFilter, taskLimit, typeFilter]);

  const taskGroups = groupTasksByStatus(observation.tasks);

  function toggleTaskDetail(taskId: number): void {
    if (expandedTaskId === taskId) {
      setExpandedTaskId(null);
      observationController.current?.setExpandedTask(null);
      return;
    }
    setExpandedTaskId(taskId);
    observationController.current?.setExpandedTask(taskId);
    observationController.current?.loadTaskDetail(taskId);
  }

  function renderTaskDetail(
    task: Task,
    detail: TaskDetailState | undefined,
  ) {
    if (detail?.phase === "error") {
      return (
        <div
          className="task-detail"
          data-task-state="detail-error"
          id={`task-detail-${task.id}`}
        >
          <ApiErrorMessage error={detail.error} />
        </div>
      );
    }
    if (detail?.phase !== "ready" || detail.task === null) {
      return (
        <p
          className="field-hint"
          data-task-state="detail-loading"
          id={`task-detail-${task.id}`}
        >
          正在加载任务详情…
        </p>
      );
    }

    const detailTask = detail.task;
    return (
      <dl
        className="task-detail"
        data-task-state="detail-ready"
        id={`task-detail-${task.id}`}
      >
        <div>
          <dt>request_id</dt>
          <dd>{detailTask.request_id ?? "—"}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>{detailTask.status}</dd>
        </div>
        <div>
          <dt>进度</dt>
          <dd>{detailTask.progress}</dd>
        </div>
        <div>
          <dt>心跳时间（本地时区）</dt>
          <dd>{formatTaskTime(detailTask.heartbeat_at)}</dd>
        </div>
        <div>
          <dt>取消请求时间（本地时区）</dt>
          <dd>{formatTaskTime(detailTask.cancel_requested_at)}</dd>
        </div>
        <div>
          <dt>创建时间（本地时区）</dt>
          <dd>{formatTaskTime(detailTask.created_at)}</dd>
        </div>
        <div>
          <dt>开始时间（本地时区）</dt>
          <dd>{formatTaskTime(detailTask.started_at)}</dd>
        </div>
        <div>
          <dt>完成时间（本地时区）</dt>
          <dd>{formatTaskTime(detailTask.finished_at)}</dd>
        </div>
        <div>
          <dt>完整错误</dt>
          <dd>
            <pre className="task-error-detail">
              {detailTask.error_msg ?? "—"}
            </pre>
          </dd>
        </div>
      </dl>
    );
  }

  function renderTaskCard(task: Task) {
    const isExpanded = expandedTaskId === task.id;
    const cancelState = observation.cancelStates[task.id];
    const cancelRequested =
      task.status === "running" && task.cancel_requested_at !== null;
    const canCancel = task.status === "queued" || task.status === "running";
    const cancelAuthorityPending = cancelState?.authorityPending === true;
    return (
      <article className="entity-card task-card" key={task.id}>
        <div className="task-heading">
          <h3>任务 #{task.id}</h3>
          <span className="task-status">{task.status}</span>
        </div>
        <p>
          类型：{task.type}；目标 ID：{task.target_id}
        </p>
        <div className="task-progress-row">
          <progress
            aria-label={`任务 ${task.id} 进度`}
            max={1}
            value={task.progress}
          />
          <span>{Math.round(task.progress * 100)}%</span>
        </div>
        {task.error_msg !== null && (
          <p className="error-message">{task.error_msg}</p>
        )}
        <dl className="task-times">
          <div>
            <dt>创建时间</dt>
            <dd>{formatTaskTime(task.created_at)}</dd>
          </div>
          <div>
            <dt>开始时间</dt>
            <dd>{formatTaskTime(task.started_at)}</dd>
          </div>
          <div>
            <dt>完成时间</dt>
            <dd>{formatTaskTime(task.finished_at)}</dd>
          </div>
        </dl>
        {(cancelState?.phase === "error" ||
          cancelState?.phase === "unknown") && (
          <ApiErrorMessage error={cancelState.error} />
        )}
        {cancelState?.phase === "unknown" && cancelAuthorityPending && (
          <p data-task-state="cancel-unconfirmed">
            取消结果未确认，正在读取最新任务状态
          </p>
        )}
        {cancelState?.phase === "posting" && (
          <button disabled type="button">
            正在取消…
          </button>
        )}
        {cancelState?.phase === "confirming" && (
          <button disabled type="button">
            正在确认取消…
          </button>
        )}
        {cancelState?.phase === "unknown" && cancelAuthorityPending && (
          <button disabled type="button">
            取消结果未确认
          </button>
        )}
        {cancelRequested &&
          !cancelAuthorityPending &&
          cancelState?.phase !== "confirming" && (
          <>
            <button disabled type="button">
              已请求取消
            </button>
            <p data-task-state="cancel-requested">
              已请求取消，等待任务停止
            </p>
          </>
        )}
        {canCancel &&
          !cancelRequested &&
          cancelState?.phase !== "posting" &&
          cancelState?.phase !== "confirming" &&
          !cancelAuthorityPending && (
            <button
              type="button"
              onClick={() => observationController.current?.cancelTask(task.id)}
            >
              取消任务
            </button>
          )}
        <button
          aria-controls={isExpanded ? `task-detail-${task.id}` : undefined}
          aria-expanded={isExpanded}
          type="button"
          onClick={() => toggleTaskDetail(task.id)}
        >
          {isExpanded ? "收起详情" : "查看详情"}
        </button>
        {isExpanded &&
          renderTaskDetail(task, observation.taskDetails[task.id])}
      </article>
    );
  }

  return (
    <>
      <AuxiliaryPageReturn />
      <PageTitle>任务中心</PageTitle>
      <section aria-label="任务筛选" className="panel task-filters">
        <h2>任务筛选</h2>
        <div className="task-filter-grid">
          <label>
            状态
            <select
              aria-label="状态筛选"
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value as TaskStatusFilter)
              }
            >
              {TASK_STATUS_FILTER_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {status === "all" ? "全部" : status}
                </option>
              ))}
            </select>
          </label>
          <label>
            类型
            <select
              aria-label="类型筛选"
              value={typeFilter}
              onChange={(event) =>
                setTypeFilter(event.target.value as TaskTypeFilter)
              }
            >
              {TASK_TYPE_FILTER_OPTIONS.map((type) => (
                <option key={type} value={type}>
                  {type === "all" ? "全部" : type}
                </option>
              ))}
            </select>
          </label>
          <label>
            数量
            <select
              aria-label="任务数量"
              value={taskLimit}
              onChange={(event) =>
                setTaskLimit(Number(event.target.value) as TaskListLimit)
              }
            >
              {TASK_LIMIT_OPTIONS.map((limit) => (
                <option key={limit} value={limit}>
                  {limit}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="field-hint">
          最多显示匹配条件的最近 {taskLimit} 条，本次已加载 {observation.tasks.length} 条
        </p>
      </section>
      {observation.connectionState === "reconnecting" && (
        <p
          aria-live="polite"
          className="connection-message"
          data-task-state="reconnecting"
          role="status"
        >
          实时连接已断开，正在重连
        </p>
      )}
      {observation.listPhase === "updating" &&
        observation.tasks.length > 0 && (
          <p
            aria-live="polite"
            className="connection-message"
            data-task-state="updating"
            role="status"
          >
            正在更新，以下为上次结果
          </p>
        )}
      {observation.listPhase === "loading" && (
        <section
          aria-live="polite"
          className="panel"
          data-task-state="loading"
        >
          <p>正在加载任务…</p>
        </section>
      )}
      {observation.listError !== null && (
        <section data-task-state="rest-error">
          <ApiErrorMessage error={observation.listError} />
        </section>
      )}
      {observation.socketError !== null && (
        <section data-task-state="socket-error">
          <ApiErrorMessage error={observation.socketError} />
        </section>
      )}
      {observation.detailError !== null &&
        (expandedTaskId !== observation.detailError.taskId ||
          observation.taskDetails[observation.detailError.taskId]?.phase !==
            "error") && (
        <section
          aria-label="任务详情错误"
          data-task-state="detail-error"
        >
          <p>任务 #{observation.detailError.taskId} 详情读取失败</p>
          <ApiErrorMessage error={observation.detailError.error} />
        </section>
      )}
      {Object.entries(observation.cancelStates)
        .filter(
          ([taskId, cancelState]) =>
            (cancelState.phase === "error" ||
              cancelState.phase === "unknown") &&
            !observation.tasks.some((task) => task.id === Number(taskId)),
        )
        .map(([taskId, cancelState]) => (
          <section
            aria-label={`任务 ${taskId} 取消错误`}
            data-task-state="cancel-error"
            key={taskId}
          >
            <p>任务 #{taskId}：取消操作</p>
            <ApiErrorMessage error={cancelState.error} />
            {cancelState.phase === "unknown" &&
              cancelState.authorityPending && (
                <p>取消结果未确认，正在读取最新任务状态</p>
              )}
          </section>
        ))}
      {observation.listPhase === "ready" && observation.tasks.length === 0 && (
        <div data-task-state="empty">
          <EmptyState message="当前条件下暂无任务" />
        </div>
      )}
      {observation.listPhase !== "loading" && observation.tasks.length > 0 && (
        <>
          {taskGroups.inProgress.length > 0 && (
            <section aria-label="进行中任务" className="task-group">
              <h2>进行中</h2>
              <div className="task-list" data-task-state="ready">
                {taskGroups.inProgress.map(renderTaskCard)}
              </div>
            </section>
          )}
          {taskGroups.history.length > 0 && (
            <section aria-label="历史任务" className="task-group">
              <h2>历史</h2>
              <div className="task-list" data-task-state="ready">
                {taskGroups.history.map(renderTaskCard)}
              </div>
            </section>
          )}
        </>
      )}
    </>
  );
}
