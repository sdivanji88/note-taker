import { spawn as nodeSpawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import net from 'node:net'

export interface BackendOptions {
  backendDir: string
  dataDir: string
}

export interface RunningBackend {
  baseUrl: string
  token: string
  stop: () => Promise<void>
}

// Injection points for tests; production uses the defaults.
export interface BackendDeps {
  spawn?: typeof nodeSpawn
  fetch?: typeof fetch
  kill?: (pid: number, signal: NodeJS.Signals) => void
  pollMs?: number
  timeoutMs?: number
  killGraceMs?: number
}

// Enough to show a Python traceback, small enough to put in a dialog.
const STDERR_LIMIT = 8 * 1024

// There is a window between closing this probe server and uvicorn binding the port in
// which another process could take it. For a single-user desktop app that race is
// negligible, and a lost race surfaces as a normal startup failure with stderr.
export function pickFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as net.AddressInfo
      server.close((err) => (err ? reject(err) : resolve(port)))
    })
  })
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function startBackend(
  opts: BackendOptions,
  deps: BackendDeps = {}
): Promise<RunningBackend> {
  const spawn = deps.spawn ?? nodeSpawn
  const doFetch = deps.fetch ?? fetch
  const kill = deps.kill ?? process.kill
  const pollMs = deps.pollMs ?? 250
  const timeoutMs = deps.timeoutMs ?? 20_000
  const killGraceMs = deps.killGraceMs ?? 3_000

  const port = await pickFreePort()
  const token = randomBytes(32).toString('hex')
  const baseUrl = `http://127.0.0.1:${port}`

  // The token travels in the child's environment only: argv is world-readable via `ps`.
  const child: ChildProcess = spawn(
    'uv',
    ['run', '--project', opts.backendDir, 'python', '-m', 'note_taker', '--port', String(port), '--data-dir', opts.dataDir, '--exit-on-stdin-eof'],
    {
      env: { ...process.env, NOTE_TAKER_TOKEN: token },
      // stdin stays open for the child's lifetime and is never closed by us: when this
      // process dies (even kill -9) the OS closes it and the backend sees EOF and exits.
      stdio: ['pipe', 'ignore', 'pipe'],
      // Own process group, so signals reach python behind `uv run`. Not unref'd: we
      // still wait for the exit event.
      detached: true
    }
  )

  // uv forwards SIGTERM but cannot forward SIGKILL, so signal the whole group (-pid).
  // ESRCH means the group is already gone, which is what we wanted.
  const signalGroup = (signal: NodeJS.Signals): void => {
    // No pid means spawn itself failed, so there is nothing to signal.
    if (child.pid === undefined) return
    try {
      kill(-child.pid, signal)
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== 'ESRCH') throw err
    }
  }

  let stderr = ''
  child.stderr?.on('data', (chunk: Buffer) => {
    stderr = (stderr + chunk.toString()).slice(-STDERR_LIMIT)
  })

  let exited = child.exitCode !== null || child.signalCode !== null
  const exitWaiters: Array<() => void> = []
  function markGone(): void {
    exited = true
    process.removeListener('exit', killOnProcessExit)
    exitWaiters.splice(0).forEach((w) => w())
  }
  child.once('exit', markGone)
  const waitForExit = () => new Promise<void>((resolve) => (exited ? resolve() : exitWaiters.push(resolve)))

  // Last resort if Electron dies without before-quit: only synchronous work runs here.
  function killOnProcessExit(): void {
    if (!exited) signalGroup('SIGTERM')
  }
  process.once('exit', killOnProcessExit)

  let stopping: Promise<void> | undefined
  const stop = (): Promise<void> => {
    stopping ??= (async () => {
      if (exited) return
      signalGroup('SIGTERM')
      let timer: NodeJS.Timeout | undefined
      const forced = new Promise<void>((resolve) => {
        timer = setTimeout(() => {
          if (!exited) signalGroup('SIGKILL')
          resolve()
        }, killGraceMs)
      })
      await Promise.race([waitForExit(), forced])
      clearTimeout(timer)
      await waitForExit()
    })()
    return stopping
  }

  // Resolves when /health answers; rejects on child exit (immediately) or the deadline.
  const earlyExit = new Promise<never>((_, reject) => {
    child.once('exit', (code, signal) => {
      reject(new Error(`backend exited with code ${code ?? signal} during startup:\n${stderr}`))
    })
  })
  // A spawn failure (uv missing, not executable) emits 'error' and never 'exit'; without
  // a listener it would crash the main process, and without rejecting here startup would
  // sit out the full timeout. After a successful start the rejection is simply unused:
  // an 'error' then (e.g. a failed signal) is ignored, and a dead backend is handled by
  // the 'exit' path / the API's network errors.
  const spawnFailed = new Promise<never>((_, reject) => {
    child.on('error', (err: NodeJS.ErrnoException) => {
      if (child.pid === undefined) markGone() // never started: nothing to wait for or signal
      const hint = err.code === 'ENOENT' ? ' (is uv installed? https://docs.astral.sh/uv/)' : ''
      reject(new Error(`could not start the backend${hint}: ${err.message}`))
    })
  })
  spawnFailed.catch(() => {})
  earlyExit.catch(() => {}) // handled via the race below; avoid an unhandled rejection after success

  const healthy = (async () => {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline && !exited) {
      try {
        const res = await doFetch(`${baseUrl}/health`, {
          headers: { 'X-Session-Token': token },
          signal: AbortSignal.timeout(Math.max(pollMs, 1_000))
        })
        if (res.ok) return
      } catch {
        // Not listening yet; keep polling.
      }
      await sleep(pollMs)
    }
    // Reached on timeout, or because the child is gone (its own rejection wins the race).
    throw new Error(`backend did not become healthy within ${timeoutMs / 1000}s:\n${stderr}`)
  })()
  healthy.catch(() => {})

  try {
    await Promise.race([healthy, earlyExit, spawnFailed])
  } catch (err) {
    await stop()
    throw err
  }
  return { baseUrl, token, stop }
}
