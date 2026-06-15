/**
 * Storage helpers — lectures/ecritures JSON safe.
 *
 * Garanties :
 *  - writeJsonAtomic : ecrit dans un .tmp puis rename atomique. Pas de fichier tronque
 *    si le processus crash en plein write.
 *  - withFileLock : serialise les operations sur une meme cle (path) pour eviter
 *    qu'un read-modify-write soit ecrase par un autre.
 *
 * Usage :
 *   await withFileLock(file, () => {
 *     const data = readJson(file, []);
 *     data.push(...);
 *     writeJsonAtomic(file, data);
 *   });
 */

const fs   = require('fs');
const path = require('path');

const _locks = new Map(); // key -> Promise (chaine d'attente)

function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { return typeof fallback === 'function' ? fallback() : fallback; }
}

function writeJsonAtomic(file, data) {
  const dir = path.dirname(file);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const tmp = file + '.tmp.' + process.pid + '.' + Date.now();
  // ASCII-safe JSON (echappe les unicode hors ASCII pour eviter les problemes d'encodage)
  const json = JSON.stringify(data, null, 2)
    .replace(/[-￿]/g, c => '\\u' + ('0000' + c.charCodeAt(0).toString(16)).slice(-4));
  fs.writeFileSync(tmp, json, 'utf8');
  fs.renameSync(tmp, file);
}

async function withFileLock(key, fn) {
  const prev = _locks.get(key) || Promise.resolve();
  let release;
  const next = new Promise(r => { release = r; });
  _locks.set(key, prev.then(() => next));
  try {
    await prev;
    return await fn();
  } finally {
    release();
    // Nettoyage : si on est le dernier maillon, retire la cle
    if (_locks.get(key) === next) _locks.delete(key);
  }
}

module.exports = { readJson, writeJsonAtomic, withFileLock };
