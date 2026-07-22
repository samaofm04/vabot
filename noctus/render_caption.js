/**
 * render_caption.js — Rend UNE caption en PNG transparent 1080x1920 via le MÊME
 * moteur que la vidéo finale (renderCaptionsPng de pipeline-core.js).
 * Sert l'aperçu WYSIWYG de l'éditeur : ce que montre ce PNG = ce qui sera incrusté.
 *
 * Usage : node render_caption.js '{"text":"...","font":"Strong","out":"/tmp/x.png"}'
 * offset Y = 0 (pas de jitter anti-fingerprint pour l'aperçu -> position stable).
 */
const core = require('./pipeline-core.js');

(async () => {
  try {
    const arg = JSON.parse(process.argv[2] || '{}');
    const out = String(arg.out || '');
    if (!out) { process.stderr.write('out manquant'); process.exit(1); }
    const cap = { text: String(arg.text || '') };
    if (arg.font) cap.font = arg.font;
    await core.renderCaptionsPng([cap], out, 0, arg.font || null);
    process.stdout.write('OK');
  } catch (e) {
    process.stderr.write(String((e && e.stack) || e));
    process.exit(1);
  }
})();
