import { spawn } from 'node:child_process'

const cwd = new URL('..', import.meta.url).pathname.replace(/^\/(.:)/, '$1')
const server = spawn(
  process.execPath,
  ['./node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '4173'],
  { cwd, stdio: 'inherit' },
)

async function waitForServer() {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch('http://127.0.0.1:4173')
      if (response.ok) return
    } catch {
      // Vite 仍在启动。
    }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Vite test server did not become ready')
}

function waitForExit(child) {
  return new Promise(resolve => child.once('exit', code => resolve(code ?? 1)))
}

let exitCode = 1
try {
  await waitForServer()
  const tests = spawn(
    process.execPath,
    ['./node_modules/@playwright/test/cli.js', 'test', ...process.argv.slice(2)],
    { cwd, stdio: 'inherit' },
  )
  exitCode = await waitForExit(tests)
} finally {
  server.kill()
  await Promise.race([
    waitForExit(server),
    new Promise(resolve => setTimeout(resolve, 2_000)),
  ])
  server.unref()
}

process.exitCode = exitCode
