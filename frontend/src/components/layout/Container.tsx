import React from 'react'

interface ContainerProps {
  children: React.ReactNode
  className?: string
  size?: 'default' | 'wide' | 'narrow'
}

const Container: React.FC<ContainerProps> = ({
  children,
  className = '',
  size = 'default',
}) => {
  const maxWidthClass = {
    default: 'max-w-[var(--max-width-content)]',
    wide: 'max-w-[var(--max-width-wide)]',
    narrow: 'max-w-4xl',
  }[size]

  return (
    <div className={`${maxWidthClass} mx-auto px-6 py-8 ${className}`}>
      {children}
    </div>
  )
}

export default Container
