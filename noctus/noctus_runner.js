#!/usr/bin/env node
/*
 * Runner CLI appelé par Flask :  node noctus_runner.js '<jsonargs>'
 *  - émet les logs + la progression en JSON-lines sur stdout
 *  - écrit data/<user>/models/<modelId>/_status.json (polling côté Flask)
 *  - sur SIGTERM/SIGINT : stoppe proprement le pipeline (tue les ffmpeg)
 *
 * jsonargs : {"modelId","userDir","selectedFolders"?,"selectedCaptions"?,"targetFiles"?}
 */
const path = require('path');
const fs = require('fs');
const { runPipeline, stopPipeline } = require('./pipeline-core');

let args = {};
try {
  args = JSON.parse(process.argv[2] || '{}');
} catch (e) {
  console.error('args JSON invalides:', e.message);
  process.exit(2);
}

const modelId = args.modelId;
const userDir = args.userDir;
const selectedFolders = args.selectedFolders || null;
const selectedCaptions = args.selectedCaptions || null;
const targetFiles = args.targetFiles || null;

if (!modelId || !userDir) {
  console.error('modelId + userDir requis');
  process.exit(2);
}

const statusFile = path.join(userDir, 'models', modelId, '_status.json');
function writeStatus(o) {
  try {
    fs.mkdirSync(path.dirname(statusFile), { recursive: true });
    fs.writeFileSync(statusFile, JSON.stringify(o));
  } catch (_) {}
}
function emit(o) {
  try { process.stdout.write(JSON.stringify(o) + '\n'); } catch (_) {}
}

writeStatus({ state: 'running', current: 0, total: 0, pct: 0, eta: null });

function log(msg) { emit({ type: 'log', msg: String(msg).slice(0, 2000) }); }
function notify(ev) {
  emit({ type: 'notify', event: ev });
  if (ev && ev.type === 'progress') {
    writeStatus({ state: 'running', current: ev.current, total: ev.total, pct: ev.pct, eta: ev.eta });
  }
}

let stopping = false;
function gracefulStop() {
  if (stopping) return;
  stopping = true;
  try { stopPipeline(modelId); } catch (_) {}
  writeStatus({ state: 'stopped' });
  setTimeout(() => process.exit(0), 1500);
}
process.on('SIGTERM', gracefulStop);
process.on('SIGINT', gracefulStop);

(async () => {
  try {
    await runPipeline(modelId, log, selectedFolders, notify, selectedCaptions, userDir, null, null, targetFiles);
    if (!stopping) { writeStatus({ state: 'done', pct: 100 }); emit({ type: 'done' }); }
    process.exit(0);
  } catch (e) {
    writeStatus({ state: 'error', error: String((e && e.message) || e) });
    emit({ type: 'error', error: String((e && e.message) || e) });
    process.exit(1);
  }
})();
