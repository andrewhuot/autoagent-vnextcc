import { useEffect, type ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  useEffect(() => {
    document.title = `${title} • AutoAgent`;
  }, [title]);

  return (
    <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <h2 className="text-xl font-semibold tracking-tight text-gray-900">{title}</h2>
        {description && <p className="mt-1.5 text-sm leading-relaxed text-gray-600">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </section>
  );
}
