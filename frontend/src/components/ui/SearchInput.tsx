import React, { useState, useCallback } from 'react'
import { SearchOutlined, CloseCircleFilled } from '@ant-design/icons'

interface SearchInputProps {
  placeholder?: string
  value?: string
  onChange?: (value: string) => void
  onSearch?: (value: string) => void
  className?: string
  size?: 'small' | 'default' | 'large'
  allowClear?: boolean
}

const sizeClasses = {
  small: 'py-1.5 text-sm',
  default: 'py-2 text-sm',
  large: 'py-2.5 text-base',
}

const SearchInput: React.FC<SearchInputProps> = ({
  placeholder = '搜索...',
  value: controlledValue,
  onChange,
  onSearch,
  className = '',
  size = 'default',
  allowClear = true,
}) => {
  const [internalValue, setInternalValue] = useState('')
  const isControlled = controlledValue !== undefined
  const value = isControlled ? controlledValue : internalValue

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const newValue = e.target.value
    if (!isControlled) {
      setInternalValue(newValue)
    }
    onChange?.(newValue)
  }, [isControlled, onChange])

  const handleClear = useCallback(() => {
    if (!isControlled) {
      setInternalValue('')
    }
    onChange?.('')
  }, [isControlled, onChange])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      onSearch?.(value)
    }
  }, [onSearch, value])

  return (
    <div className={`relative ${className}`}>
      <SearchOutlined 
        className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] pointer-events-none"
      />
      <input
        type="text"
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className={`
          w-full pl-9 pr-${allowClear && value ? '9' : '3'}
          border border-[var(--color-border)] rounded-[var(--radius-lg)]
          outline-none transition-all
          focus:border-[var(--color-primary)] focus:shadow-[0_0_0_2px_rgba(107,124,63,0.1)]
          placeholder:text-[var(--color-text-muted)]
          bg-white
          ${sizeClasses[size]}
        `}
      />
      {allowClear && value && (
        <button
          onClick={handleClear}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] cursor-pointer bg-transparent border-none p-0 flex items-center justify-center"
        >
          <CloseCircleFilled />
        </button>
      )}
    </div>
  )
}

export default SearchInput
