import { execFileSync, spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { deflateSync } from 'node:zlib'

// Everything a test touches lives under one throwaway root: data dir, bare "remote",
// HOME. Nothing here may reach the user's real userData dir, notes repo or git config.
export interface Sandbox {
  root: string
  dataDir: string
  bare: string
  env: Record<string, string>
}

export function createSandbox(): Sandbox {
  // realpath: macOS tmpdir is a symlink, and `pgrep -f` matches the resolved path.
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'nt-e2e-')))
  const dataDir = join(root, 'data')
  const home = join(root, 'home')
  const bare = join(root, 'remote.git')
  mkdirSync(dataDir)
  mkdirSync(home)

  // Overriding HOME and nulling the config files stops the user's identity, hooks and
  // credential helpers from leaking in; the author vars give commits a stable identity.
  const env: Record<string, string> = {
    ...(process.env as Record<string, string>),
    HOME: home,
    NOTE_TAKER_DATA_DIR: dataDir,
    GIT_CONFIG_GLOBAL: '/dev/null',
    GIT_CONFIG_SYSTEM: '/dev/null',
    GIT_CONFIG_NOSYSTEM: '1',
    GIT_TERMINAL_PROMPT: '0',
    GIT_AUTHOR_NAME: 'E2E Author',
    GIT_AUTHOR_EMAIL: 'e2e-author@example.invalid',
    GIT_COMMITTER_NAME: 'E2E Committer',
    GIT_COMMITTER_EMAIL: 'e2e-committer@example.invalid'
  }
  // A real data dir must never be inherited from the developer's shell.
  delete env.NOTE_TAKER_BACKEND_DIR

  const sandbox = { root, dataDir, bare, env }
  git(sandbox, ['init', '--bare', '-b', 'main', bare])
  // The app clones the remote and pushes to main, so main needs a first commit.
  const seed = join(root, 'seed')
  git(sandbox, ['clone', bare, seed])
  git(sandbox, ['-C', seed, 'checkout', '-b', 'main'])
  writeFileSync(join(seed, 'README.md'), '# notes\n')
  git(sandbox, ['-C', seed, 'add', 'README.md'])
  git(sandbox, ['-C', seed, 'commit', '-m', 'seed'])
  git(sandbox, ['-C', seed, 'push', 'origin', 'main'])
  rmSync(seed, { recursive: true, force: true })
  return sandbox
}

export function git(sb: Sandbox, args: string[]): string {
  return execFileSync('git', args, { env: sb.env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
}

export const gitBare = (sb: Sandbox, args: string[]) => git(sb, ['--git-dir', sb.bare, ...args])

export function writeSettings(sb: Sandbox, settings: object): void {
  writeFileSync(join(sb.dataDir, 'settings.json'), JSON.stringify(settings))
}

// Backends started by this sandbox are identified by its unique data dir, so another
// running Note Taker on the developer's machine is never matched or killed.
function backendPids(sb: Sandbox): string[] {
  const r = spawnSync('pgrep', ['-f', `note_taker.*--data-dir ${sb.dataDir}`], { encoding: 'utf8' })
  return r.stdout.split('\n').filter(Boolean)
}

export function killLeftoverBackends(sb: Sandbox): string[] {
  const pids = backendPids(sb)
  for (const pid of pids) {
    try {
      process.kill(Number(pid), 'SIGKILL')
    } catch {
      // Already gone.
    }
  }
  return pids
}

export function hasTesseract(): boolean {
  return spawnSync('which', ['tesseract']).status === 0
}

// ---- PNG fixtures: yellow highlight bar behind dark text, no image dependency ----

// 5x7 glyphs for just the letters the two fixture phrases use.
const GLYPHS: Record<string, string[]> = {
  A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
  C: ['01110', '10001', '10000', '10000', '10000', '10001', '01110'],
  D: ['11110', '10001', '10001', '10001', '10001', '10001', '11110'],
  E: ['11111', '10000', '10000', '11110', '10000', '10000', '11111'],
  H: ['10001', '10001', '10001', '11111', '10001', '10001', '10001'],
  I: ['01110', '00100', '00100', '00100', '00100', '00100', '01110'],
  L: ['10000', '10000', '10000', '10000', '10000', '10000', '11111'],
  M: ['10001', '11011', '10101', '10101', '10001', '10001', '10001'],
  O: ['01110', '10001', '10001', '10001', '10001', '10001', '01110'],
  R: ['11110', '10001', '10001', '11110', '10100', '10010', '10001'],
  S: ['01111', '10000', '10000', '01110', '00001', '00001', '11110'],
  T: ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
  U: ['10001', '10001', '10001', '10001', '10001', '10001', '01110'],
  W: ['10001', '10001', '10001', '10101', '10101', '11011', '10001'],
  Y: ['10001', '10001', '01010', '00100', '00100', '00100', '00100']
}

const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
  return c >>> 0
})
function crc32(buf: Buffer): number {
  let c = 0xffffffff
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}
function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const body = Buffer.concat([Buffer.from(type), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(body))
  return Buffer.concat([len, body, crc])
}

export function highlightedTextPng(text: string): Buffer {
  const scale = 5
  const pad = 30
  const width = text.length * 6 * scale + pad * 2
  const height = 7 * scale + pad * 2
  const rgb = Buffer.alloc(width * height * 3, 255)
  const put = (x: number, y: number, c: [number, number, number]) => rgb.set(c, (y * width + x) * 3)
  // The bar is taller than the glyphs so it reads as a highlighter stroke, like the real pages.
  for (let y = pad - 10; y < height - pad + 10; y++)
    for (let x = pad - 10; x < width - pad + 10; x++) put(x, y, [255, 235, 59])
  ;[...text].forEach((ch, i) => {
    const glyph = GLYPHS[ch]
    if (!glyph) return
    glyph.forEach((row, gy) =>
      [...row].forEach((bit, gx) => {
        if (bit !== '1') return
        for (let dy = 0; dy < scale; dy++)
          for (let dx = 0; dx < scale; dx++)
            put(pad + (i * 6 + gx) * scale + dx, pad + gy * scale + dy, [20, 20, 20])
      })
    )
  })
  const raw = Buffer.alloc(height * (width * 3 + 1))
  for (let y = 0; y < height; y++) {
    raw[y * (width * 3 + 1)] = 0
    rgb.copy(raw, y * (width * 3 + 1) + 1, y * width * 3, (y + 1) * width * 3)
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 2 // truecolor RGB
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0))
  ])
}
