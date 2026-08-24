import { EmptyState } from "../components/EmptyState";
import { PageTitle } from "../components/PageTitle";

export function SettingsPage() {
  return (
    <>
      <PageTitle>设置</PageTitle>
      <EmptyState message="暂无可用设置" />
    </>
  );
}
