import React from 'react'

interface StatCardProps {
  title: string
  value: number | string
  icon: React.ReactNode
  trend?: {
    value: number
    isUp: boolean
  }
  color?: string
}

const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  icon,
  trend,
  color = 'var(--color-primary)',
}) => {
  return (
    <div className="bg-white rounded-xl p-6 border border-[var(--color-border-light)] hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">
            {title}
          </p>
          <p 
            className="text-3xl font-bold"
            style={{ color }}
          >
            {value}
          </p>
          {trend && (
            <p className={`text-sm mt-2 ${trend.isUp ? 'text-green-500' : 'text-red-500'}`}>
              {trend.isUp ? '↑' : '↓'} {Math.abs(trend.value)}%
              <span className="text-[var(--color-text-tertiary)] ml-1">较昨日</span>
            </p>
          )}
        </div>
        <div 
          className="p-3 rounded-xl"
          style={{ 
            backgroundColor: `${color}15`,
            color,
          }}
        >
          {icon}
        </div>
      </div>
    </div>
  )
}

export default StatCard
