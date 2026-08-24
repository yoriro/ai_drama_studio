import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

export function TasksPage() {
  return (
    <>
      <PageTitle>任务中心</PageTitle>
      <EmptyState message="暂无任务" />
    </>
  );
}
