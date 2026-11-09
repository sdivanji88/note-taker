import { EventEmitter } from 'node:events'
import net from 'node:net'
import { describe, expect, it, vi } from 'vitest'
import { pickFreePort, startBackend } from '../electron/main/backend'

// A stand-in for the uv child: emits stderr/exit and records signals, never runs anything.
class FakeChild extends EventEmitter {
  stderr = new EventEmitter()
  exitCode: number | null = null
  signalCode: string | null = null
  signals: string[] = []
  pid = 4242
  // dies: the signal that ends the process (undefined = ignores every signal).
  constructor(private dies?: string) {
    super()
  }
  kill(signal: string) {
    this.signals.push(signal)
    if (this.dies === signal) this.die(null, signal)
    return true
  }
  die(code: number | null, signal: string | null = null) {
    this.exitCode = code
    this.signalCode = signal
    this.emit('exit', code, signal)
  }
}

const opts = { backendDir: '/b', dataDir: '/d' }
const ok = () => new Response('{}', { status: 200 })

// The backend lives in its own process group (uv forwards SIGTERM but cannot forward
// SIGKILL), so tests observe signals sent to the group: kill(-pid, sig).
function setup(child: FakeChild, fetchImpl: unknown, extra: Record<string, unknown> = {}) {
  const spawn = vi.fn(() => child)
  const kill = vi.fn((pid: number, signal: string) => {
    if (pid !== -child.pid) throw new Error(`signalled ${pid}, expected the group -${child.pid}`)
    child.kill(signal)
  })
  const deps = {
    kill: kill as never,
    spawn: spawn as never,
    fetch: fetchImpl as typeof fetch,
    pollMs: 5,
    timeoutMs: 100,
    killGraceMs: 20,
    ...extra
  }
  return { spawn, kill, deps }
}

describe('pickFreePort', () => {
  it('returns a port that can be bound on 127.0.0.1 right after', async () => {
    const port = await pickFreePort()
    expect(port).toBeGreaterThan(0)
    await new Promise<void>((resolve, reject) => {
      const s = net.createServer().once('error', reject)
      s.listen(port, '127.0.0.1', () => s.close(() => resolve()))
    })
  })
})

describe('startBackend', () => {
  it('spawns uv with the token only in the environment and resolves once /health answers', async () => {
    const child = new FakeChild()
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error('refused')).mockResolvedValue(ok())
    const { spawn, deps } = setup(child, fetchMock)
    const b = await startBackend(opts, deps)

    const [cmd, args, spawnOpts] = spawn.mock.calls[0] as unknown as [
      string,
      string[],
      { env: Record<string, string> }
    ]
    expect(cmd).toBe('uv')
    expect(args.slice(0, 5)).toEqual(['run', '--project', '/b', 'python', '-m'])
    expect(args).toContain('note_taker')
    expect(args[args.indexOf('--data-dir') + 1]).toBe('/d')
    expect(b.token).toMatch(/^[0-9a-f]{64}$/)
    expect(args.join(' ')).not.toContain(b.token)
    expect(args).not.toContain('--token')
    expect(spawnOpts.env.NOTE_TAKER_TOKEN).toBe(b.token)

    const port = Number(args[args.indexOf('--port') + 1])
    expect(b.baseUrl).toBe(`http://127.0.0.1:${port}`)
    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toBe(`${b.baseUrl}/health`)
    expect(new Headers(init.headers).get('X-Session-Token')).toBe(b.token)
  })

  it('rejects with the captured stderr when /health never answers', async () => {
    const child = new FakeChild('SIGTERM')
    const { spawn, deps } = setup(child, vi.fn().mockRejectedValue(new Error('refused')), { timeoutMs: 300 })
    const p = startBackend(opts, deps)
    await vi.waitFor(() => expect(spawn).toHaveBeenCalled()) // port lookup is async
    child.stderr.emit('data', Buffer.from('ModuleNotFoundError: boom'))
    await expect(p).rejects.toThrow(/did not become healthy.*ModuleNotFoundError: boom/s)
    expect(child.signals).toContain('SIGTERM') // a failed start must not leak a child
  })

  it('rejects immediately with exit code and stderr when the child exits early', async () => {
    const child = new FakeChild()
    const { spawn, deps } = setup(child, vi.fn().mockRejectedValue(new Error('refused')), {
      timeoutMs: 60_000
    })
    const p = startBackend(opts, deps)
    await vi.waitFor(() => expect(spawn).toHaveBeenCalled()) // port lookup is async
    child.stderr.emit('data', Buffer.from('uv: command failed'))
    child.die(2)
    await expect(p).rejects.toThrow(/exited with code 2.*uv: command failed/s)
  })

  it('keeps only the last 8 KB of stderr in the failure message', async () => {
    const child = new FakeChild()
    const { spawn, deps } = setup(child, vi.fn().mockRejectedValue(new Error('refused')), {
      timeoutMs: 60_000
    })
    const p = startBackend(opts, deps)
    await vi.waitFor(() => expect(spawn).toHaveBeenCalled()) // port lookup is async
    child.stderr.emit('data', Buffer.from('HEAD-MARKER' + 'x'.repeat(20_000)))
    child.stderr.emit('data', Buffer.from('TAIL-MARKER'))
    child.die(1)
    const err = (await p.catch((e: Error) => e)) as Error
    expect(err.message).toContain('TAIL-MARKER')
    expect(err.message).not.toContain('HEAD-MARKER')
    expect(err.message.length).toBeLessThan(9_000)
  })

  it('stop() sends SIGTERM once, however often it is called', async () => {
    const child = new FakeChild('SIGTERM')
    const { spawn, deps } = setup(child, vi.fn().mockResolvedValue(ok()))
    const b = await startBackend(opts, deps)
    await Promise.all([b.stop(), b.stop()])
    await b.stop()
    expect(child.signals).toEqual(['SIGTERM'])
  })

  it('stop() escalates to SIGKILL when the child ignores SIGTERM', async () => {
    const child = new FakeChild('SIGKILL')
    const { spawn, deps } = setup(child, vi.fn().mockResolvedValue(ok()))
    const b = await startBackend(opts, deps)
    await b.stop()
    expect(child.signals).toEqual(['SIGTERM', 'SIGKILL'])
  })

  it('stop() does not signal a child that already exited', async () => {
    const child = new FakeChild()
    const { spawn, deps } = setup(child, vi.fn().mockResolvedValue(ok()))
    const b = await startBackend(opts, deps)
    child.die(0)
    await b.stop()
    expect(child.signals).toEqual([])
  })
})

describe('process group handling', () => {
  it('spawns detached with an open stdin pipe and the exit-on-stdin-eof flag', async () => {
    const { spawn, deps } = setup(new FakeChild(), vi.fn().mockResolvedValue(ok()))
    await startBackend(opts, deps)
    const [, args, o] = spawn.mock.calls[0] as unknown as [string, string[], { detached: boolean; stdio: unknown[] }]
    expect(o.detached).toBe(true)
    expect(o.stdio[0]).toBe('pipe')
    expect(args).toContain('--exit-on-stdin-eof')
  })

  it('stop() signals the process group for TERM and for the KILL escalation', async () => {
    const child = new FakeChild('SIGKILL')
    const { kill, deps } = setup(child, vi.fn().mockResolvedValue(ok()))
    const b = await startBackend(opts, deps)
    await b.stop()
    expect(kill.mock.calls).toEqual([
      [-4242, 'SIGTERM'],
      [-4242, 'SIGKILL']
    ])
  })

  it('treats ESRCH (group already gone) as success', async () => {
    const child = new FakeChild()
    const { deps } = setup(child, vi.fn().mockResolvedValue(ok()), {
      kill: () => {
        child.die(0)
        throw Object.assign(new Error('no such process'), { code: 'ESRCH' })
      }
    })
    const b = await startBackend(opts, deps)
    await expect(b.stop()).resolves.toBeUndefined()
  })

  it('the synchronous process-exit hook also signals the group', async () => {
    const once = vi.spyOn(process, 'once')
    const child = new FakeChild()
    const { kill, deps } = setup(child, vi.fn().mockResolvedValue(ok()))
    await startBackend(opts, deps)
    const hook = once.mock.calls.find(([ev]) => ev === 'exit')![1] as () => void
    once.mockRestore()
    hook()
    expect(kill).toHaveBeenCalledWith(-4242, 'SIGTERM')
    child.die(0) // lets the listener clean itself up
  })
})
