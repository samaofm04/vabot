"""Dashboard presentation shared by loaded and loading states."""
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

STYLE = """
<style>
.home-period-row{display:flex;gap:0;background:rgba(255,255,255,.04);border:1px solid #2a2a2a;border-radius:10px;padding:4px;font-size:13px}
.home-period-btn{background:transparent;border:0;color:#888;padding:8px 18px;border-radius:7px;font-weight:600;cursor:pointer;text-decoration:none;transition:all .15s;flex:1;text-align:center}
.home-period-btn:hover{color:#fff}
/* #0a84ff etait la seule occurrence de ce bleu dans tout le fichier : la
   pastille de periode ne ressemblait a aucun autre element actif. On rejoint
   le bleu d accent du site ; le theme Apple garde le sien. */
.home-period-active{background:rgba(59,130,246,.12) !important;color:#3b82f6 !important;box-shadow:none}
body.light .home-period-active{background:rgba(59,130,246,.10) !important;color:#3b82f6 !important}
body.light.apple .home-period-active{background:rgba(0,122,255,.10) !important;color:#007aff !important}
body.infloww .home-period-active,body.light.inflowwlight .home-period-active{background:rgba(22,119,255,.12) !important;color:#1677FF !important}
body.light .home-period-row{background:#fff;border-color:rgba(60,60,67,.12)}
.home-overview{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:24px;margin-bottom:18px}
.home-overview-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px;gap:14px;flex-wrap:wrap}
.home-overview-title{font-size:16px;font-weight:700;letter-spacing:-.01em;display:flex;align-items:center;gap:8px}
.home-overview-title small{font-size:11px;font-weight:400;color:#888;background:rgba(59,130,246,.1);padding:3px 8px;border-radius:5px}
.home-grid{display:grid;grid-template-columns:280px 1fr 1fr 1fr;gap:14px}
@media(max-width:1100px){.home-grid{grid-template-columns:1fr 1fr 1fr}}
@media(max-width:760px){.home-grid{grid-template-columns:1fr 1fr}}
.home-hero-card{background:rgba(59,130,246,.06);border:1px solid rgba(59,130,246,.25);border-radius:14px;padding:22px;grid-row:span 2;display:flex;flex-direction:column;justify-content:space-between;min-height:180px;position:relative;overflow:hidden}
.home-hero-card::before{content:'';position:absolute;inset:0;background:radial-gradient(circle at 80% 20%,rgba(59,130,246,.15),transparent 60%);pointer-events:none}
.home-hero-icon{width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg,#3b82f6,#2563eb);display:flex;align-items:center;justify-content:center;color:#fff;box-shadow:0 6px 20px rgba(59,130,246,.4);position:relative}
.home-hero-label{font-size:13px;color:#3b82f6;font-weight:600;margin-top:32px;position:relative}
.home-hero-value{font-size:36px;font-weight:800;letter-spacing:-.03em;margin-top:6px;position:relative}
.home-stat{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:14px;padding:18px 20px;position:relative;display:flex;flex-direction:column;justify-content:space-between;min-height:88px}
.home-stat-icon{position:absolute;top:18px;right:18px;width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center}
.home-stat-value{font-size:22px;font-weight:800;letter-spacing:-.02em;line-height:1.1}
.home-stat-label{font-size:12px;color:#888;margin-top:5px;font-weight:500}
/* Depuis quand le releve date. Sa couleur a une contrepartie claire : sur le
   fond creme du theme Claude, le gris ardoise du theme sombre tombe a 2,56 de
   contraste -- illisible, et c'est le genre de detail qu'on ne voit jamais
   parce qu'on relit rarement une page dans les deux themes. */
.home-fresh-chip{margin-left:6px;background:rgba(148,163,184,.14);color:#8b98ab}
body.light .home-fresh-chip{background:rgba(71,85,105,.10);color:#475569}
.home-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px}
@media(max-width:768px){.home-row{grid-template-columns:1fr}}
.home-card{background:#0f1116;border:1px solid #2a2a2a;border-radius:14px;padding:18px 20px}
.home-card-header{font-size:14px;font-weight:700;margin-bottom:14px;letter-spacing:-.01em}
body.light .home-period-row{background:#f3f4f6;border-color:#e5e7eb}
body.light .home-period-btn{color:#1c1c1e}          /* inactifs en noir, pas en bleu */
body.light .home-period-btn:hover{color:#000}
body.light .home-overview{background:#fff;border-color:#e5e7eb}
body.light .home-stat{background:#f9fafb;border-color:#e5e7eb}
body.light .home-card{background:#fff;border-color:#e5e7eb}
/* One continuous earnings surface, with column separators. */
.home-overview{container:home-earnings / inline-size}
.home-overview-head{display:grid;grid-template-columns:minmax(220px,1fr) auto auto minmax(340px,auto);gap:12px;align-items:center}
.home-overview-title{flex-wrap:wrap;min-width:0;row-gap:7px;min-height:42px}
.home-overview-heading{flex-basis:100%}
.home-overview-title small{white-space:nowrap}
.home-overview-head #fx-cur-toggle,.home-overview-head #fx-mode-toggle{margin:0!important;white-space:nowrap}
.home-overview-head .home-period-row{min-width:0;align-items:stretch}
.home-overview-head .home-period-btn{padding:8px 12px;white-space:nowrap;display:flex;align-items:center;justify-content:center}
body:not(.light) .home-overview{background:#252525;border-color:#252525;color:#f2f2f3;border-radius:16px}
body:not(.light) .home-overview .home-period-active{background:#363636!important}
.home-overview .home-grid{grid-template-columns:minmax(220px,1fr) repeat(3,minmax(0,1fr));gap:0;--home-divider:#414141}
body.light .home-overview .home-grid{--home-divider:#e0e2e6}
body .home-overview .home-hero-card,body .home-overview .home-stat{min-width:0;background:transparent;border:0;border-radius:0;box-shadow:none;box-sizing:border-box}
body .home-overview .home-hero-card{min-height:256px;padding:16px 28px 12px 10px;grid-row:span 2;justify-content:space-between}
body .home-overview .home-hero-card::before{display:none}
body .home-overview .home-hero-icon{width:60px;height:60px;border-radius:50%;background:#3075ff;color:#fff;font-size:34px;font-weight:600;line-height:1;box-shadow:none;flex-shrink:0}
.home-overview .home-hero-label{margin-top:24px}
.home-overview .home-hero-value{font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
body .home-overview .home-stat{border-left:1px solid var(--home-divider);min-height:128px;padding:24px 78px 24px 28px;justify-content:center}
.home-overview .home-stat-icon{top:50%;right:22px;transform:translateY(-50%);width:46px;height:46px;border-radius:50%}
.home-overview .home-stat-icon svg{width:25px;height:25px}
.home-overview .home-stat-value{font-size:25px;font-weight:650;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.home-overview .home-stat-label{font-size:13px;margin-top:7px}
body:not(.light) .home-overview .home-hero-label{color:#5294ff}
body:not(.light) .home-overview .home-hero-value{color:#3275ff}
body:not(.light) .home-overview .home-stat-label{color:#9d9d9f}
body .home-overview .home-stat:nth-child(n+8){grid-column:2/-1;border-top:1px solid var(--home-divider);min-height:90px}
.home-overview .home-loading-status{background:transparent;color:#aaa;padding:0;font-size:11px;letter-spacing:0;line-height:1.5}
.home-loading-status:before{content:'';display:inline-block;width:9px;height:9px;border:1.5px solid #555;border-top-color:#b7b7b7;border-radius:50%;margin-right:6px;vertical-align:-1px;animation:home-loading-spin .9s linear infinite}
.home-placeholder{display:block;background:#383838;border-radius:5px;height:1em;width:110px;max-width:100%;animation:home-loading-pulse 1.4s ease-in-out infinite}
.home-hero-value .home-placeholder{width:168px}
.home-switch-loading .home-grid .fx-amt,.home-switch-loading .hpb-amount,.home-switch-loading .hpb-percentage{color:transparent!important;user-select:none;border-radius:5px;background:linear-gradient(#383838,#383838) no-repeat left center;background-size:130px 75%;animation:home-loading-pulse 1.4s ease-in-out infinite}
.home-switch-loading .home-hero-value.fx-amt{background-size:180px 75%}
.home-switch-loading .hpb-amount{min-width:90px}.home-switch-loading .hpb-percentage{min-width:40px}
.home-switch-loading .hpb-bar,.home-switch-loading .home-fresh-chip,.home-switch-loading .home-sales-card .home-card-header>span{visibility:hidden}
.home-switch-loading .home-sales-card{position:relative}
.home-switch-loading .home-sales-card svg{visibility:hidden}
.home-switch-loading .home-sales-card:after{content:'';position:absolute;left:7%;right:3%;top:90px;bottom:42px;border-radius:6px;background:repeating-linear-gradient(to bottom,transparent 0,transparent calc(25% - 1px),#363636 calc(25% - 1px),#363636 25%);animation:home-loading-pulse 1.4s ease-in-out infinite;pointer-events:none}
.home-switch-loading .home-row{visibility:hidden}
.home-loading-chart{aspect-ratio:3/1;min-height:180px;background:repeating-linear-gradient(to bottom,transparent 0,transparent calc(25% - 1px),#363636 calc(25% - 1px),#363636 25%);margin:18px 14px 26px 46px;animation:home-loading-pulse 1.4s ease-in-out infinite}
.home-pending-chart{background:#252525;border-color:#252525;margin-top:18px;box-sizing:border-box}
body.light .home-placeholder,body.light .home-switch-loading .fx-amt,body.light .home-switch-loading .hpb-percentage{background:#e9ebee}
body.light .home-pending-chart{background:#fff;border-color:#e5e7eb}
@keyframes home-loading-pulse{50%{opacity:.5}}@keyframes home-loading-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.home-placeholder,.home-loading-status:before,.home-loading-chart,.home-switch-loading .fx-amt,.home-switch-loading .hpb-percentage,.home-switch-loading .home-sales-card:after{animation:none}}
@container home-earnings (max-width:1100px){
  .home-overview-head .home-period-btn{padding:8px;font-size:12px}
  .home-overview-title{font-size:14px}
  body .home-overview .home-stat{padding-left:20px;padding-right:58px}
  .home-overview .home-stat-icon{right:12px;width:36px;height:36px}.home-overview .home-stat-icon svg{width:22px;height:22px}
  .home-overview .home-stat-value{font-size:22px}
}
@container home-earnings (max-width:900px){
  .home-overview .home-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
  body .home-overview .home-hero-card{grid-column:1/-1;grid-row:auto;min-height:112px;flex-direction:row;align-items:center;gap:18px;padding:12px 6px 24px;border-bottom:1px solid var(--home-divider)}
  .home-overview .home-hero-label{margin-top:0}
  body .home-overview .home-stat:nth-child(3n+2){border-left:0}
}
@container home-earnings (max-width:740px){
  .home-overview-head{grid-template-columns:auto auto minmax(0,1fr);gap:10px}
  .home-overview-title{grid-column:1/-1}
  .home-overview-head .home-period-btn{white-space:normal}
}
@container home-earnings (max-width:540px){
  .home-overview .home-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .home-overview-head{grid-template-columns:auto auto 1fr}
  .home-overview-head .home-period-row{grid-column:1/-1;flex-wrap:wrap}
  .home-overview-head .home-period-btn{flex:1 1 70px}
  body .home-overview .home-stat{padding:20px 48px 20px 12px;min-height:108px}
  body .home-overview .home-stat:nth-child(n){border-left:1px solid var(--home-divider)}
  body .home-overview .home-stat:nth-child(2n){border-left:0}
  body .home-overview .home-stat:nth-child(n+8){grid-column:1/-1}
  .home-overview .home-stat-value{font-size:20px}.home-overview .home-stat-icon{right:8px;width:30px;height:30px}
  .home-overview .home-stat-icon svg{width:19px;height:19px}
  .home-overview .home-hero-value{font-size:28px}
  body .home-overview .home-hero-icon{width:52px;height:52px;font-size:30px}
}
@container home-earnings (max-width:320px){
  .home-overview .home-grid{grid-template-columns:1fr}
  body .home-overview .home-stat:nth-child(n){border-left:0;border-top:1px solid var(--home-divider)}
  body .home-overview .home-hero-card{flex-wrap:wrap}
}
</style>
"""

CATEGORIES = (
    ('Abonnements', '#18c9a3', 'rgba(24,201,163,.12)', "<svg viewBox='0 0 24 24' width='22' height='22' fill='none' stroke='currentColor' stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='m19 21-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z'/><path d='M12 7v6M9 10h6'/></svg>"),
    ('Posts', '#18c9a3', 'rgba(24,201,163,.12)', "<svg viewBox='0 0 24 24' width='22' height='22' fill='none' stroke='currentColor' stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/><path d='M14 2v6h6M8 12h8M8 16h6'/></svg>"),
    ('Messages (PPV)', '#c64af0', 'rgba(198,74,240,.12)', "<svg viewBox='0 0 24 24' width='22' height='22' fill='none' stroke='currentColor' stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M7.9 20.1 3 21l.9-4.9A9 9 0 1 1 7.9 20.1Z'/><path d='M8 12h.01M12 12h.01M16 12h.01'/></svg>"),
    ('Pourboires', '#3775ff', 'rgba(55,117,255,.12)', "<svg viewBox='0 0 24 24' width='22' height='22' fill='none' stroke='currentColor' stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M9 18h6M10 22h4M9 14a6 6 0 1 1 6 0v1a2 2 0 0 1-2 2h-2a2 2 0 0 1-2-2z'/><path d='M12 1V0M4 4 3 3M20 4l1-1M2 10H1M23 10h-1'/></svg>"),
    ('Parrainage', '#eb5b5b', 'rgba(235,91,91,.12)', "<svg viewBox='0 0 24 24' width='22' height='22' fill='none' stroke='currentColor' stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><circle cx='9' cy='7' r='4'/><path d='M2 21v-2a6 6 0 0 1 10-4.5'/><path d='m17 12 1.55 3.15 3.45.5-2.5 2.44.6 3.44-3.1-1.63-3.1 1.63.6-3.44-2.5-2.44 3.45-.5z'/></svg>"),
    ('Streams', '#3775ff', 'rgba(55,117,255,.12)', "<svg viewBox='0 0 24 24' width='22' height='22' fill='none' stroke='currentColor' stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M3 3h14v4H3zM7 10h14v4H7zM3 17h14v4H3z'/></svg>"),
)


def render_header(period, group, rate=None, timezone=None, fresh_html=''):
    if timezone is None:
        offset = datetime.now(ZoneInfo('Europe/Paris')).strftime('%z')
        timezone = f'UTC{offset[:3]}:{offset[3:]}'
    buttons = []
    for value, label in [('today', "Aujourd'hui"), ('yesterday', 'Hier'), ('week', 'Cette semaine'), ('month', 'Ce mois'), ('trente', 'Mois dernier')]:
        active = ' home-period-active' if value == period else ''
        buttons.append(f'<a href="?tab=home&home_period={value}&home_group={group}" class="home-period-btn{active}">{escape(label, quote=False)}</a>')
    rate_attr = f' data-rate="{float(rate)}"' if rate is not None else ''
    return ("<div class='home-overview-head'><div class='home-overview-title'>"
            "<span class='home-overview-heading'>Aperçu des revenus créateur</span>"
            f"<small title='Les journées sont découpées à cette heure-là'>{escape(timezone)}</small>"
            + fresh_html + "</div>"
            + f"<button id='fx-cur-toggle'{rate_attr} onclick='fxToggleCur()' title='Basculer entre dollars et euros' "
            "style='padding:7px 13px;background:#161a26;border:1px solid #2a2a2a;color:#cbd5e1;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer'>$ USD</button>"
            "<button id='fx-mode-toggle' onclick='fxToggleMode()' title='Basculer entre revenus nets et bruts' "
            "style='padding:7px 13px;background:#161a26;border:1px solid #2a2a2a;color:#cbd5e1;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer'>Net</button>"
            "<div class='home-period-row'>" + ''.join(buttons) + "</div></div>")


def render_pending(period, group, failed=False):
    from dashboard_platforms import render_selector, render_breakdown
    import re
    status = 'Relevé indisponible · nouvelle tentative…' if failed else 'Actualisation…'
    badge = f'<small class="home-loading-status" role="status">{status}</small>'
    placeholder = '<span class="home-placeholder" aria-hidden="true">&nbsp;</span>'
    cards = ("<div class='home-grid' aria-hidden='true'><div class='home-hero-card'>"
             "<div class='home-hero-icon'>$</div><div><div class='home-hero-label'>Total revenus</div>"
             "<div class='home-hero-value'>" + placeholder + '</div></div></div>')
    for label, color, bg, icon in CATEGORIES:
        cards += (f'<div class="home-stat"><div class="home-stat-icon" style="background:{bg};color:{color}">{icon}</div>'
                  f'<div><div class="home-stat-value">{placeholder}</div><div class="home-stat-label">{label}</div></div></div>')
    cards += '</div>'
    breakdown = ''
    if group == 'all':
        breakdown = render_breakdown({}, .26, .20)
        breakdown = re.sub(r'<strong class="fx-amt hpb-amount"[^>]*>[^<]*</strong>', '<strong class="hpb-amount">'+placeholder+'</strong>', breakdown)
        breakdown = re.sub(r'<span class="hpb-percentage">[^<]*</span>', '<span class="hpb-percentage">—</span>', breakdown)
        breakdown = breakdown.replace('<section class="home-platform-breakdown"', '<section aria-hidden="true" class="home-platform-breakdown"')
        breakdown = breakdown.replace('class="hpb-bar"', 'class="hpb-bar" style="visibility:hidden"')
    return (STYLE + '<div class="home-overview home-snapshot-pending" aria-busy="true">'
            + render_header(period, group, fresh_html=badge)
            + render_selector(group, period) + cards + breakdown + '</div>'
            + '<div class="home-card home-pending-chart" aria-hidden="true"><div class="home-card-header">Revenus par jour</div>'
            '<div class="home-loading-chart"></div></div>')
