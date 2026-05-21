import React from 'react'
import { Slider } from 'antd'

/** Ollama num_ctx presets: 1K … 256K (powers of two). */
export const OLLAMA_CTX_STEPS = [
  1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144,
] as const

export function formatOllamaCtxLabel(value: number): string {
  if (value >= 1024 && value % 1024 === 0) {
    return `${value / 1024}K`
  }
  return String(value)
}

export function snapOllamaNumCtx(value: number | undefined, fallback: number): number {
  const target = value ?? fallback
  if (OLLAMA_CTX_STEPS.includes(target as (typeof OLLAMA_CTX_STEPS)[number])) {
    return target
  }
  return OLLAMA_CTX_STEPS.reduce((best, cur) =>
    Math.abs(cur - target) < Math.abs(best - target) ? cur : best,
  )
}

const SLIDER_MARKS = Object.fromEntries(
  OLLAMA_CTX_STEPS.map((step, index) => [index, formatOllamaCtxLabel(step)]),
)

interface OllamaCtxSliderProps {
  value?: number
  onChange?: (value: number) => void
}

const OllamaCtxSlider: React.FC<OllamaCtxSliderProps> = ({ value, onChange }) => {
  const snapped = snapOllamaNumCtx(value, OLLAMA_CTX_STEPS[0])
  const index = Math.max(0, OLLAMA_CTX_STEPS.indexOf(snapped as (typeof OLLAMA_CTX_STEPS)[number]))

  return (
    <Slider
      min={0}
      max={OLLAMA_CTX_STEPS.length - 1}
      step={1}
      value={index}
      marks={SLIDER_MARKS}
      tooltip={{
        formatter: (raw) => {
          const i = typeof raw === 'number' ? raw : index
          return formatOllamaCtxLabel(OLLAMA_CTX_STEPS[i] ?? snapped)
        },
      }}
      onChange={(nextIndex) => onChange?.(OLLAMA_CTX_STEPS[nextIndex] ?? snapped)}
    />
  )
}

export default OllamaCtxSlider
