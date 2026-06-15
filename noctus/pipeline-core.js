/**
 * PIPELINE-CORE.JS — Moteur de traitement vidéo (async, stoppable)
 * Rendu du texte via node-canvas — emojis Apple via PNG (samuelngs/apple-emoji-linux)
 * Anti-fingerprinting : nommage unique, grain, jitter, trim, métadonnées
 * Queue dynamique : ajout de dossiers pendant l'exécution
 */

const { spawn }                                = require('child_process');
const { createCanvas, GlobalFonts, loadImage } = require('@napi-rs/canvas');
const fs                                       = require('fs');
const path                                     = require('path');
const https                                    = require('https');
const http                                     = require('http');

// Config centrale (fallback si lib/config absent — le pipeline reste utilisable
// en standalone pour les tests locaux).
let APP_CONFIG = null;
try { APP_CONFIG = require('./lib/config'); } catch (_) { APP_CONFIG = null; }
const FONT_PATHS = APP_CONFIG?.FONT_PATHS || {
  bold: [
    'C:/Windows/Fonts/arialbd.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
  ],
  regular: [
    'C:/Windows/Fonts/arial.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
  ],
};

// ─── Config ───────────────────────────────────────────────────────────────────
const CONFIG = {
  fontSize:     44,
  fontColor:    'white',
  borderw:      3,
  borderColor:  'black',
  verticalY:    0.61,
  outputWidth:  1080,
  outputHeight: 1920,
  maxTextWidth: 720,
  boxPadH:      14,
  boxPadV:      9,
  boxRadius:    12,
  boxOpacity:   0.50,
  lineSpacing:  1.45,
};

// ── Polices texte ────────────────────────────────────────────────────────────
// Tente Windows puis Linux (premiere existante gagne, alias 'ArialBold' / 'LinuxBold').
function _registerFirst(paths, alias) {
  for (const p of paths) {
    try { if (fs.existsSync(p)) { GlobalFonts.registerFromPath(p, alias); return p; } }
    catch (_) {}
  }
  return null;
}
_registerFirst(FONT_PATHS.bold,    'ArialBold');
_registerFirst(FONT_PATHS.bold,    'LinuxBold');
_registerFirst(FONT_PATHS.regular, 'Arial');

// ── Polices custom (TTF dans /fonts/) — si presentes, registered au demarrage ──
const _CUSTOM_FONTS_DIR = path.join(__dirname, 'fonts');
const CUSTOM_FONTS = [
  { file: 'Inter-Bold.ttf',              family: 'Inter' },
  { file: 'Inter-Regular.ttf',           family: 'InterRegular' },
  { file: 'Inter-Medium.ttf',            family: 'InterMedium' },
  { file: 'Poppins-Bold.ttf',            family: 'Poppins' },
  { file: 'Montserrat-Bold.ttf',         family: 'Montserrat' },
  { file: 'BebasNeue-Regular.ttf',       family: 'BebasNeue' },
  { file: 'Anton-Regular.ttf',           family: 'Anton' },
  { file: 'TikTokSans-Bold.woff2',       family: 'TikTokSans' },
  { file: 'TikTokSans-Regular.woff2',    family: 'TikTokSansRegular' },
];
// Polices "regular" (poids leger) → ne pas appliquer 'bold' prefix + stroke fin
const LIGHT_WEIGHT_FONTS = new Set(['InterRegular', 'InterMedium', 'TikTokSansRegular']);
const REGISTERED_CUSTOM_FONTS = [];
for (const cf of CUSTOM_FONTS) {
  const p = path.join(_CUSTOM_FONTS_DIR, cf.file);
  try {
    if (fs.existsSync(p)) {
      GlobalFonts.registerFromPath(p, cf.family);
      REGISTERED_CUSTOM_FONTS.push(cf.family);
    }
  } catch (e) { /* ignore — fallback Arial */ }
}

// ─── Emoji PNG (Apple style via samuelngs/apple-emoji-linux) ─────────────────
const _EMOJI_CACHE_DIR = path.join(__dirname, '.emoji-cache');
try { if (!fs.existsSync(_EMOJI_CACHE_DIR)) fs.mkdirSync(_EMOJI_CACHE_DIR); } catch (_) {}
const _emojiImgCache = new Map(); // cp → Image | null

// Codepoint sans FE0F — pour Twemoji (fallback)
function _emojiCP(emoji) {
  return [...emoji]
    .map(c => c.codePointAt(0).toString(16))
    .filter(cp => cp !== 'fe0f')
    .join('-');
}

// Codepoint COMPLET avec FE0F — pour Apple emoji linux repo
function _emojiCPFull(emoji) {
  return [...emoji]
    .map(c => c.codePointAt(0).toString(16))
    .join('-');
}

function _fetchBuf(url) {
  return new Promise((resolve, reject) => {
    const mod  = url.startsWith('https') ? https : http;
    const opts = new URL(url);
    const req  = mod.get(
      { hostname: opts.hostname, path: opts.pathname + opts.search, headers: { 'User-Agent': 'Mozilla/5.0' } },
      res => {
        if (res.statusCode === 301 || res.statusCode === 302) {
          return _fetchBuf(res.headers.location).then(resolve).catch(reject);
        }
        if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode} for ${url}`));
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => resolve(Buffer.concat(chunks)));
        res.on('error', reject);
      }
    );
    req.on('error', reject);
    req.setTimeout(8000, () => { req.destroy(); reject(new Error('timeout')); });
  });
}

async function _loadEmojiImg(emoji) {
  const cpShort = _emojiCP(emoji);     // ex: 2764       (sans fe0f) → Twemoji
  const cpFull  = _emojiCPFull(emoji); // ex: 2764-fe0f  (avec fe0f) → Apple repo
  const cacheKey = cpShort;

  if (_emojiImgCache.has(cacheKey)) return _emojiImgCache.get(cacheKey);

  // Le cache disque est nommé avec cpShort pour compatibilité
  const cacheFile = path.join(_EMOJI_CACHE_DIR, `${cpShort}.png`);

  try {
    let buf = null;

    if (fs.existsSync(cacheFile)) {
      buf = fs.readFileSync(cacheFile);
    } else {
      // Apple emoji via iamcal/emoji-data (img-apple-64, lowercase) — seule source qui répond 200 depuis le VPS
      const sources = [
        `https://raw.githubusercontent.com/iamcal/emoji-data/master/img-apple-64/${cpFull}.png`,
        `https://raw.githubusercontent.com/iamcal/emoji-data/master/img-apple-64/${cpShort}.png`,
      ];

      for (const url of sources) {
        try {
          const b = await _fetchBuf(url);
          if (b && b.length > 200) { buf = b; break; }
        } catch (_) {}
      }

      if (!buf || buf.length < 200) throw new Error(`no PNG found for ${emoji} (${cpFull})`);
      try { fs.writeFileSync(cacheFile, buf); } catch (_) {}
    }

    const img = await loadImage(buf);
    _emojiImgCache.set(cacheKey, img);
    return img;
  } catch (err) {
    console.error(`[emoji] échec ${emoji} : ${err.message}`);
    _emojiImgCache.set(cacheKey, null);
    return null;
  }
}

// Découpe une chaîne en runs [{type:'text'|'emoji', content}]
function _splitRuns(text) {
  const seg     = new Intl.Segmenter('en', { granularity: 'grapheme' });
  const emojiRe = /\p{Extended_Pictographic}/u;
  const runs    = [];
  let buf = '';
  for (const { segment } of seg.segment(text)) {
    if (emojiRe.test(segment)) {
      if (buf) { runs.push({ type: 'text', content: buf }); buf = ''; }
      runs.push({ type: 'emoji', content: segment });
    } else {
      buf += segment;
    }
  }
  if (buf) runs.push({ type: 'text', content: buf });
  return runs;
}

// Mesure la largeur d'une ligne mixte texte+emoji
function _measureLine(ctx, text, emojiSize) {
  let w = 0;
  for (const run of _splitRuns(text)) {
    w += run.type === 'text' ? ctx.measureText(run.content).width : emojiSize;
  }
  return w;
}

const VARIATIONS = [
  { label: 'zoom_normal',    zoom: 1.00, brightness:  0.00, saturation: 1.0,  hue:   0 },
  { label: 'zoom_chaud',     zoom: 1.02, brightness:  0.03, saturation: 1.1,  hue:   5 },
  { label: 'dezoom_froid',   zoom: 1.04, brightness: -0.03, saturation: 0.9,  hue:  -5 },
  { label: 'zoom_vif',       zoom: 1.03, brightness:  0.05, saturation: 1.2,  hue:  10 },
  { label: 'dezoom_sombre',  zoom: 1.05, brightness: -0.05, saturation: 1.15, hue:  -8 },
  { label: 'zoom_doux',      zoom: 1.01, brightness:  0.02, saturation: 0.95, hue:   3 },
  { label: 'zoom_contraste', zoom: 1.06, brightness:  0.04, saturation: 1.05, hue: -10 },
  { label: 'zoom_saturé',    zoom: 1.02, brightness: -0.02, saturation: 1.25, hue:   7 },
  { label: 'dezoom_clair',   zoom: 1.04, brightness:  0.06, saturation: 0.85, hue:  -3 },
  { label: 'zoom_teinté',    zoom: 1.03, brightness: -0.04, saturation: 1.1,  hue:  12 },
];

// Cède l'event loop entre les opérations lourdes pour garder le serveur réactif
const yieldLoop = () => new Promise(resolve => setImmediate(resolve));

// Concurrence FFmpeg (parallelisation) — configurable via env, defaut 2.
// Sur un VPS 4 vCPU, 2-3 ffmpeg en parallele est l'optimum (chaque ffmpeg sature
// deja 1.5-2 cores avec preset=fast).
const FFMPEG_CONCURRENCY = Math.max(1, Math.min(8,
  parseInt(process.env.PIPELINE_FFMPEG_CONCURRENCY, 10) || 2
));

// ─── État pipeline ────────────────────────────────────────────────────────────
const activeProcs    = new Map(); // modelId → Set<ffmpeg process> (parallele)
const stopFlags      = new Map(); // modelId → bool
const pendingFolders = new Map(); // modelId → Set<folderName> (ajouts dynamiques)

function stopPipeline(modelId) {
  stopFlags.set(modelId, true);
  const set = activeProcs.get(modelId);
  if (set) for (const p of set) { try { p.kill('SIGTERM'); } catch (_) {} }
}

// Semaphore minimaliste pour limiter le nb de promesses en vol.
function createSemaphore(limit) {
  let active = 0;
  const waiting = [];
  return {
    async acquire() {
      if (active < limit) { active++; return; }
      await new Promise(r => waiting.push(r));
      active++;
    },
    release() {
      active--;
      const next = waiting.shift();
      if (next) next();
    },
  };
}

/** Ajoute un dossier à la queue d'un pipeline en cours */
function addFolderToRunning(modelId, folderName) {
  if (!pendingFolders.has(modelId)) pendingFolders.set(modelId, new Set());
  pendingFolders.get(modelId).add(folderName);
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function sanitizeName(str) {
  return str
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9_]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '');
}

function randomId(len = 4) {
  return Math.random().toString(36).substring(2, 2 + len);
}

function dateStamp() {
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth()+1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`;
}

// ─── Anti-fingerprinting helpers ──────────────────────────────────────────────
function randFloat(min, max) {
  return Math.random() * (max - min) + min;
}
function jitter(base, pct = 0.02) {
  return base * (1 + randFloat(-pct, pct));
}
function randomOutputName() {
  const digits = String(Math.floor(Math.random() * 9000) + 1000);
  return `DSC_${digits}_${randomId(4)}.mp4`;
}
function randomImageOutputName(ext) {
  const digits = String(Math.floor(Math.random() * 9000) + 1000);
  return `IMG_${digits}_${randomId(4)}${ext}`;
}
function randomCreationDate() {
  const ms = Date.now() - Math.floor(Math.random() * 24 * 3600 * 1000);
  return new Date(ms).toISOString().split('.')[0];
}
const _DEVICES = [
  'Apple iPhone 14 Pro', 'Apple iPhone 13', 'Apple iPhone 15 Pro',
  'Samsung Galaxy S23', 'Samsung Galaxy A54', 'Google Pixel 7a',
  'OnePlus 11', 'Xiaomi 13', 'OPPO Find X5 Pro',
];
function randomDevice() {
  return _DEVICES[Math.floor(Math.random() * _DEVICES.length)];
}

// Pitch shift ±2% + délai aléatoire 0-250ms → piste audio unique à chaque export
function randomAudioFilter() {
  const pitchFactor  = 1 + randFloat(-0.02, 0.02);
  const delayMs      = Math.floor(randFloat(0, 250));
  const targetRate   = Math.round(44100 * pitchFactor);
  const tempo        = (1 / pitchFactor).toFixed(6);
  return `adelay=${delayMs}|${delayMs},asetrate=${targetRate},aresample=44100,atempo=${tempo}`;
}

// Résolution finale ±2px (toujours paire pour libx264)
function randomOutputDims() {
  const wDelta = (Math.floor(Math.random() * 3) - 1) * 2; // -2, 0 ou +2
  const hDelta = (Math.floor(Math.random() * 3) - 1) * 2;
  return { w: CONFIG.outputWidth + wDelta, h: CONFIG.outputHeight + hDelta };
}

function timeToSeconds(t) {
  if (!t || t.includes('∞')) return 99999;
  const parts = t.split(':');
  if (parts.length !== 3) return 99999;
  const [h, m, s] = parts;
  return parseFloat(h) * 3600 + parseFloat(m) * 60 + parseFloat(s);
}

async function getVideoDuration(videoPath) {
  return new Promise(resolve => {
    const p = spawn('ffprobe', [
      '-v', 'error', '-show_entries', 'format=duration',
      '-of', 'default=noprint_wrappers=1:nokey=1', videoPath,
    ]);
    let out = '';
    p.stdout.on('data', d => out += d.toString());
    p.on('close', () => resolve(parseFloat(out.trim()) || 0));
  });
}

// ─── Rendu texte via canvas ───────────────────────────────────────────────────
function wrapText(ctx, text, maxW, emojiSize) {
  const eSize    = emojiSize || CONFIG.fontSize;
  const segments = [...new Intl.Segmenter('fr', { granularity: 'grapheme' }).segment(text)].map(s => s.segment);
  const lines    = [];
  let current    = '';
  const words    = text.split(' ');
  const hasSpaces = words.length > 1;

  if (hasSpaces) {
    for (const word of words) {
      const test = current ? `${current} ${word}` : word;
      if (_measureLine(ctx, test, eSize) > maxW && current) { lines.push(current); current = word; }
      else current = test;
    }
    if (current) lines.push(current);
  } else {
    for (const g of segments) {
      const test = current + g;
      if (_measureLine(ctx, test, eSize) > maxW && current) { lines.push(current); current = g; }
      else current = test;
    }
    if (current) lines.push(current);
  }
  return lines.length ? lines : [text];
}

async function renderCaptionsPng(captions, pngPath, yOffset = 0, fontFamily = null) {
  const W    = CONFIG.outputWidth;
  const H    = CONFIG.outputHeight;
  const maxW = CONFIG.maxTextWidth;
  const BASE = CONFIG.fontSize;
  // Police texte selectionnee (fallback Arial si non disponible)
  // Bebas/Anton sont des fontes "Regular" qui font deja un effet bold visuel
  // InterRegular/InterMedium sont des poids legers (style TikTok native)
  const isPreBold  = fontFamily === 'BebasNeue' || fontFamily === 'Anton';
  const isLight    = LIGHT_WEIGHT_FONTS.has(fontFamily);
  const usePrefix  = !isPreBold && !isLight;
  const fontStack = fontFamily
    ? `${usePrefix ? 'bold ' : ''}${'%S%px'} "${fontFamily}", ArialBold, Arial, sans-serif`
    : `bold ${'%S%px'} ArialBold, LinuxBold, Arial, sans-serif`;
  const FONT = size => fontStack.replace('%S%', size);
  // Stroke fin pour les fontes regular (effet TikTok), epais pour les bold classiques
  const strokeMul = isLight ? 0.07 : 0.14;
  const strokeMin = isLight ? 2    : 5;

  const canvas = createCanvas(W, H);
  const ctx    = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);
  ctx.textBaseline = 'middle';

  const finalLines = [];
  for (const cap of captions) {
    const raw = (cap.text || '').trim();
    if (!raw) continue;
    const emojiSize = Math.round(BASE * 1.15);
    ctx.font = FONT(BASE);
    // Respecte les sauts de ligne manuels (\n) saisis dans l'editeur
    const manualLines = raw.split(/\r?\n/);
    for (const manualLine of manualLines) {
      const seg = manualLine.trim();
      if (!seg) {
        // Ligne vide = espacement (fontSize neutre, pas de texte a dessiner)
        finalLines.push({ text: '', fontSize: BASE });
        continue;
      }
      const wrapped = wrapText(ctx, seg, maxW, emojiSize);
      for (const line of wrapped) {
        let size = BASE;
        ctx.font = FONT(size);
        while (_measureLine(ctx, line, Math.round(size * 1.15)) > maxW && size > 18) {
          size -= 2; ctx.font = FONT(size);
        }
        finalLines.push({ text: line, fontSize: size });
      }
    }
  }

  await yieldLoop();

  if (!finalLines.length) { fs.writeFileSync(pngPath, canvas.toBuffer('image/png')); return; }

  const lineH  = Math.round(BASE * CONFIG.lineSpacing);
  const totalH = (finalLines.length - 1) * lineH;
  // baseY = position verticale ratio + offset aleatoire anti-detection (-5..+5 px par render)
  const baseY  = Math.round(H * CONFIG.verticalY) + yOffset;
  const startY = baseY - totalH / 2;

  for (let i = 0; i < finalLines.length; i++) {
    const { text, fontSize } = finalLines[i];
    const emojiSize = Math.round(fontSize * 1.15);
    const y         = Math.round(startY + i * lineH);
    ctx.font      = FONT(fontSize);
    ctx.lineWidth = Math.max(strokeMin, fontSize * strokeMul);
    ctx.lineJoin  = 'round';

    const runs     = _splitRuns(text);
    const hasEmoji = runs.some(r => r.type === 'emoji');

    if (!hasEmoji) {
      // Texte pur — rendu centré classique
      ctx.textAlign   = 'center';
      ctx.strokeStyle = 'rgba(0,0,0,0.95)';
      ctx.strokeText(text, Math.round(W / 2), y);
      ctx.fillStyle = 'white';
      ctx.fillText(text, Math.round(W / 2), y);
    } else {
      // Mixte texte + emoji — mesure totale puis dessin gauche→droite
      ctx.textAlign = 'left';
      const totalW  = _measureLine(ctx, text, emojiSize);
      let curX      = Math.round(W / 2 - totalW / 2);

      for (const run of runs) {
        if (run.type === 'text') {
          ctx.strokeStyle = 'rgba(0,0,0,0.95)';
          ctx.strokeText(run.content, curX, y);
          ctx.fillStyle = 'white';
          ctx.fillText(run.content, curX, y);
          curX += ctx.measureText(run.content).width;
        } else {
          const img = await _loadEmojiImg(run.content);
          if (img) {
            ctx.drawImage(img, curX, Math.round(y - emojiSize * 0.5), emojiSize, emojiSize);
          }
          curX += emojiSize;
        }
      }
    }
    await yieldLoop();
  }

  fs.writeFileSync(pngPath, canvas.toBuffer('image/png'));
}

// ─── Filtre vidéo ─────────────────────────────────────────────────────────────
function buildVideoFilter(variation, brightJitter = 0, contrastJitter = 0, outW = CONFIG.outputWidth, outH = CONFIG.outputHeight) {
  const W = CONFIG.outputWidth;
  const H = CONFIG.outputHeight;
  // Zoom ±2% jitter
  const zoomVal  = variation.zoom * (1 + randFloat(-0.02, 0.02));
  // Garantit que les dimensions zoomées sont toujours >= cibles (évite crop impossible)
  const zoomedW  = Math.max(W + 2, Math.round(W * zoomVal));
  const zoomedH  = Math.max(H + 2, Math.round(H * zoomVal));
  const brightness = Math.min(0.5, Math.max(-0.5, variation.brightness + brightJitter));
  const contrast   = Math.min(2.0, Math.max(0.5, 1.0 + contrastJitter));
  // Saturation ±2% jitter
  const saturation = Math.min(3.0, Math.max(0.1, jitter(variation.saturation, 0.02)));
  // Hue : décalage aléatoire -0.03..+0.03, jamais exactement 0
  let hueShift = variation.hue + randFloat(-0.03, 0.03);
  if (Math.abs(hueShift) < 0.005) hueShift = randFloat(0.008, 0.015);
  // hflip : 1 vidéo sur 3
  const doHflip = Math.random() < (1 / 3);
  const filters = [
    `scale=${W}:${H}:force_original_aspect_ratio=increase`,
    `crop=${W}:${H}`,
    `scale=${zoomedW}:${zoomedH}`,
    `crop=${W}:${H}`,
    `eq=brightness=${brightness.toFixed(3)}:saturation=${saturation.toFixed(3)}:contrast=${contrast.toFixed(3)}`,
    `hue=h=${hueShift.toFixed(4)}`,
  ];
  if (doHflip) filters.push('hflip');
  // Résolution finale légèrement variée (±2px)
  if (outW !== W || outH !== H) filters.push(`scale=${outW}:${outH}`);
  return filters.join(',');
}

// ─── FFmpeg ───────────────────────────────────────────────────────────────────
function runFFmpeg(modelId, args) {
  return new Promise(resolve => {
    const proc = spawn('ffmpeg', args, { stdio: 'pipe' });
    if (!activeProcs.has(modelId)) activeProcs.set(modelId, new Set());
    activeProcs.get(modelId).add(proc);
    let stderr = '';
    proc.stderr.on('data', d => { stderr += d.toString(); });
    const cleanup = () => {
      const s = activeProcs.get(modelId);
      if (s) { s.delete(proc); if (!s.size) activeProcs.delete(modelId); }
    };
    proc.on('close', code => { cleanup(); resolve({ status: code, stderr: stderr.slice(-300) }); });
    proc.on('error', () => { cleanup(); resolve({ status: -1, stderr: 'ffmpeg introuvable' }); });
  });
}

// ─── Pipeline principal ────────────────────────────────────────────────────────
/**
 * @param captionMap     Optionnel : { 'video1.mp4': ['v1','v2'], 'video2.mp4': ['v3'] }
 *                       Si fourni, chaque vidéo n'utilise QUE les captions listées
 *                       (override de selectedCaptions). Si une vidéo a une liste vide → skippée.
 * @param videoFolderMap Optionnel : { 'video1.mp4': ['V1','V3'], 'video2.mp4': ['V2'] }
 *                       Si fourni, chaque vidéo va UNIQUEMENT dans les V folders listés
 *                       (override de selectedFolders). Si liste vide → vidéo skippée.
 *                       Évite la duplication d'une même vidéo dans tous les V.
 * @param targetFiles    Optionnel : ['video1.mp4', 'video2.mp4']
 *                       Si fourni, le pipeline ne traite QUE ces fichiers du dossier input/.
 *                       Les autres vidéos restent intactes. Permet "Lancer 1 vidéo" = 1 vidéo.
 */
async function runPipeline(modelId, log, selectedFolders = null, notify = null, selectedCaptions = null, userDir = __dirname, captionMap = null, videoFolderMap = null, targetFiles = null) {
  stopFlags.set(modelId, false);
  pendingFolders.delete(modelId);

  const inputDir  = path.join(userDir, 'models', modelId, 'input');
  const outputDir = path.join(userDir, 'models', modelId, 'output');
  const stockDir  = path.join(userDir, 'models', modelId, 'stock');
  const tempDir   = path.join(userDir, 'temp');

  [stockDir, tempDir].forEach(d => { if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true }); });

  VARIATIONS.forEach((_, i) => {
    const d = path.join(outputDir, `V${i + 1}`);
    if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  });

  // Captions : prefere captions.json (lib/captions migre depuis .js si necessaire).
  // Garde un fallback require() pour rester compatible si lib/ absent (tests).
  let CAPTION_VERSIONS = [];
  try {
    const captionsStore = require('./lib/captions');
    CAPTION_VERSIONS = captionsStore.read(userDir);
  } catch (_) {
    try {
      const captionsPath = path.join(userDir, 'captions.js');
      delete require.cache[require.resolve(captionsPath)];
      CAPTION_VERSIONS = require(captionsPath);
    } catch (_) { CAPTION_VERSIONS = []; }
  }

  const versionsToProcess = (selectedCaptions && selectedCaptions.length)
    ? CAPTION_VERSIONS.filter(v => selectedCaptions.includes(v.label))
    : CAPTION_VERSIONS;

  if (!versionsToProcess.length) {
    log('⚠️  Aucune caption correspondante trouvée — vérifiez les labels sélectionnés', '⚠️ Aucune caption sélectionnée');
    return;
  }

  let videos = fs.readdirSync(inputDir).filter(f =>
    ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'].includes(path.extname(f).toLowerCase())
  );

  // ── Filtre targetFiles : si fourni, ne traite que ces fichiers spécifiques ──
  // Permet "Lancer 1 vidéo" = 1 vidéo (au lieu de tout input/).
  // Les autres vidéos restent intactes dans input/, prêtes pour un futur run.
  if (Array.isArray(targetFiles) && targetFiles.length > 0) {
    const wanted = new Set(targetFiles.map(f => String(f || '')));
    const filtered = videos.filter(v => wanted.has(v));
    if (filtered.length === 0) {
      log(`⚠️  targetFiles fourni (${targetFiles.length} fichier(s)) mais aucun ne correspond aux vidéos d'input/`, '⚠️ Fichiers cibles introuvables');
      return;
    }
    log(`🎯 Filtre targetFiles actif : ${filtered.length}/${videos.length} vidéo(s) sélectionnée(s) — ${filtered.join(', ')}`, `🎯 ${filtered.length} vidéo(s) cible`);
    videos = filtered;
  }

  const IMAGE_EXTS_CHECK = ['.jpg', '.jpeg', '.png', '.webp'];
  const hasPosts   = fs.existsSync(path.join(inputDir, 'posts'))   && fs.readdirSync(path.join(inputDir, 'posts')).some(f => IMAGE_EXTS_CHECK.includes(path.extname(f).toLowerCase()));
  const hasStories = fs.existsSync(path.join(inputDir, 'stories')) && fs.readdirSync(path.join(inputDir, 'stories')).some(f => IMAGE_EXTS_CHECK.includes(path.extname(f).toLowerCase()));

  if (!videos.length && !hasPosts && !hasStories) {
    log('⚠️  Aucun fichier à traiter (ni vidéos, ni posts, ni stories)', '⚠️ Aucun fichier à traiter');
    return;
  }

  // ── Calcul EXACT du total des rendus AVANT les logs (tient compte captionMap + videoFolderMap) ──
  const pipelineStart = Date.now();
  let   doneRenders   = 0;
  let totalRenders = 0;
  if (videos.length > 0) {
    const defaultFolderCount = selectedFolders ? selectedFolders.length : VARIATIONS.length;
    for (const f of videos) {
      // Captions pour cette vidéo
      let capsCount;
      if (captionMap && Array.isArray(captionMap[f]) && captionMap[f].length) {
        capsCount = captionMap[f].length;
      } else if (captionMap && typeof captionMap === 'object') {
        capsCount = 0;   // vidéo absente du map en mode matrix → skippée
      } else {
        capsCount = versionsToProcess.length;
      }
      if (capsCount === 0) continue;
      // V folders pour cette vidéo
      let foldCount;
      if (videoFolderMap && Array.isArray(videoFolderMap[f]) && videoFolderMap[f].length) {
        foldCount = videoFolderMap[f].length;
      } else if (videoFolderMap && typeof videoFolderMap === 'object') {
        foldCount = 0;   // vidéo absente du map → skippée
      } else {
        foldCount = defaultFolderCount;
      }
      if (foldCount === 0) continue;
      totalRenders += capsCount * foldCount;
    }
  }

  // ── Logs d'intro (maintenant que totalRenders est calculé) ──
  log('═══════════════════════════════════════════', '');
  log(`🚀 Pipeline démarré — ${new Date().toLocaleTimeString('fr-FR')}`, `🚀 Pipeline démarré`);
  if (videos.length) {
    const activeVars = selectedFolders ? selectedFolders.length : VARIATIONS.length;
    const folderList = selectedFolders ? selectedFolders.join(', ') : 'V1–V10';
    const capList    = selectedCaptions ? selectedCaptions.join(', ') : 'toutes';
    const matrixHint = captionMap || videoFolderMap ? ' [matrice par vidéo activée]' : '';
    log(`📹 ${videos.length} vidéo(s) × ${activeVars} variation(s) [${folderList}] × ${versionsToProcess.length} caption(s) [${capList}]${matrixHint} = ${totalRenders} exports prévus`, `📹 ${videos.length} vidéo(s) · ${totalRenders} exports prévus`);
  }
  if (hasPosts)   log(`🖼 Posts à traiter`, `🖼 Posts à traiter`);
  if (hasStories) log(`📲 Stories à traiter`, `📲 Stories à traiter`);
  log('═══════════════════════════════════════════', '');

  let success = 0, failed = 0, stopped = false;

  for (const filename of videos) {
    if (stopFlags.get(modelId)) { stopped = true; break; }

    // ── Captions à utiliser pour CETTE vidéo ──
    // Si captionMap existe et contient cette vidéo → utilise ses captions spécifiques
    // Si captionMap existe mais cette vidéo n'y est pas → on saute la vidéo (volonté explicite)
    // Sinon → fallback sur versionsToProcess (mode global)
    let videoVersionsToProcess = versionsToProcess;
    if (captionMap && typeof captionMap === 'object') {
      const labels = captionMap[filename];
      if (Array.isArray(labels) && labels.length > 0) {
        videoVersionsToProcess = CAPTION_VERSIONS.filter(v => labels.includes(v.label));
      } else {
        // Vidéo absente de la map ou liste vide → skip
        log(`  ⏭️  ${filename} — pas de caption assignée dans la matrice, skip`, `  ⏭️ ${filename} skippée`);
        continue;
      }
    }
    if (!videoVersionsToProcess.length) {
      log(`  ⏭️  ${filename} — aucune caption à appliquer, skip`, `  ⏭️ ${filename} skippée`);
      continue;
    }

    const inputPath = path.join(inputDir, filename);
    const baseName  = sanitizeName(path.basename(filename, path.extname(filename)));
    const duration  = await getVideoDuration(inputPath);

    log(`\n📹 ${filename} (${duration.toFixed(1)}s) — ${videoVersionsToProcess.length} caption(s) [${videoVersionsToProcess.map(c => c.label).join(', ')}]`, `\n📹 Traitement de ${filename}`);

    // ── V folders à utiliser pour CETTE vidéo ──
    // Si videoFolderMap existe et contient cette vidéo → utilise SES V folders
    // Sinon → fallback sur selectedFolders (mode global)
    let videoFolders = selectedFolders;
    if (videoFolderMap && typeof videoFolderMap === 'object') {
      const vf = videoFolderMap[filename];
      if (Array.isArray(vf) && vf.length > 0) {
        videoFolders = vf;
        log(`  📁 V folders pour cette vidéo : ${vf.join(', ')}`, `  📁 ${vf.join(', ')}`);
      } else {
        log(`  ⏭️  ${filename} — aucun V folder assigné, skip`, `  ⏭️ ${filename} skippée`);
        continue;
      }
    }

    const initialSet = videoFolders
      ? new Set(videoFolders)
      : new Set(VARIATIONS.map((_, i) => `V${i + 1}`));

    const pending0 = pendingFolders.get(modelId);
    if (pending0) { pending0.forEach(f => initialSet.add(f)); pending0.clear(); }

    const processedSet = new Set();
    const queue = [];
    VARIATIONS.forEach((_, i) => {
      const name = `V${i + 1}`;
      if (initialSet.has(name)) { queue.push(i); processedSet.add(i); }
    });

    let qi = 0;
    while (true) {
      const pending = pendingFolders.get(modelId);
      if (pending && pending.size > 0) {
        for (const folderName of [...pending]) {
          const vi = parseInt(folderName.slice(1)) - 1;
          if (vi >= 0 && vi < VARIATIONS.length && !processedSet.has(vi)) {
            queue.push(vi);
            processedSet.add(vi);
            log(`  📋 Dossier ${folderName} ajouté à la file d'attente`, `  📋 ${folderName} ajouté à la file`);
            if (notify) notify({ type: 'folder-queued', folder: folderName });
          }
          pending.delete(folderName);
        }
      }

      if (qi >= queue.length) break;
      if (stopFlags.get(modelId)) { stopped = true; break; }

      const vi         = queue[qi++];
      const variation  = VARIATIONS[vi];
      const folderName = `V${vi + 1}`;
      const folder     = path.join(outputDir, folderName);

      if (notify) notify({ type: 'folder-start', folder: folderName });

      // Lance les captions en parallele (FFMPEG_CONCURRENCY simultanes max).
      // videoVersionsToProcess est calculé en début de boucle vidéo (peut être < versionsToProcess si captionMap)
      const sem = createSemaphore(FFMPEG_CONCURRENCY);
      const tasks = videoVersionsToProcess.map(cap => (async () => {
        if (stopFlags.get(modelId)) return;
        await sem.acquire();
        try {
          if (stopFlags.get(modelId)) return;

          const noiseSeed      = Math.floor(Math.random() * 99999);
          const brightJitter   = parseFloat(((Math.random() * 0.02) - 0.01).toFixed(3));
          const contrastJitter = parseFloat(((Math.random() * 0.02) - 0.01).toFixed(3));
          const trimSec        = (50 + Math.floor(Math.random() * 51)) / 1000;
          // Offset Y aleatoire des captions (-300..+300 px) anti-fingerprint Insta
          const captionYOffset = Math.floor(Math.random() * 601) - 300;
          log(`  📐 Caption Y offset: ${captionYOffset >= 0 ? '+' : ''}${captionYOffset}px [V${vi+1}/${cap.label}/${baseName}]`, `📐 offset Y: ${captionYOffset}px`);
          const uid            = randomId(4);
          const capLabel       = sanitizeName(cap.label);
          const outputName     = randomOutputName();
          const outputPath     = path.join(folder, outputName);
          const finalDuration  = Math.max(1, duration - trimSec);

          const { w: outW, h: outH } = randomOutputDims();
          const audioFilter  = randomAudioFilter();
          const videoFilter  = buildVideoFilter(variation, brightJitter, contrastJitter, outW, outH);

          const pngPaths      = [];
          const ffmpegInputs  = ['-i', inputPath];
          let filterComplex   = `[0:v]${videoFilter}[vid0]`;
          let lastOutput      = 'vid0';

          for (let i = 0; i < cap.captions.length; i++) {
            const segment = cap.captions[i];
            if (!segment.text || !segment.text.trim()) continue;
            // Nom unique avec uid pour eviter les collisions inter-taches paralleles.
            const pngPath = path.join(tempDir, `cap_${modelId}_${uid}_${Date.now()}_${i}.png`);
            try {
              await renderCaptionsPng([segment], pngPath, captionYOffset, cap.font || null);
              pngPaths.push(pngPath);
              ffmpegInputs.push('-i', pngPath);
              const inputIndex    = pngPaths.length;
              const startSec      = timeToSeconds(segment.start);
              const endSec        = timeToSeconds(segment.end);
              const currentOutput = `vid${inputIndex}`;
              filterComplex += `;[${inputIndex}:v]format=rgba[ov${inputIndex}];[${lastOutput}][ov${inputIndex}]overlay=0:0:enable='between(t,${startSec},${endSec})'[${currentOutput}]`;
              lastOutput = currentOutput;
            } catch (err) {
              log(`  ⚠️ PNG segment ${i} : ${err.message}`);
            }
          }

          filterComplex += `;[${lastOutput}]noise=alls=1:allf=t+u:all_seed=${noiseSeed}[final_${uid}]`;
          lastOutput = `final_${uid}`;

          const args = [...ffmpegInputs,
            '-filter_complex', filterComplex,
            '-map',            `[${lastOutput}]`,
            '-map',            '0:a?',
            '-af',             audioFilter,
            '-t',              finalDuration.toFixed(3),
            '-map_metadata',   '-1',
            '-metadata',       `comment=${uid}`,
            '-metadata',       `creation_time=${randomCreationDate()}`,
            '-metadata',       `make=${randomDevice().split(' ')[0]}`,
            '-metadata',       `model=${randomDevice()}`,
            '-metadata',       `encoder=QuickTime`,
            '-c:v',            'libx264',
            '-preset',         'fast',
            '-crf',            '23',
            '-c:a',            'aac',
            '-b:a',            '192k',
            '-y',              outputPath,
          ];

          const result = await runFFmpeg(modelId, args);
          for (const p of pngPaths) { try { fs.unlinkSync(p); } catch (_) {} }

          if (stopFlags.get(modelId)) {
            if (fs.existsSync(outputPath)) try { fs.unlinkSync(outputPath); } catch (_) {}
            return;
          }
          if (result.status === 0) {
            log(`  ✅ [${folderName}] [${capLabel}] → ${outputName}`, `  ✅ Vidéo créée [${folderName}]`);
            success++;
          } else {
            log(`  ❌ [${folderName}] [${capLabel}] — ${result.stderr}`, `  ❌ Erreur lors du rendu [${folderName}]`);
            failed++;
          }
          if (notify && totalRenders > 0) {
            doneRenders++;
            const elapsed = (Date.now() - pipelineStart) / 1000;
            const rate    = elapsed > 0 ? doneRenders / elapsed : 0;
            const eta     = rate > 0 ? Math.round((totalRenders - doneRenders) / rate) : null;
            const pct     = Math.min(99, Math.round(doneRenders / totalRenders * 100));
            notify({ type: 'progress', current: doneRenders, total: totalRenders, pct, eta });
          }
        } finally {
          sem.release();
        }
      })());
      await Promise.all(tasks);
      if (stopFlags.get(modelId)) { stopped = true; break; }
    }

    if (!stopped) {
      // La source reste dans input/ (visible dans le dropdown du dossier de /generator)
      log(`\n  ✓ "${filename}" traité (reste dans le dossier)`, `\n  ✓ "${filename}" traité`);
    }
  }

  // ── Traitement images (posts + stories) ───────────────────────────────────
  const IMAGE_EXTS_PIPE = ['.jpg', '.jpeg', '.png', '.webp'];

  for (const imgType of ['posts', 'stories']) {
    if (stopped) break;
    const imgInputDir = path.join(inputDir, imgType);
    if (!fs.existsSync(imgInputDir)) continue;

    const images = fs.readdirSync(imgInputDir)
      .filter(f => IMAGE_EXTS_PIPE.includes(path.extname(f).toLowerCase()));
    if (!images.length) continue;

    log(`\n─────────────────────────────────────────`, '');
    log(`🖼 ${images.length} ${imgType === 'posts' ? 'post(s)' : 'storie(s)'} à traiter`, `🖼 ${images.length} ${imgType === 'posts' ? 'post(s)' : 'storie(s)'} à traiter`);

    for (const imgFile of images) {
      if (stopFlags.get(modelId)) { stopped = true; break; }
      const imgInputPath = path.join(imgInputDir, imgFile);
      const baseName     = sanitizeName(path.basename(imgFile, path.extname(imgFile)));
      const ext          = path.extname(imgFile);

      log(`\n🖼 ${imgFile}`, `\n🖼 Traitement de ${imgFile}`);

      const initialSet2 = selectedFolders
        ? new Set(selectedFolders)
        : new Set(VARIATIONS.map((_, i) => `V${i + 1}`));
      const pending0b = pendingFolders.get(modelId);
      if (pending0b) { pending0b.forEach(f => initialSet2.add(f)); pending0b.clear(); }

      for (let vi = 0; vi < VARIATIONS.length; vi++) {
        if (stopFlags.get(modelId)) { stopped = true; break; }
        const imgFolderName = `V${vi + 1}`;
        if (!initialSet2.has(imgFolderName)) continue;
        const variation = VARIATIONS[vi];
        const outDir    = path.join(outputDir, imgFolderName, imgType);
        if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
        const uid     = randomId(4);
        const stamp   = dateStamp();
        const outName = randomImageOutputName(ext);
        const outPath = path.join(outDir, outName);
        const result  = await runFFmpegImage(imgInputPath, outPath, variation);
        if (result.status === 0) { log(`  ✅ [${imgFolderName}] ${imgType}`, `  ✅ Image créée [${imgFolderName}]`); success++; }
        else { log(`  ❌ [${imgFolderName}] ${imgType} — ${result.stderr.slice(-120)}`, `  ❌ Erreur image [${imgFolderName}]`); failed++; }
      }

      if (!stopped) {
        const stockImgDir = path.join(stockDir, imgType);
        if (!fs.existsSync(stockImgDir)) fs.mkdirSync(stockImgDir, { recursive: true });
        fs.renameSync(imgInputPath, path.join(stockImgDir, imgFile));
        log(`\n  📦 "${imgFile}" déplacé vers le stock`, `\n  📦 "${imgFile}" archivé`);
      }
    }
  }

  log('\n═══════════════════════════════════════════', '');
  if (stopped) log('⛔ Pipeline arrêté manuellement', '⛔ Pipeline arrêté');
  else log(`✅ Terminé — ${success} réussi${failed ? ` / ❌ ${failed} échoué` : ''}`, `✅ Terminé — ${success} vidéo(s) créée(s)${failed ? ` / ❌ ${failed} erreur(s)` : ''}`);
  log('═══════════════════════════════════════════', '');

  stopFlags.set(modelId, false);
  pendingFolders.delete(modelId);
}

// ─── FFmpeg image ─────────────────────────────────────────────────────────────
async function runFFmpegImage(inputPath, outputPath, variation) {
  // Jitter ±2% sur tous les paramètres visuels
  const zoomVal = jitter(variation.zoom !== undefined ? variation.zoom : 1.0, 0.02);
  const briVal  = Math.min(0.5, Math.max(-0.5, (variation.brightness || 0) + randFloat(-0.02, 0.02)));
  const satVal  = Math.min(3.0, Math.max(0.1, jitter(variation.saturation !== undefined ? variation.saturation : 1.0, 0.02)));
  // Hue toujours appliqué, jamais 0
  let hueVal = (variation.hue || 0) + randFloat(-0.03, 0.03);
  if (Math.abs(hueVal) < 0.005) hueVal = randFloat(0.008, 0.015);
  const parts = [
    `scale=iw*${zoomVal.toFixed(4)}:ih*${zoomVal.toFixed(4)},crop=iw/${zoomVal.toFixed(4)}:ih/${zoomVal.toFixed(4)}`,
    `eq=brightness=${briVal.toFixed(3)}:saturation=${satVal.toFixed(3)}`,
    `hue=h=${hueVal.toFixed(4)}`,
  ];
  return new Promise(resolve => {
    const proc = spawn('ffmpeg', ['-y', '-i', inputPath, '-vf', parts.join(','), '-q:v', '2', outputPath]);
    let stderr = '';
    proc.stderr.on('data', d => { stderr += d.toString(); });
    proc.on('close', code => resolve({ status: code, stderr }));
  });
}

module.exports = { runPipeline, stopPipeline, addFolderToRunning, VARIATIONS, buildVideoFilter, loadEmojiImg: _loadEmojiImg, splitRuns: _splitRuns, measureLine: _measureLine };
