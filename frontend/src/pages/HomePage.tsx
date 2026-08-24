import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

export function HomePage() {
  return (
    <>
      <PageTitle>项目首页</PageTitle>
      <EmptyState message="暂无项目" />
    </>
  );
}
