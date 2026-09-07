interface EmptyStateProps {
  message: string;
}

export function EmptyState({ message }: EmptyStateProps) {
  return (
    <section
      aria-label={message}
      aria-live="polite"
      className="empty-state"
      role="status"
    >
      <p>{message}</p>
    </section>
  );
}
