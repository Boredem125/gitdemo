// Shared contracts between analyzer, runner, api and web.
// Keep this file free of runtime dependencies so every package (including the browser) can import it.

// ---------------------------------------------------------------------------
// Analyzer input
// ---------------------------------------------------------------------------

export interface RepoEntry {
  /** POSIX path relative to repo root, no leading slash. */
  path: string;
  /** Size in bytes. */
  size: number;
}

/** What the analyzer sees: every path, plus UTF-8 text of small text files. */
export interface RepoSnapshot {
  entries: RepoEntry[];
  /** path -> UTF-8 content. Only text files <= MAX_TEXT_FILE_BYTES; binaries and large files are absent. */
  contents: Record<string, string>;
}

export const MAX_TEXT_FILE_BYTES = 512 * 1024;

// ---------------------------------------------------------------------------
// Analyzer output
// ---------------------------------------------------------------------------

export type Ecosystem =
  | 'node'
  | 'static'
  | 'python'
  | 'go'
  | 'rust'
  | 'java'
  | 'php'
  | 'ruby'
  | 'dotnet'
  | 'docker'
  | 'unknown';

export interface StackDetection {
  ecosystem: Ecosystem;
  /** e.g. 'next', 'vite', 'express', 'flask', 'django', 'streamlit', 'spring-boot', 'laravel', 'rails'. */
  framework?: string;
  /** Directory the stack lives in, relative to repo root. '' = root. */
  root: string;
  /** 0..1 */
  confidence: number;
  /** Human-readable reasons, e.g. "package.json depends on next@14". */
  evidence: string[];
}

export interface LanguageShare {
  language: string;
  bytes: number;
  /** 0..100, one decimal. */
  percent: number;
}

export interface EnvVarRef {
  name: string;
  /** File where it was found. */
  source: string;
  /** True when no default/example value is known. */
  required: boolean;
  example?: string;
}

export type WarningCode =
  | 'needs-database'
  | 'needs-secrets'
  | 'amd64-only'
  | 'gpu'
  | 'native-deps'
  | 'monorepo'
  | 'compose-partial'
  | 'no-entrypoint'
  | 'large-repo'
  | 'not-a-web-app';

export interface AnalysisWarning {
  code: WarningCode;
  message: string;
}

export type BuildStrategy = 'repo-dockerfile' | 'template' | 'compose-single' | 'unsupported';

export interface BuildPlan {
  strategy: BuildStrategy;
  /** Build context dir relative to repo root ('' = root). */
  contextDir: string;
  /** For repo-dockerfile / compose-single: Dockerfile path relative to repo root. */
  dockerfilePath?: string;
  /** For template: generated Dockerfile content (written into contextDir as Dockerfile.gitdemo). */
  dockerfile?: string;
  /** Candidate ports the app may listen on, most likely first. Runner probes in order. */
  ports: number[];
  /** Env vars to inject at run time (always includes PORT and HOST=0.0.0.0 for templates). */
  env: Record<string, string>;
  /** Why this strategy was chosen (shown in UI). */
  reason: string;
}

export interface RepoAnalysis {
  /** Primary stack (first of `stacks`) or unknown. */
  primary: StackDetection;
  /** All detected stacks, best first. */
  stacks: StackDetection[];
  languages: LanguageShare[];
  /** Runnable scripts, e.g. package.json scripts or Makefile targets. name -> command */
  scripts: Record<string, string>;
  /** Top-level dependency names grouped by manifest file. */
  dependencies: Record<string, string[]>;
  envVars: EnvVarRef[];
  /** Path of README file if any. */
  readmePath?: string;
  /** Likely entry point files. */
  entryPoints: string[];
  warnings: AnalysisWarning[];
  build: BuildPlan;
  /** Steps to run locally after cloning, e.g. ["npm install", "npm run dev"]. */
  runInstructions: string[];
  fileCount: number;
  totalBytes: number;
}

// ---------------------------------------------------------------------------
// API payloads
// ---------------------------------------------------------------------------

export interface RepoRef {
  owner: string;
  name: string;
  /** Branch/tag/sha requested, or the default branch. */
  ref: string;
}

export interface RepoMeta extends RepoRef {
  sha: string;
  defaultBranch: string;
  description?: string;
  stars?: number;
  license?: string;
  htmlUrl: string;
}

export interface AnalyzeRequest {
  url: string;
}

export interface AnalyzeResponse {
  repo: RepoMeta;
  analysis: RepoAnalysis;
  tree: RepoEntry[];
  /** README text if present (already in snapshot, sent for convenience). */
  readme?: string;
}

export type DemoStatus = 'queued' | 'building' | 'starting' | 'running' | 'failed' | 'expired' | 'stopped';

export const TERMINAL_STATUSES: readonly DemoStatus[] = ['failed', 'expired', 'stopped'];

export interface Demo {
  id: string;
  sha: string;
  /** owner/name */
  repo: string;
  status: DemoStatus;
  url?: string;
  error?: string;
  /** epoch ms */
  createdAt: number;
  startedAt?: number;
  expiresAt?: number;
  extended: boolean;
  /** Position in queue when status=queued (1-based). */
  queuePosition?: number;
}

export interface CreateDemoRequest {
  url: string;
}

export interface CreateDemoResponse {
  demo: Demo;
}

export type LogStream = 'system' | 'build' | 'run';

export interface LogEvent {
  /** epoch ms */
  ts: number;
  stream: LogStream;
  line: string;
}

/** SSE on GET /api/demos/:id/logs. Event names: 'log' (data: LogEvent), 'status' (data: Demo), 'end'. */
export type DemoSseEvent = { event: 'log'; data: LogEvent } | { event: 'status'; data: Demo } | { event: 'end'; data: null };

export interface ApiError {
  error: string;
  code?: string;
}

// ---------------------------------------------------------------------------
// Runner contract (implemented by @gitdemo/runner, consumed by @gitdemo/api)
// ---------------------------------------------------------------------------

export interface RunnerJob {
  demoId: string;
  /** Absolute path of the extracted repo on disk. */
  srcDir: string;
  plan: BuildPlan;
  /** Hostname the demo will be served on, e.g. "ab12cd.localhost" or "ab12cd.1-2-3-4.sslip.io". */
  host: string;
}

export interface RunnerStatusPatch {
  url?: string;
  error?: string;
  startedAt?: number;
  expiresAt?: number;
}

export interface RunnerEvents {
  onLog(event: LogEvent): void;
  onStatus(status: DemoStatus, patch?: RunnerStatusPatch): void;
}

export interface RunnerConfig {
  /** Docker API, e.g. "http://socket-proxy:2375" or undefined for local default socket. */
  dockerHost?: string;
  /** 'runsc' in production, 'runc' for local dev. */
  sandboxRuntime: string;
  /** Docker network demos attach to (Traefik must share it). */
  demoNetwork: string;
  /** Scheme for generated demo URLs. */
  publicScheme: 'http' | 'https';
  maxLiveDemos: number;
  maxConcurrentBuilds: number;
  ttlMinutes: number;
  buildTimeoutMinutes: number;
  /** Seconds to wait for a port to answer after container start. */
  probeTimeoutSeconds: number;
  /** Per-demo limits. */
  cpus: number;
  memoryMb: number;
  pidsLimit: number;
}

export interface Runner {
  /** Enqueue a build+run. Status/log updates arrive via events. */
  submit(job: RunnerJob, events: RunnerEvents): void;
  /** Stop and remove a demo (container + image). */
  stop(demoId: string): Promise<void>;
  /** Extend TTL once. Returns new expiresAt (epoch ms) or throws if not allowed. */
  extend(demoId: string): Promise<number>;
  /** Number of running + starting demos. */
  liveCount(): number;
  /** 1-based queue position, or undefined if not queued. */
  queuePosition(demoId: string): number | undefined;
  /** Start reaper loop and clean up orphans from a previous process. */
  start(): Promise<void>;
  /** Stop reaper loop (does not kill demos). */
  close(): Promise<void>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Label applied to every Docker object the runner creates. */
export const DEMO_LABEL = 'gitdemo.demo';
