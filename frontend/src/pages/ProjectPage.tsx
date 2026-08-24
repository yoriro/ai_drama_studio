import { useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

export function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();

  return (
    <>
      <PageTitle>项目详情</PageTitle>
      <p>项目 ID：{projectId ?? "未知"}</p>
      <EmptyState message="项目详情壳已就绪，业务页面将在后续任务接入。" />
    </>
  );
}
