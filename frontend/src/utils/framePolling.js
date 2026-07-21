// B451: Follow-Latest-Auswahl fuer die Karten-Polls.
// Reine Funktion -> deterministisch testbar (analog riskGridPolling.js).
//
// "Folgen" bedeutet: der Nutzer stand auf dem bislang neuesten Frame (oder es ist
// der Erstaufruf). Dann wird nach dem Poll der ECHTE neueste Frame angezeigt --
// unabhaengig von latest_idx (das bewusst den letzten Frame OHNE fertige
// objects.json ausklammert). Eine bewusst gewaehlte aeltere Ansicht bleibt erhalten.
export function resolveFramePoll({ newFrames, viewedTs, lastNewestTs }) {
  const frames = Array.isArray(newFrames) ? newFrames : []
  const realLatestIdx = frames.length - 1
  if (realLatestIdx < 0) {
    return { targetIdx: -1, viewedTs: null, latestTs: null, wasFollowing: true }
  }
  const latestTs = frames[realLatestIdx]?.ts ?? null
  const wasFollowing = viewedTs == null || viewedTs === lastNewestTs
  let targetIdx = realLatestIdx
  if (!wasFollowing) {
    const keep = frames.findIndex((f) => f && f.ts === viewedTs)
    targetIdx = keep >= 0 ? keep : realLatestIdx
  }
  return {
    targetIdx,
    viewedTs: frames[targetIdx]?.ts ?? null,
    latestTs,
    wasFollowing,
  }
}
