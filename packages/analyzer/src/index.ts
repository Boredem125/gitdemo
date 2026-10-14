import type { RepoAnalysis, RepoSnapshot } from '@gitdemo/shared';

/** Pure, synchronous, no I/O. Implemented in workstream 1. */
export function analyze(snapshot: RepoSnapshot): RepoAnalysis {
  throw new Error('analyze() not implemented');
}
