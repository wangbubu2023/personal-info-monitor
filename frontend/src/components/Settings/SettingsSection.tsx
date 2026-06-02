import React from 'react'

interface SettingsSectionProps {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
  contentClassName?: string
}

const SettingsSection: React.FC<SettingsSectionProps> = ({
  title,
  description,
  actions,
  children,
  className = '',
  contentClassName = '',
}) => (
  <section
    className={`rounded-2xl border border-[rgba(88,100,118,0.12)] bg-white shadow-[0_8px_28px_-18px_rgba(41,56,89,0.18)] ${className}`}
  >
    <div className="flex flex-col gap-3 border-b border-[rgba(88,100,118,0.1)] px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-5">
      <div className="min-w-0">
        <h3 className="m-0 text-[15px] font-semibold tracking-tight text-[#2c3a50]">{title}</h3>
        {description ? (
          <p className="mb-0 mt-1.5 max-w-4xl text-[12px] leading-relaxed text-[#6b7c8f]">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
    <div className={`px-4 py-4 sm:px-5 ${contentClassName}`}>{children}</div>
  </section>
)

export default SettingsSection
