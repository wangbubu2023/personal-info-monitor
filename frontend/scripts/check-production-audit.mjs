#!/usr/bin/env node
/**
 * Keep npm audit fail-closed while the only available React Router release
 * carries an RSC-only advisory that this declarative BrowserRouter app cannot
 * reach. The exception expires quickly and does not hide any other advisory.
 */

import { spawnSync } from 'node:child_process'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ALLOWED_URL = 'https://github.com/advisories/GHSA-qwww-vcr4-c8h2'
const EXPIRES_AT = Date.parse('2026-09-01T00:00:00Z')
const RSC_MARKERS = [
  'createRequestHandler',
  'ServerRouter',
  'unstable_RSC',
  'RSCStaticRouter',
  'react-router/server',
]

function sourceFiles(root) {
  return readdirSync(root).flatMap((entry) => {
    const path = join(root, entry)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    return /\.(?:ts|tsx|js|jsx)$/.test(path) ? [path] : []
  })
}

const source = sourceFiles(new URL('../src', import.meta.url).pathname)
  .map((path) => readFileSync(path, 'utf8'))
  .join('\n')

const usedRscMarker = RSC_MARKERS.find((marker) => source.includes(marker))
if (usedRscMarker) {
  console.error(`React Router audit exception is invalid: RSC marker found: ${usedRscMarker}`)
  process.exit(1)
}
if (!source.includes('BrowserRouter')) {
  console.error('React Router audit exception is invalid: declarative BrowserRouter was not found')
  process.exit(1)
}
if (Date.now() >= EXPIRES_AT) {
  console.error('React Router audit exception expired on 2026-09-01; reassess or upgrade')
  process.exit(1)
}

const audit = spawnSync('npm', ['audit', '--omit=dev', '--json'], {
  cwd: new URL('..', import.meta.url),
  encoding: 'utf8',
})
if (audit.error) {
  console.error(`npm audit failed to start: ${audit.error.message}`)
  process.exit(1)
}

let report
try {
  report = JSON.parse(audit.stdout)
} catch {
  console.error('npm audit returned invalid JSON')
  console.error(audit.stderr)
  process.exit(1)
}
if (report.error) {
  console.error(`npm audit failed: ${JSON.stringify(report.error)}`)
  process.exit(1)
}

const vulnerabilities = report.vulnerabilities ?? {}
function advisoriesFor(name, seen = new Set()) {
  if (seen.has(name)) return []
  seen.add(name)
  return (vulnerabilities[name]?.via ?? []).flatMap((via) =>
    typeof via === 'string' ? advisoriesFor(via, seen) : [via],
  )
}

const unexpected = []
const accepted = new Set()
for (const name of Object.keys(vulnerabilities)) {
  const advisories = advisoriesFor(name)
  if (advisories.length === 0) {
    unexpected.push(`${name}: no concrete advisory could be resolved`)
    continue
  }
  for (const advisory of advisories) {
    if (advisory.url === ALLOWED_URL && advisory.dependency === 'react-router') {
      accepted.add(advisory.url)
    } else {
      unexpected.push(`${name}: ${advisory.url ?? advisory.title ?? 'unknown advisory'}`)
    }
  }
}

if (unexpected.length > 0) {
  console.error('Unexpected production dependency advisories:')
  for (const finding of unexpected) console.error(`- ${finding}`)
  process.exit(1)
}
if (Object.keys(vulnerabilities).length > 0 && !accepted.has(ALLOWED_URL)) {
  console.error('Production vulnerabilities were reported but did not match the scoped exception')
  process.exit(1)
}

if (accepted.size > 0) {
  console.log(
    'Accepted temporary GHSA-qwww-vcr4-c8h2 exception through 2026-09-01: ' +
      'the app uses declarative BrowserRouter and contains no RSC server/action runtime.',
  )
} else {
  console.log('No production dependency vulnerabilities found')
}
