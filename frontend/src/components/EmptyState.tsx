interface EmptyStateProps {
  message: string;
}

export function EmptyState({ message }: EmptyStateProps) {
  return (
    <section aria-label={message} className="empty-state">
      <p>{message}</p>
    </section>
  );
}
