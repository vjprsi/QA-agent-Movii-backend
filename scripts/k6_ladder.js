// k6 variable-TPS ladder for the QA agent.
//
//   LADDER="1,3,1,5,2,3" STEP_SECONDS=60 BASE_URL=https://api-test... \
//   P95_MS=800 ERR_MAX=0.01 REQUESTS=docs/<svc>/<run>/stress/requests.json RUN_TAG=<run> \
//   k6 run scripts/k6_ladder.js --summary-export k6-summary.json --out json=k6-results.json
//
// SPIKE=1  → LADDER is "0,<max>,<max>,0" with STEP_SECONDS="5,60,5,30" (per-stage durations)
// MAX_VUS  → cap on pre-allocated VUs (default 50). Arrival-rate executor = exact TPS.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';

const LADDER = (__ENV.LADDER || '1,3,1,5,2,3').split(/[,\s;]+/).filter(Boolean).map(Number);
const STEPS = (__ENV.STEP_SECONDS || '60').split(/[,\s;]+/).filter(Boolean).map(Number);
const P95 = Number(__ENV.P95_MS || 800);
const P99 = Number(__ENV.P99_MS || P95 * 2);
const ERR_MAX = Number(__ENV.ERR_MAX || 0.01);
const RUN_TAG = __ENV.RUN_TAG || 'qa-run';
const MAX_VUS = Number(__ENV.MAX_VUS || 50);
const MAX_TPS = Number(__ENV.MAX_TPS || Math.max(...LADDER));

const requests = new SharedArray('requests', () => JSON.parse(open(__ENV.REQUESTS || './requests.json')).requests);

// Build stages: each ladder value is held for its step duration; ramp between values takes 5 s.
function buildStages() {
  const stages = [];
  LADDER.forEach((tps, i) => {
    const target = Math.min(tps, MAX_TPS);
    const dur = STEPS[i] !== undefined ? STEPS[i] : STEPS[STEPS.length - 1];
    if (i > 0 && !__ENV.SPIKE) stages.push({ target, duration: '5s' });   // ramp
    stages.push({ target, duration: `${dur}s` });                           // hold
  });
  stages.push({ target: 0, duration: '30s' });                              // recovery window
  return stages;
}

export const options = {
  scenarios: {
    ladder: {
      executor: 'ramping-arrival-rate',
      startRate: LADDER[0] || 1,
      timeUnit: '1s',
      preAllocatedVUs: Math.min(MAX_VUS, Math.max(5, MAX_TPS * 3)),
      maxVUs: MAX_VUS,
      stages: buildStages(),
      tags: { run: RUN_TAG },
    },
  },
  thresholds: {
    http_req_failed: [{ threshold: `rate<${ERR_MAX}`, abortOnFail: false }],
    http_req_duration: [`p(95)<${P95}`, `p(99)<${P99}`],
    'http_req_duration{expected_response:true}': [`p(95)<${P95}`],
  },
  summaryTrendStats: ['min', 'avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  insecureSkipTLSVerify: true,
  discardResponseBodies: false,
};

const stepTrend = new Trend('step_duration_ms', true);
const stepErrors = new Rate('step_error_rate');
const byStatus = new Counter('responses_by_status');

// which ladder step are we in? (derived from elapsed time)
const stepStarts = (() => {
  let t = 0; const arr = [];
  LADDER.forEach((_, i) => { if (i > 0 && !__ENV.SPIKE) t += 5; arr.push(t); t += (STEPS[i] !== undefined ? STEPS[i] : STEPS[STEPS.length - 1]); });
  return arr;
})();
const t0 = Date.now();
function currentStep() {
  const el = (Date.now() - t0) / 1000;
  let s = 0; for (let i = 0; i < stepStarts.length; i++) if (el >= stepStarts[i]) s = i;
  return s;
}

export default function () {
  const r = requests[Math.floor(Math.random() * requests.length)];
  const step = currentStep();
  const uniq = `${RUN_TAG}-${__VU}-${__ITER}-${Date.now()}`;
  const body = r.body ? r.body.replace(/\$\{uniq\}/g, uniq) : null;
  const headers = Object.assign({ 'Content-Type': 'application/json', 'X-QA-Run': RUN_TAG, 'X-QA-Step': String(step) }, r.headers || {});
  const params = { headers, tags: { name: r.name, step: String(step), tps: String(LADDER[step]) }, timeout: '15s' };

  const res = http.request(r.method, r.url, body, params);
  const ok = check(res, {
    'status is 2xx/4xx-expected': (x) => x.status >= 200 && x.status < 500,
    'no 5xx': (x) => x.status < 500,
    'has body': (x) => x.body && x.body.length > 0,
  });
  stepTrend.add(res.timings.duration, { step: String(step) });
  stepErrors.add(res.status >= 500 || res.status === 0, { step: String(step) });
  byStatus.add(1, { status: String(res.status) });
  if (!ok) console.warn(`[step ${step}] ${r.method} ${r.name} → ${res.status} ${res.timings.duration.toFixed(0)}ms`);
  sleep(0.01);
}

export function handleSummary(data) {
  const out = { ladder: LADDER, step_seconds: STEPS, p95_sla_ms: P95, err_max: ERR_MAX, run: RUN_TAG, metrics: data.metrics,
                thresholds_passed: Object.values(data.metrics).every(m => !m.thresholds || Object.values(m.thresholds).every(t => t.ok)) };
  return { stdout: JSON.stringify({ thresholds_passed: out.thresholds_passed }, null, 2) + '\n',
           [__ENV.SUMMARY_PATH || 'k6-handle-summary.json']: JSON.stringify(out, null, 2) };
}
