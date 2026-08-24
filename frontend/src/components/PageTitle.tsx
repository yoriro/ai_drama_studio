interface PageTitleProps {
  children: string;
}

export function PageTitle({ children }: PageTitleProps) {
  return <h1 className="page-title">{children}</h1>;
}
