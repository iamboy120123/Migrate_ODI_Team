export const meta = {
  name: 'phase4-review',
  description: 'Phase 4: per flagged task run sql-reviewer + semantic-verifier in parallel, then test-designer proposals; returns rows for status/PHASE4_REVIEW_LOG.md (read-only)',
  whenToUse: 'Phase 4 with several flagged tasks in status/REVIEW_FLAGS.md. args = ["<task_id>", ...] or omit to review every task in status/REVIEW_FLAGS.md',
  phases: [
    { title: 'Discover', detail: 'list flagged tasks from status/REVIEW_FLAGS.md (skipped when args given)' },
    { title: 'Review', detail: 'sql-reviewer and semantic-verifier per task, in parallel' },
    { title: 'Test design', detail: 'test-designer proposes cases for tasks with DIFF / NEEDS-D1 (no files written)' },
  ],
}

const TASKS = { type: 'object', properties: { tasks: { type: 'array', items: { type: 'string' } } }, required: ['tasks'] }
const ROW = {
  type: 'object',
  properties: {
    issue: { type: 'string' }, finding: { type: 'string' }, fix: { type: 'string' },
    changes_semantics: { type: 'string', enum: ['ใช่', 'ไม่', 'ไม่แน่ใจ'] },
    decision_ref: { type: 'string' },
    proposed_status: { type: 'string', enum: ['OPEN', 'FIXED', 'ACCEPTED', 'NO_CHANGE'] },
  },
  required: ['issue', 'finding', 'fix', 'changes_semantics', 'proposed_status'],
}
const REVIEW = { type: 'object', properties: { rows: { type: 'array', items: ROW } }, required: ['rows'] }
const VERDICT = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'DIFF', 'NEEDS-D1'] },
    counter_examples: { type: 'array', items: { type: 'string' } },
    test_cases: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdict', 'counter_examples', 'test_cases'],
}

let tasks = Array.isArray(args) ? args : []
if (!tasks.length) {
  phase('Discover')
  const d = await agent('Read status/REVIEW_FLAGS.md and return every distinct Task ID whose Status is PENDING (exact ids as written). Read-only.',
    { label: 'discover', phase: 'Discover', schema: TASKS, effort: 'low' })
  tasks = (d && d.tasks) || []
}
if (!tasks.length) { log('ไม่มี task ที่ถูก flag — ไม่ต้อง review'); return { tasks: [], results: [] } }
log(`review ${tasks.length} task`)

const files = t => `raw: output/sql/raw/${t}.sql · converted: output/sql/converted/${t}.sql · flags: rows of ${t} in status/REVIEW_FLAGS.md`

const results = await pipeline(
  tasks,
  t => parallel([
    () => agent(`Review task ${t} (${files(t)}). Return one row per issue for status/PHASE4_REVIEW_LOG.md. Do not edit files. proposed_status ACCEPTED only when a closed Q/ADR already covers it (put it in decision_ref).`,
      { label: `review:${t}`, phase: 'Review', agentType: 'sql-reviewer', schema: REVIEW }),
    () => agent(`Adversarially verify task ${t} (${files(t)}). Try to find inputs where Spark and Oracle results differ. Do not edit files.`,
      { label: `verify:${t}`, phase: 'Review', agentType: 'semantic-verifier', schema: VERDICT }),
  ]).then(([review, verdict]) => ({ task: t, review, verdict })),
  r => (r.verdict && r.verdict.verdict !== 'PASS')
    ? agent(`Propose (do NOT write files) test cases for task ${r.task} covering: ${JSON.stringify(r.verdict.counter_examples.concat(r.verdict.test_cases)).slice(0, 3000)}. Return a markdown table case | input | expected | source line.`,
        { label: `tests:${r.task}`, phase: 'Test design', agentType: 'test-designer' }).then(tests => ({ ...r, tests }))
    : { ...r, tests: null },
)

return {
  tasks,
  results: results.filter(Boolean).map(r => ({
    task: r.task,
    semantic_verifier: r.verdict ? r.verdict.verdict : '-',
    rows: (r.review && r.review.rows) || [],
    counter_examples: r.verdict ? r.verdict.counter_examples : [],
    tests: r.tests,
  })),
  next: 'main agent: apply FIX edits in output/sql/converted/, write rows to status/PHASE4_REVIEW_LOG.md, open /decide for changes_semantics=ใช่, then check_gate.py G2',
}
