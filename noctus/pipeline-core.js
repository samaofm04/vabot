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

// Rectangle arrondi (fond "bulle" derrière le texte)
function _roundRect(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
// Effet de texte (bouton "Effets") : ombre portée / néon (glow couleur)
function _fxOn(ctx, fx, fs, col) {
  if (fx === 'shadow') {
    ctx.shadowColor = 'rgba(0,0,0,0.8)'; ctx.shadowBlur = Math.round(fs * 0.12);
    ctx.shadowOffsetX = Math.round(fs * 0.04); ctx.shadowOffsetY = Math.round(fs * 0.07);
  } else if (fx === 'neon') {
    ctx.shadowColor = col; ctx.shadowBlur = Math.round(fs * 0.5);
    ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
  }
}
function _fxOff(ctx) {
  ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0;
  ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
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

// ── Métadonnées iPhone crédibles (MÊME recette que /reel / video_transform.py) ──
// iPhone + iOS cohérent + ville française + GPS RÉEL (ISO6709 Apple) + dates.
// Écrites via -movflags use_metadata_tags ; -bitexact efface le mouchard Lavf/x264.
const _FR_CITIES = [
  ['Paris',48.8566,2.3522,35],['Lyon',45.7640,4.8357,170],['Marseille',43.2965,5.3698,12],
  ['Nice',43.7102,7.2620,10],['Bordeaux',44.8378,-0.5792,9],['Toulouse',43.6047,1.4442,146],
  ['Nantes',47.2184,-1.5536,8],['Lille',50.6292,3.0573,23],['Cannes',43.5528,7.0174,10],
  ['Montpellier',43.6108,3.8767,27],['Strasbourg',48.5734,7.7521,142],['Rennes',48.1173,-1.6778,30],
  ['Biarritz',43.4832,-1.5586,19],['Annecy',45.8992,6.1294,447],['Saint-Tropez',43.2727,6.6386,10],
  ['Deauville',49.3600,0.0756,3],['Aix-en-Provence',43.5297,5.4474,173],['Grenoble',45.1885,5.7245,212],
  ['Toulon',43.1242,5.9280,10],['Avignon',43.9493,4.8055,23],['Colmar',48.0794,7.3585,194],
  ['Versailles',48.8014,2.1301,132],['La Baule',47.2860,-2.3908,6],['Honfleur',49.4189,0.2337,8],
];
const _IOS_BY = {
  'iPhone 15':['17.0','17.4','17.5','18.0','18.1'],'iPhone 15 Plus':['17.1','17.5','18.0','18.2'],
  'iPhone 15 Pro':['17.0','17.4','18.0','18.3','18.4'],'iPhone 15 Pro Max':['17.2','17.6','18.1','18.4'],
  'iPhone 16':['18.0','18.2','18.5','19.0'],'iPhone 16 Plus':['18.0','18.3','18.6','19.0'],
  'iPhone 16 Pro':['18.0','18.4','18.6','19.1'],'iPhone 16 Pro Max':['18.1','18.5','19.0','19.2'],
  'iPhone 17':['19.0','19.2','19.3'],'iPhone 17 Plus':['19.0','19.3'],
  'iPhone 17 Pro':['19.0','19.3','19.4'],'iPhone 17 Pro Max':['19.1','19.4','19.5'],
};
const _IPHONES = Object.keys(_IOS_BY);
function _isoPad(n, width, dec) {           // "007.4321" (signe géré à part)
  const parts = Math.abs(n).toFixed(dec).split('.');
  return parts[0].padStart(width, '0') + (parts[1] ? '.' + parts[1] : '');
}
function appleMetaArgs() {
  const model = _IPHONES[Math.floor(Math.random() * _IPHONES.length)];
  const iosArr = _IOS_BY[model];
  const ios   = iosArr[Math.floor(Math.random() * iosArr.length)];
  const c     = _FR_CITIES[Math.floor(Math.random() * _FR_CITIES.length)];
  const lat   = c[1] + randFloat(-0.003, 0.003);
  const lon   = c[2] + randFloat(-0.004, 0.004);
  const alt   = Math.max(0, c[3] + randFloat(-5, 15));
  const latS = lat >= 0 ? '+' : '-', lonS = lon >= 0 ? '+' : '-', altS = alt >= 0 ? '+' : '-';
  // Apple ISO6709 : lat 2 chiffres, lon 3, alt 3, chacun son signe (ex +44.8363-000.5792+009.990/)
  const iso = `${latS}${_isoPad(lat,2,4)}${lonS}${_isoPad(lon,3,4)}${altS}${_isoPad(alt,3,3)}/`;
  const ms  = Date.now() - Math.floor(randFloat(1,60))*86400000 - Math.floor(randFloat(0,23))*3600000;
  const iso8601 = new Date(ms).toISOString().split('.')[0];   // 2026-01-02T15:04:05
  return [
    '-metadata', `com.apple.quicktime.location.ISO6709=${iso}`,
    '-metadata', `com.apple.quicktime.make=Apple`,
    '-metadata', `com.apple.quicktime.model=${model}`,
    '-metadata', `com.apple.quicktime.software=${ios}`,
    '-metadata', `com.apple.quicktime.creationdate=${iso8601}+0200`,   // heure locale + offset
    '-metadata', `make=Apple`,
    '-metadata', `model=${model}`,
    '-metadata', `creation_time=${iso8601}.000000Z`,
    '-metadata:s:v:0', `handler_name=Core Media Video`,
  ];
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
  // Zone texte plus large (~88% de la largeur) -> les grandes tailles rentrent
  // sans être rétrécies. (avant : 720/1080 = 67% -> le texte long rapetissait.)
  const maxW = Math.round(W * 0.88);
  // ── Style PAR CAPTION (éditeur CapCut web) : x/y fraction 0-1, size px, color hex,
  //    font par segment. Champs absents -> comportement historique inchangé.
  const st = (captions && captions.length === 1 && captions[0]) || {};
  if (st.font) fontFamily = st.font;
  const hasSize = Number(st.size) > 0;   // taille imposée par l'utilisateur
  const BASE = hasSize
    ? Math.min(160, Math.max(16, Math.round(Number(st.size))))
    : CONFIG.fontSize;
  const fillColor = (typeof st.color === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(st.color))
    ? st.color : 'white';
  const hasCustomY = (st.y != null && isFinite(parseFloat(st.y)));
  const capY = hasCustomY ? Math.min(0.96, Math.max(0.03, parseFloat(st.y))) : CONFIG.verticalY;
  const hasCustomX = (st.x != null && isFinite(parseFloat(st.x)));
  const capX = hasCustomX ? Math.min(0.97, Math.max(0.03, parseFloat(st.x))) : 0.5;
  // Position custom (drag) -> PETIT décalage aléatoire (~±16px sur X et Y) : le texte
  // reste À CÔTÉ de là où tu l'as posé, mais JAMAIS au même pixel d'un export à l'autre
  // (anti-empreinte). Sans position custom -> jitter historique (yOffset).
  const jitterX = hasCustomX ? Math.round((Math.random() - 0.5) * 32) : 0;
  const CX = Math.round(W * capX) + jitterX;
  const effYOffset = hasCustomY ? Math.round((Math.random() - 0.5) * 32) : yOffset;
  // ── Styles CapCut par caption : alignement / casse / souligné / bulle / effet ──
  const alignSt = (st.align === 'left' || st.align === 'right') ? st.align : 'center';
  const caseSt  = (st.case === 'upper' || st.case === 'lower' || st.case === 'title') ? st.case : 'none';
  const underlineSt = st.underline === true;
  const boxSt = st.box === true;   // "Bulle" = fond derrière le texte
  const boxColor = (typeof st.boxColor === 'string' && /^#[0-9a-fA-F]{3,8}$/.test(st.boxColor)) ? st.boxColor : '#000000';
  const effectSt = (st.effect === 'shadow' || st.effect === 'neon') ? st.effect : 'none';   // "Effets"
  // Police texte selectionnee (fallback Arial si non disponible)
  // Bebas/Anton sont des fontes "Regular" qui font deja un effet bold visuel
  // InterRegular/InterMedium sont des poids legers (style TikTok native)
  // "Strong" = reproduction de la police Instagram Stories = Poppins gras + ITALIQUE penché
  const STRONG_ALIAS = { 'Strong': 'Poppins' };
  const realFamily = (fontFamily && STRONG_ALIAS[fontFamily]) ? STRONG_ALIAS[fontFamily] : fontFamily;
  const italicPart = (fontFamily && STRONG_ALIAS[fontFamily]) ? 'italic ' : '';
  const isPreBold  = realFamily === 'BebasNeue' || realFamily === 'Anton';
  const isLight    = LIGHT_WEIGHT_FONTS.has(realFamily);
  const usePrefix  = !isPreBold && !isLight;
  // Gras/italique manuels (boutons B/I) : st.bold/st.italic surchargent le défaut
  const wantBold   = (st.bold === true) ? true : (st.bold === false ? false : usePrefix);
  const wantItalic = (italicPart !== '') || (st.italic === true);
  const stylePrefix = (wantItalic ? 'italic ' : '') + (wantBold ? 'bold ' : '');
  const fontStack = realFamily
    ? `${stylePrefix}${'%S%px'} "${realFamily}", ArialBold, Arial, sans-serif`
    : `bold ${'%S%px'} ArialBold, LinuxBold, Arial, sans-serif`;
  const FONT = size => fontStack.replace('%S%', size);
  // Contour noir MARQUÉ (style TikTok/Insta) : plus épais qu'avant pour bien
  // détacher le texte du fond. Un peu plus fin pour les fontes légères.
  const strokeMul = isLight ? 0.11 : 0.19;
  const strokeMin = isLight ? 3    : 7;

  const canvas = createCanvas(W, H);
  const ctx    = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);
  ctx.textBaseline = 'middle';

  // Casse (boutons TT / tt / Tt de CapCut)
  function _applyCase(s) {
    if (caseSt === 'upper') return s.toUpperCase();
    if (caseSt === 'lower') return s.toLowerCase();
    if (caseSt === 'title') return s.replace(/\p{L}[\p{L}\p{M}']*/gu,
      w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
    return s;
  }

  const finalLines = [];
  for (const cap of captions) {
    const raw = _applyCase((cap.text || '').trim());
    if (!raw) continue;
    const emojiSize = Math.round(BASE * 1.15);
    ctx.font = FONT(BASE);
    // Respecte les sauts de ligne manuels (\n) saisis dans l'editeur.
    const manualLines = raw.split(/\r?\n/).map(l => l.trim());
    const hasManualBreaks = manualLines.length > 1;

    if (hasManualBreaks) {
      // Taille imposée (slider) -> on GARDE la taille : les lignes trop longues
      // passent à la ligne (wrap) au lieu de rétrécir. Sinon (taille auto) ->
      // ancien comportement : on réduit la taille pour que tout tienne.
      let size = BASE;
      if (!hasSize) {
        const widest = () => {
          ctx.font = FONT(size);
          const ws = manualLines.filter(l => l).map(
            l => _measureLine(ctx, l, Math.round(size * 1.15)));
          return ws.length ? Math.max(...ws) : 0;
        };
        while (widest() > maxW && size > 24) size -= 2;
      }
      ctx.font = FONT(size);
      for (const ml of manualLines) {
        if (!ml) {
          finalLines.push({ text: '', fontSize: size });   // ligne vide = espacement
          continue;
        }
        if (_measureLine(ctx, ml, Math.round(size * 1.15)) > maxW) {
          for (const w of wrapText(ctx, ml, maxW, Math.round(size * 1.15)))
            finalLines.push({ text: w, fontSize: size });
        } else {
          finalLines.push({ text: ml, fontSize: size });
        }
      }
    } else {
      // Pas de saut manuel -> wrap auto par largeur.
      const seg = manualLines[0] || '';
      if (!seg) continue;
      const wrapped = wrapText(ctx, seg, maxW, emojiSize);
      for (const line of wrapped) {
        let size = BASE;
        ctx.font = FONT(size);
        // taille auto -> on peut rétrécir une ligne trop large ; taille imposée -> on garde
        while (!hasSize && _measureLine(ctx, line, Math.round(size * 1.15)) > maxW && size > 18) {
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
  // baseY = position verticale (custom editeur ou ratio config) + offset anti-detection
  const baseY  = Math.round(H * capY) + effYOffset;
  const startY = baseY - totalH / 2;

  // Largeur réelle du bloc de texte -> on ancre son CENTRE visuel sur CX (=W*x)
  // pour TOUS les alignements (avant : left/right collaient aux bords d'une boîte
  // maxW, donc le centre visuel n'était pas x). L'aperçu web (translate -50%) et la
  // poignée de drag centrent aussi sur x : ainsi rendu final == aperçu, sans saut.
  let blockW = 0;
  for (const fl of finalLines) {
    ctx.font = FONT(fl.fontSize);
    const w = _measureLine(ctx, fl.text, Math.round(fl.fontSize * 1.15));
    if (w > blockW) blockW = w;
  }
  blockW = Math.min(maxW, blockW);
  const blockLeft = CX - blockW / 2;

  // "Bulle" : fond arrondi derrière tout le bloc de texte (dessiné AVANT le texte)
  if (boxSt) {
    let bl = Infinity, br = -Infinity;
    for (let i = 0; i < finalLines.length; i++) {
      const fl = finalLines[i];
      ctx.font = FONT(fl.fontSize);
      const lw = _measureLine(ctx, fl.text, Math.round(fl.fontSize * 1.15));
      let sx;
      if (alignSt === 'left') sx = blockLeft;
      else if (alignSt === 'right') sx = blockLeft + blockW - lw;
      else sx = CX - lw / 2;
      if (lw > 0) { bl = Math.min(bl, sx); br = Math.max(br, sx + lw); }
    }
    if (isFinite(bl) && br > bl) {
      const padX = Math.round(BASE * 0.40), padY = Math.round(BASE * 0.30);
      const bx = bl - padX, bw = (br - bl) + padX * 2;
      const bTop = startY - Math.round(BASE * 0.62) - padY;
      const bBot = startY + (finalLines.length - 1) * lineH + Math.round(BASE * 0.62) + padY;
      ctx.fillStyle = (boxColor.toLowerCase() === '#000000') ? 'rgba(0,0,0,0.5)' : boxColor;
      _roundRect(ctx, bx, bTop, bw, bBot - bTop, Math.round(BASE * 0.24));
      ctx.fill();
    }
  }

  for (let i = 0; i < finalLines.length; i++) {
    const { text, fontSize } = finalLines[i];
    const emojiSize = Math.round(fontSize * 1.15);
    const y         = Math.round(startY + i * lineH);
    ctx.font      = FONT(fontSize);
    ctx.lineWidth = Math.max(strokeMin, fontSize * strokeMul);
    ctx.lineJoin  = 'round';

    const runs     = _splitRuns(text);
    const hasEmoji = runs.some(r => r.type === 'emoji');
    const lineW    = _measureLine(ctx, text, emojiSize);
    // Alignement (boutons gauche/centre/droite) : bloc centré sur CX (largeur réelle blockW)
    let startX;
    if (alignSt === 'left')       startX = blockLeft;
    else if (alignSt === 'right') startX = blockLeft + blockW - lineW;
    else                          startX = CX - lineW / 2;

    ctx.textAlign = 'left';
    if (!hasEmoji) {
      ctx.strokeStyle = 'rgba(0,0,0,1)';
      ctx.strokeText(text, startX, y);
      _fxOn(ctx, effectSt, fontSize, fillColor);
      ctx.fillStyle = fillColor;
      ctx.fillText(text, startX, y);
      _fxOff(ctx);
    } else {
      let curX = Math.round(startX);
      for (const run of runs) {
        if (run.type === 'text') {
          ctx.strokeStyle = 'rgba(0,0,0,1)';
          ctx.strokeText(run.content, curX, y);
          _fxOn(ctx, effectSt, fontSize, fillColor);
          ctx.fillStyle = fillColor;
          ctx.fillText(run.content, curX, y);
          _fxOff(ctx);
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
    // Souligné (bouton U) : trait couleur + contour noir, sur la largeur du texte
    if (underlineSt && text) {
      const uy  = Math.round(y + fontSize * 0.42);
      const uh  = Math.max(2, Math.round(fontSize * 0.07));
      const pad = Math.max(2, Math.round(fontSize * strokeMul / 2));
      ctx.fillStyle = 'rgba(0,0,0,1)';
      ctx.fillRect(startX - pad, uy - uh / 2 - pad, lineW + pad * 2, uh + pad * 2);
      ctx.fillStyle = fillColor;
      ctx.fillRect(startX, uy - uh / 2, lineW, uh);
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
  // hflip (effet miroir) : DÉSACTIVÉ (le boss n'en veut plus — ça inversait texte/visage)
  const doHflip = false;
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
          // Micro-offset Y aleatoire des captions (-25..+25 px) : assez pour varier
          // l'empreinte entre variations, MAIS le texte reste la ou l'apercu le
          // montre (avant c'etait ±300px -> le rendu ne matchait pas l'apercu).
          const captionYOffset = Math.floor(Math.random() * 51) - 25;
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
              // fin EXCLUSIVE (gte/lt) au lieu de between() inclusif : 2 captions consécutives
              // (A.end == B.start) ne se chevauchent plus sur la frame frontière (sinon 1 frame en double).
              filterComplex += `;[${inputIndex}:v]format=rgba[ov${inputIndex}];[${lastOutput}][ov${inputIndex}]overlay=0:0:enable='gte(t,${startSec})*lt(t,${endSec})'[${currentOutput}]`;
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
            ...appleMetaArgs(),          // identité iPhone crédible + GPS ville (comme /reel)
            '-c:v',            'libx264',
            '-preset',         'fast',
            '-crf',            '23',
            '-c:a',            'aac',
            '-b:a',            '192k',
            // use_metadata_tags : écrit les atomes com.apple.quicktime.* ; -bitexact : efface Lavf/SEI x264
            '-movflags',       'use_metadata_tags+faststart',
            '-bitexact',
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

module.exports = { runPipeline, stopPipeline, addFolderToRunning, VARIATIONS, buildVideoFilter, renderCaptionsPng, loadEmojiImg: _loadEmojiImg, splitRuns: _splitRuns, measureLine: _measureLine };
