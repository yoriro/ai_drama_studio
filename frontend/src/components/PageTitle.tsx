interface PageTitleProps {
  children: string;
  variant?: "home" | "work";
}

export function PageTitle({ children, variant = "work" }: PageTitleProps) {
  return (
    <h1 className={variant === "home" ? "page-title page-title-home" : "page-title"}>
      {children}
    </h1>
  );
}
