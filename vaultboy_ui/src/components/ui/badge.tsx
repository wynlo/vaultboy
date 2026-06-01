import * as React from 'react';
import { cn } from '../../lib/utils';

const statusClasses: Record<string, string> = {
  Synced: 'bg-emerald-700 text-white',
  'Needs sync': 'bg-amber-700 text-white',
  Conflict: 'bg-red-700 text-white',
  'Missing path': 'bg-red-700 text-white',
  Error: 'bg-red-700 text-white',
  Disabled: 'bg-zinc-600 text-white',
};

export function Badge({ status, className, ...props }: React.HTMLAttributes<HTMLSpanElement> & { status?: string }) {
  return (
    <span className={cn('inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium', statusClasses[status || ''] || 'bg-zinc-700 text-white', className)} {...props}>
      {status}
    </span>
  );
}
