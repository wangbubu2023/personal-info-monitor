import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // The full jsdom suite can legitimately take longer than the per-test
    // default on a cold desktop runtime. Keep the timeout deterministic so
    // an otherwise healthy interaction test is not reported as flaky.
    testTimeout: 15000,
    hookTimeout: 15000,
  },
})
