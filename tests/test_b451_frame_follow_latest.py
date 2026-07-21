import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_resolve_frame_poll_behaviour():
    script = r'''
import assert from 'node:assert/strict';
import { resolveFramePoll } from './frontend/src/utils/framePolling.js';

const F = (ts, has) => ({ ts, has_objects_file: !!has });

// 1) Erstaufruf: viewedTs=null -> neuester Frame
let r = resolveFramePoll({
  newFrames: [F('a', true), F('b', true), F('c', false)],
  viewedTs: null,
  lastNewestTs: null,
});
assert.equal(r.targetIdx, 2);
assert.equal(r.viewedTs, 'c');
assert.equal(r.latestTs, 'c');
assert.equal(r.wasFollowing, true);

// 2) Live-Folgen, kein neuer Frame -> bleibt auf neuestem
r = resolveFramePoll({
  newFrames: [F('a', true), F('b', true), F('c', true)],
  viewedTs: 'c',
  lastNewestTs: 'c',
});
assert.equal(r.targetIdx, 2);

// 3) KERN: Live-Folgen, neuer (noch nicht analysierter) Frame kommt an
//    -> springt auf den ECHTEN neuesten Frame, NICHT auf den vorletzten.
r = resolveFramePoll({
  newFrames: [F('b', true), F('c', true), F('d', false)],
  viewedTs: 'c',
  lastNewestTs: 'c',
});
assert.equal(r.targetIdx, 2);
assert.equal(r.viewedTs, 'd');
assert.equal(r.wasFollowing, true);

// 4) Manuelle aeltere Auswahl bleibt erhalten (ts noch im Fenster)
r = resolveFramePoll({
  newFrames: [F('b', true), F('c', true), F('d', true)],
  viewedTs: 'b',
  lastNewestTs: 'c',
});
assert.equal(r.targetIdx, 0);
assert.equal(r.viewedTs, 'b');
assert.equal(r.wasFollowing, false);

// 5) Manuelle Auswahl aus dem Fenster gefallen -> Fallback neuester
r = resolveFramePoll({
  newFrames: [F('c', true), F('d', true), F('e', true)],
  viewedTs: 'a',
  lastNewestTs: 'c',
});
assert.equal(r.targetIdx, 2);
assert.equal(r.wasFollowing, false);

// 6) Leeres Fenster
r = resolveFramePoll({ newFrames: [], viewedTs: 'x', lastNewestTs: 'x' });
assert.equal(r.targetIdx, -1);
assert.equal(r.latestTs, null);

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


def test_map_pages_use_follow_latest_and_drop_latest_idx_jump():
    for rel in ["frontend/src/pages/MapView.jsx", "frontend/src/pages/MapFullscreen.jsx"]:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "resolveFramePoll" in src, rel
        assert "from '../utils/framePolling.js'" in src, rel
        assert "setCurrentIdx(latestIdx)" not in src, rel
        assert "`/api/objects?ts=${latestTs}`" not in src, rel
        assert "`/api/forecast?ts=${latestTs}`" not in src, rel
        assert "if (frame.has_objects_file)" in src, rel
