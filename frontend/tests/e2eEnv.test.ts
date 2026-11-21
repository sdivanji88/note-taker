import { describe, expect, it } from 'vitest'
import { buildSandboxEnv } from '../e2e/helpers'

describe('buildSandboxEnv', () => {
  const polluted = {
    PATH: '/usr/bin:/bin',
    UV_CACHE_DIR: '/cache/uv',
    GIT_DIR: '/nonexistent',
    GIT_WORK_TREE: '/nonexistent',
    GIT_INDEX_FILE: '/nonexistent',
    GIT_ASKPASS: '/bin/true',
    GIT_SSH_COMMAND: 'ssh -i /real/key',
    GIT_CONFIG_COUNT: '1',
    SSH_AUTH_SOCK: '/tmp/agent.sock',
    ELECTRON_RUN_AS_NODE: '1',
    NOTE_TAKER_TOKEN: 'secret',
    NOTE_TAKER_BACKEND_DIR: '/real/backend',
    NOTE_TAKER_DATA_DIR: '/real/data'
  }
  const env = buildSandboxEnv(polluted, { home: '/tmp/h', dataDir: '/tmp/d' })

  it('drops developer git, ssh and app variables', () => {
    for (const k of ['GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_ASKPASS', 'GIT_SSH_COMMAND',
      'GIT_CONFIG_COUNT', 'SSH_AUTH_SOCK', 'ELECTRON_RUN_AS_NODE', 'NOTE_TAKER_TOKEN', 'NOTE_TAKER_BACKEND_DIR'])
      expect(env, k).not.toHaveProperty(k)
  })

  it('keeps what uv and node need', () => {
    expect(env.PATH).toBe('/usr/bin:/bin')
    expect(env.UV_CACHE_DIR).toBe('/cache/uv')
  })

  it('applies the hermetic overrides', () => {
    expect(env).toMatchObject({
      HOME: '/tmp/h',
      NOTE_TAKER_DATA_DIR: '/tmp/d',
      GIT_CONFIG_GLOBAL: '/dev/null',
      GIT_CONFIG_SYSTEM: '/dev/null',
      GIT_CONFIG_NOSYSTEM: '1',
      GIT_TERMINAL_PROMPT: '0'
    })
    expect(env.GIT_AUTHOR_EMAIL).toContain('example.invalid')
    expect(env.GIT_COMMITTER_NAME).toBeTruthy()
  })
})
