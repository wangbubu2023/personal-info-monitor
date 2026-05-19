import React, { useCallback, useState } from 'react';
import { ChevronDown, Info, AlertTriangle, ShieldCheck } from 'lucide-react';

type SectionNoteTone = 'neutral' | 'caution' | 'success';

export interface SectionNoteProps {
  title?: React.ReactNode;
  children: React.ReactNode;
  tone?: SectionNoteTone;
  style?: React.CSSProperties;
  className?: string;
  /** 更紧凑的边距与图标，默认 true */
  compact?: boolean;
  /** 可折叠（适合长说明）；会记住展开状态（需 storageKey） */
  collapsible?: boolean;
  /** 与 collapsible 配合：无 localStorage 时的初始是否展开 */
  defaultOpen?: boolean;
  /** 展开状态持久化 key；不设则仅内存状态 */
  storageKey?: string;
}

const toneConfigs: Record<
  SectionNoteTone,
  { bg: string; border: string; iconColor: string; icon: typeof Info }
> = {
  neutral: {
    bg: 'bg-[#49A8C9]/[0.06]',
    border: 'border-[#49A8C9]/20',
    iconColor: 'text-[#3d94b3]',
    icon: Info,
  },
  caution: {
    bg: 'bg-amber-50/90',
    border: 'border-amber-200/70',
    iconColor: 'text-amber-600',
    icon: AlertTriangle,
  },
  success: {
    bg: 'bg-emerald-50/90',
    border: 'border-emerald-200/70',
    iconColor: 'text-emerald-700',
    icon: ShieldCheck,
  },
};

function readStoredOpen(key: string | undefined, fallback: boolean): boolean {
  if (!key || typeof window === 'undefined') return fallback;
  try {
    const getItem = localStorage.getItem?.bind(localStorage);
    if (typeof getItem !== 'function') return fallback;
    const v = getItem(key);
    if (v === null) return fallback;
    return v === '1';
  } catch {
    return fallback;
  }
}

const SectionNote: React.FC<SectionNoteProps> = ({
  title,
  children,
  tone = 'neutral',
  style,
  className = '',
  compact = true,
  collapsible = false,
  defaultOpen = true,
  storageKey,
}) => {
  const config = toneConfigs[tone];
  const Icon = config.icon;

  const [open, setOpen] = useState(() =>
    collapsible ? readStoredOpen(storageKey, defaultOpen) : true,
  );

  const toggle = useCallback(() => {
    if (!collapsible) return;
    setOpen((prev) => {
      const next = !prev;
      if (storageKey && typeof window !== 'undefined' && typeof localStorage.setItem === 'function') {
        try {
          localStorage.setItem(storageKey, next ? '1' : '0');
        } catch {
          /* ignore quota / private mode */
        }
      }
      return next;
    });
  }, [collapsible, storageKey]);

  const showBody = !collapsible || open;

  const pad = compact ? 'p-2.5 sm:p-3' : 'p-4 sm:p-5';
  const gap = compact ? 'gap-2.5' : 'gap-4';
  const round = compact ? 'rounded-xl' : 'rounded-2xl';
  const shell = `${round} border ${pad} ${config.bg} ${config.border}`;

  const iconEl = compact ? (
    <div className={`mt-0.5 shrink-0 ${config.iconColor}`}>
      <Icon size={15} strokeWidth={2} />
    </div>
  ) : (
    <div
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[rgba(88,100,118,0.12)] bg-white/90 shadow-sm ${config.iconColor}`}
    >
      <Icon size={17} />
    </div>
  );

  const bodyClass = compact
    ? 'text-[12px] font-normal leading-relaxed text-[#5a6a7d]'
    : 'text-[13px] font-medium leading-relaxed text-[#586476]';

  if (collapsible) {
    return (
      <div className={`flex flex-col ${gap} ${shell} ${className}`} style={style}>
        <button
          type="button"
          className="flex w-full gap-2.5 text-left outline-none ring-offset-2 focus-visible:ring-2 focus-visible:ring-[#49A8C9]/40"
          onClick={toggle}
          aria-expanded={open}
        >
          {iconEl}
          <div className="flex min-w-0 flex-1 items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              {title && (
                <div className="text-[13px] font-semibold tracking-tight text-[#293859] sm:text-sm">
                  {title}
                </div>
              )}
            </div>
            <span
              className="mt-0.5 shrink-0 text-[#586476] transition-transform duration-200"
              style={{ transform: open ? 'rotate(180deg)' : undefined }}
              aria-hidden
            >
              <ChevronDown size={16} strokeWidth={2} />
            </span>
          </div>
        </button>
        {showBody && (
          <div
            className={`border-l-2 border-[#49A8C9]/20 pl-3 ${compact ? 'ml-1' : 'ml-2'} ${bodyClass}`}
          >
            {children}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`flex ${gap} ${shell} ${className}`} style={style}>
      {iconEl}
      <div className="min-w-0 flex-1 leading-relaxed">
        {title && (
          <div className="mb-0.5 text-[13px] font-semibold tracking-tight text-[#293859] sm:text-sm">
            {title}
          </div>
        )}
        <div className={bodyClass}>{children}</div>
      </div>
    </div>
  );
};

export default SectionNote;
