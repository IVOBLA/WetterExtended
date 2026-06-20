import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_risk_grid_polling_helper_health_gate_backoff_and_log_suppression():
    script = r'''
import assert from 'node:assert/strict';
import {
  loadRiskGridAfterHealth,
  nextRiskGridBackoffMs,
  nextRiskGridDelayMs,
} from './frontend/src/utils/riskGridPolling.js';

assert.equal(nextRiskGridBackoffMs(0), 1000);
assert.equal(nextRiskGridBackoffMs(1000), 2000);
assert.equal(nextRiskGridBackoffMs(30000), 30000);

const state = { riskGridBackoffMs: 0, lastLoggedRiskGridError: null };
const calls = [];
const logs = [];
const refusedFetch = async (url) => {
  calls.push(url);
  throw new TypeError('Failed to fetch: ERR_CONNECTION_REFUSED');
};
const apiClient = { get: async () => { throw new Error('risk_grid must wait for health'); } };

let result = await loadRiskGridAfterHealth({
  apiClient,
  state,
  fetchImpl: refusedFetch,
  logger: (...args) => logs.push(args),
});
assert.equal(result.ok, false);
assert.deepEqual(calls, ['/api/health']);
assert.equal(state.riskGridBackoffMs, 1000);
assert.equal(nextRiskGridDelayMs(state), 1000);
assert.equal(logs.length, 1);

result = await loadRiskGridAfterHealth({
  apiClient,
  state,
  fetchImpl: refusedFetch,
  logger: (...args) => logs.push(args),
});
assert.equal(result.ok, false);
assert.equal(state.riskGridBackoffMs, 2000);
assert.equal(logs.length, 1);

let riskCalls = 0;
result = await loadRiskGridAfterHealth({
  apiClient: { get: async (url) => { riskCalls += 1; assert.equal(url, '/api/risk_grid'); return { cells: [{ risk: 2 }], grid_step: 0.05 }; } },
  state,
  fetchImpl: async (url) => { calls.push(url); return { ok: true }; },
  logger: (...args) => logs.push(args),
});
assert.equal(result.ok, true);
assert.equal(riskCalls, 1);
assert.equal(state.riskGridBackoffMs, 0);
assert.equal(nextRiskGridDelayMs(state), 60000);
console.log(JSON.stringify({ ok: true }));
'''
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(completed.stdout)["ok"] is True


def test_map_pages_use_health_gated_risk_grid_polling():
    for rel in ["frontend/src/pages/MapView.jsx", "frontend/src/pages/MapFullscreen.jsx"]:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "loadRiskGridAfterHealth" in src
        assert "nextRiskGridDelayMs" in src
        assert "setInterval(loadRisk, 60_000)" not in src
        assert "api.get('/api/risk_grid')" not in src
