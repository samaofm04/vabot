/**
 * render_caption.js — Rend UNE caption en PNG transparent via le MÊME moteur que
 * la vidéo finale (renderCaptionsPng de pipeline-core.js).
 * Sert l'aperçu WYSIWYG de l'éditeur : ce que montre ce PNG = ce qui sera incrusté.
 *
 * Usage : node render_caption.js '{"text":"...","font":"Strong","size":48,
 *          "color":"#ffffff","align":"center","case":"none","bold":true,
 *          "italic":false,"underline":false,"tight":true,"out":"/tmp/x.png"}'
 *
 * tight:true -> on DÉTOURE le PNG à la boîte réelle du texte (pixels non transparents)
 *   et on imprime sur stdout {"bbox":{x,y,w,h,W,H}} (coords dans le cadre 1080x1920).
 *   L'éditeur positionne cette image détourée où il veut (drag) : le cadre épouse
 *   pile le texte et déplacer = bouger la vraie image (la police reste, pas de fallback).
 * offset Y = 0 (pas de jitter anti-fingerprint pour l'aperçu -> position stable).
 */
const core = require('./pipeline-core.js');
const { createCanvas, loadImage } = require('@napi-rs/canvas');
const fs = require('fs');

(async () => {
  try {
    const arg = JSON.parse(process.argv[2] || '{}');
    const out = String(arg.out || '');
    if (!out) { process.stderr.write('out manquant'); process.exit(1); }
    const cap = { text: String(arg.text || '') };
    ['font', 'size', 'color', 'x', 'y', 'align', 'case', 'bold', 'italic', 'underline',
     'box', 'boxColor', 'effect', 'wrapW']
      .forEach(k => { if (arg[k] !== undefined && arg[k] !== null) cap[k] = arg[k]; });
    await core.renderCaptionsPng([cap], out, 0, arg.font || null);

    if (arg.tight) {
      const img = await loadImage(out);
      const W = img.width, H = img.height;
      const cv = createCanvas(W, H);
      const cx = cv.getContext('2d');
      cx.drawImage(img, 0, 0);
      const d = cx.getImageData(0, 0, W, H).data;
      let minx = W, miny = H, maxx = -1, maxy = -1;
      for (let y = 0; y < H; y++) {
        const row = y * W * 4;
        for (let x = 0; x < W; x++) {
          if (d[row + x * 4 + 3] > 8) {            // pixel non (quasi) transparent
            if (x < minx) minx = x; if (x > maxx) maxx = x;
            if (y < miny) miny = y; if (y > maxy) maxy = y;
          }
        }
      }
      if (maxx >= minx && maxy >= miny) {
        const pad = 8;                              // petit air autour du texte
        minx = Math.max(0, minx - pad); miny = Math.max(0, miny - pad);
        maxx = Math.min(W - 1, maxx + pad); maxy = Math.min(H - 1, maxy + pad);
        const cw = maxx - minx + 1, ch = maxy - miny + 1;
        const cc = createCanvas(cw, ch);
        cc.getContext('2d').drawImage(img, minx, miny, cw, ch, 0, 0, cw, ch);
        fs.writeFileSync(out, cc.toBuffer('image/png'));
        process.stdout.write(JSON.stringify({ bbox: { x: minx, y: miny, w: cw, h: ch, W, H } }));
        return;
      }
    }
    process.stdout.write('OK');
  } catch (e) {
    process.stderr.write(String((e && e.stack) || e));
    process.exit(1);
  }
})();
