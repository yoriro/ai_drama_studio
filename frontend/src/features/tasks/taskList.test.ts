import { describe, expect, it } from "vitest";

import {
  buildTaskListQuery,
  groupTasksByStatus,
} from "./taskList";

describe("task list filters", () => {
  it("omits all status and type values while preserving the selected limit", () => {
    expect(
      buildTaskListQuery({ status: "all", type: "all", limit: 50 }),
    ).toEqual({ limit: 50 });
  });

  it("builds the existing status/type/limit query together", () => {
    expect(
      buildTaskListQuery({
        status: "failed",
        type: "gen_clip_video",
        limit: 100,
      }),
    ).toEqual({ status: "failed", type: "gen_clip_video", limit: 100 });
  });

  it("sorts each group by descending task id without mutating the input", () => {
    const tasks = [
      { id: 2, status: "done" as const },
      { id: 5, status: "queued" as const },
      { id: 3, status: "failed" as const },
      { id: 4, status: "running" as const },
      { id: 1, status: "canceled" as const },
    ];

    expect(groupTasksByStatus(tasks)).toEqual({
      inProgress: [
        { id: 5, status: "queued" },
        { id: 4, status: "running" },
      ],
      history: [
        { id: 3, status: "failed" },
        { id: 2, status: "done" },
        { id: 1, status: "canceled" },
      ],
    });
    expect(tasks.map((task) => task.id)).toEqual([2, 5, 3, 4, 1]);
  });
});
