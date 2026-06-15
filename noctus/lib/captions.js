/**
 * Captions store — captions.json par utilisateur, avec migration auto depuis
 * l'ancien format captions.js (CommonJS module exportant un tableau).
 *
 * Le fichier .js est lu une derniere fois si .json absent, le contenu est
 * copie dans .json puis le .js est laisse en place (compat retro pendant la
 * transition). Au prochain ecriture, seul le .json est touche.
 */

const fs   = require('fs');
const path = require('path');
const { readJson, writeJsonAtomic, withFileLock } = require('./storage');

function captionsJsonFile(userDataDir) { return path.join(userDataDir, 'captions.json'); }
function captionsJsFile(userDataDir)   { return path.join(userDataDir, 'captions.js');   }

/**
 * Lit les captions d'un user. Migre de .js vers .json si necessaire.
 * @returns {Array}
 */
function read(userDataDir) {
  const jsonF = captionsJsonFile(userDataDir);
  if (fs.existsSync(jsonF)) return readJson(jsonF, []);

  // Migration douce depuis captions.js — require() veut un chemin absolu
  const jsF = path.resolve(captionsJsFile(userDataDir));
  if (fs.existsSync(jsF)) {
    try {
      delete require.cache[require.resolve(jsF)];
      const arr = require(jsF);
      if (Array.isArray(arr)) {
        writeJsonAtomic(jsonF, arr);
        return arr;
      }
    } catch (e) {
      console.warn(`[captions] migration .js->.json echouee (${jsF}):`, e.message);
    }
  }
  return [];
}

async function write(userDataDir, data) {
  if (!Array.isArray(data)) throw new Error('captions: data must be an array');
  const jsonF = captionsJsonFile(userDataDir);
  await withFileLock(jsonF, () => writeJsonAtomic(jsonF, data));
}

/** Initialise un fichier captions.json vide si absent (et pas de .js a migrer). */
function initIfMissing(userDataDir) {
  const jsonF = captionsJsonFile(userDataDir);
  if (fs.existsSync(jsonF)) return;
  if (fs.existsSync(captionsJsFile(userDataDir))) return; // sera migre a la 1ere lecture
  writeJsonAtomic(jsonF, []);
}

module.exports = { read, write, initIfMissing, captionsJsonFile, captionsJsFile };
