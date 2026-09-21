"""Dashboard platform selector; existing revenue conversion remains in MyPuls."""
from html import escape
from urllib.parse import urlencode

GROUPS = (('all', 'Toutes', ''), ('mym', 'MYM', 'M'),
          ('of_us', 'OF US', 'OF'), ('of_fr', 'OF FR', 'OF'))


def valid_group(value):
    return value if value in {row[0] for row in GROUPS} else 'all'


def in_group(name, group, mapping):
    return group == 'all' or mapping.get(str(name or '').strip().casefold()) == group


def filter_team_stats(data, group, mapping, start, end):
    if group == 'all':
        return data
    import mypuls
    txs = [tx for tx in data.get('transactions', []) if in_group(tx.get('creator'), group, mapping)]
    original = {str(c.get('name') or '').strip().casefold(): c for c in data.get('chatters', [])}
    chatters = {}
    for tx in txs:
        name = str(tx.get('chatter') or '').strip()
        key = name.casefold()
        source = original.get(key, {})
        if key not in chatters:
            chatters[key] = dict(name=source.get('name') or name or '(non attribué)',
                                 non_attribue=source.get('non_attribue', not name),
                                 ca_total=0.0, ca_ppv=0.0, ca_tips=0.0, nb_ventes=0)
        row = chatters[key]
        amount = float(tx.get('amount') or 0)
        row['ca_total'] += amount
        row['nb_ventes'] += 1
        category = mypuls.categorie_transaction(tx.get('type'))
        if category == 'Messages':
            row['ca_ppv'] += amount
        elif category == 'Tips':
            row['ca_tips'] += amount
    return mypuls._assembler_stats(txs, list(chatters.values()), start, end, data.get('diagnostic', {}))


def render_selector(group, period):
    links = []
    for key, label, badge in GROUPS:
        query = urlencode(dict(tab='home', home_period=period, home_group=key))
        icon = (f'<span aria-hidden="true" class="home-platform-icon home-platform-{key}">{badge}</span>'
                if badge else '')
        links.append(f'<a class="home-platform-btn" href="?{escape(query, quote=True)}" '
                     f'role="button" aria-pressed="{str(group == key).lower()}">{icon}<span>{label}</span></a>')
    return ('''<style>
.home-overview .home-platform-selector{display:inline-flex;align-items:center;gap:5px;padding:5px;margin:0 0 22px;border:1px solid #373a3f;border-radius:999px;background:#1c1e20;max-width:100%;box-sizing:border-box;flex-wrap:wrap}
body .home-overview .home-platform-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 17px;min-height:40px;box-sizing:border-box;border:0!important;border-radius:999px!important;background:transparent!important;color:#a5aab3!important;font-size:14px;font-weight:600;line-height:1.25;text-decoration:none;box-shadow:none!important;cursor:pointer}
body .home-overview .home-platform-btn[aria-pressed=true]{background:linear-gradient(115deg,#176bef,#6442c9)!important;color:#fff!important}
.home-overview .home-platform-btn:focus-visible{outline:2px solid #8eb4ff;outline-offset:2px}
.home-overview .home-platform-icon{width:22px;height:22px;display:inline-flex;align-items:center;justify-content:center;border-radius:50%;background:#00afe8;color:#fff;font-size:10px;font-weight:700;flex-shrink:0}
.home-overview .home-platform-mym{background:#347dff;font-size:13px}
body.light .home-overview .home-platform-selector{background:#fff;border-color:#e3e6ec}
body.light .home-overview .home-platform-btn{color:#687280!important}
</style><nav class="home-platform-selector" aria-label="Plateforme du Dashboard" data-home-group="'''
            + escape(group, quote=True) + '">' + ''.join(links) + '</nav>')


def render_breakdown(segments, mym_fee, of_fee):
    """Presentation only: preserve the existing net and gross USD amounts."""
    platforms = [('mym', 'MYM', '', 'M', mym_fee),
                 ('of_fr', 'OnlyFans', 'FR', 'OF', of_fee),
                 ('of_us', 'OnlyFans', 'US', 'OF', of_fee)]
    total = sum(float(segments.get(key, 0)) for key, *_ in platforms)
    nonnegative = all(float(segments.get(key, 0)) >= 0 for key, *_ in platforms)
    cards, bars = [], []
    for key, name, region, icon, fee in platforms:
        value = float(segments.get(key, 0))
        share = value / total * 100 if total > 0 and nonnegative else 0
        share_text = f'{share:.1f}'.replace('.', ',') + ' %' if nonnegative else '—'
        region_html = f'<span class="hpb-region">{region}</span>' if region else ''
        cards.append(
            f'<div class="hpb-platform hpb-{key}" data-platform-share="{key}" aria-label="{name} {region}">'
            f'<div class="hpb-label"><span class="hpb-logo" aria-hidden="true">{icon}</span>'
            f'<span>{name}</span>{region_html}</div>'
            f'<div class="hpb-values"><strong class="fx-amt hpb-amount" data-usd="{value:.2f}" '
            f'data-brut="{value / (1 - fee):.2f}">${value:,.2f}</strong>'
            f'<span class="hpb-share"><span class="hpb-percentage">{share_text}</span></span></div></div>')
        bars.append(f'<span class="hpb-{key}" data-platform-bar="{key}" style="flex-grow:{share:.8f}"></span>')
    return '''<style>
.home-overview .home-platform-breakdown{--hpb-bg:#191b20;--hpb-line:#2b2e35;--hpb-text:#f0f1f4;--hpb-muted:#a0a5b0;margin-top:14px;background:var(--hpb-bg);border:1px solid var(--hpb-line);border-radius:15px;overflow:hidden;color:var(--hpb-text)}
.home-platform-breakdown .hpb-mym{--hpb-color:#4087ff}.home-platform-breakdown .hpb-of_fr{--hpb-color:#9a85f5}.home-platform-breakdown .hpb-of_us{--hpb-color:#20bcd5}
.home-platform-breakdown .hpb-heading{padding:12px 18px 0;font-size:12px;font-weight:400;color:var(--hpb-muted)}
.home-platform-breakdown .hpb-platforms{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));padding:10px 0 12px}
.home-platform-breakdown .hpb-platform{min-width:0;padding:0 18px;box-sizing:border-box}
.home-platform-breakdown .hpb-platform+.hpb-platform{border-left:1px solid var(--hpb-line)}
.home-platform-breakdown .hpb-label{display:flex;align-items:center;gap:9px;margin-bottom:6px;font-size:13px;font-weight:500;color:var(--hpb-text)}
.home-platform-breakdown .hpb-logo{display:inline-flex;align-items:center;justify-content:center;width:25px;height:25px;flex-shrink:0;border-radius:50%;background:#00afd9;color:#fff;font-size:11px;font-weight:700}
.home-platform-breakdown .hpb-mym .hpb-logo{background:#367aff;font-size:16px}
.home-platform-breakdown .hpb-region{padding:3px 5px;background:var(--hpb-line);border-radius:4px;font-size:11px;color:var(--hpb-muted);font-weight:500}
.home-platform-breakdown .hpb-values{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:5px 10px}
.home-platform-breakdown .hpb-amount{font-size:21px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.7px;white-space:nowrap;color:var(--hpb-text)}
.home-platform-breakdown .hpb-share{display:flex;align-items:center;gap:5px;font-size:11px;font-weight:400;color:var(--hpb-muted);white-space:nowrap;font-variant-numeric:tabular-nums}
.home-platform-breakdown .hpb-share:before{content:"";width:5px;height:5px;border-radius:50%;background:var(--hpb-color)}
.home-platform-breakdown .hpb-bar{display:flex;gap:3px;height:4px;margin:0 18px 12px;border-radius:4px;overflow:hidden}
.home-platform-breakdown .hpb-bar span{flex-basis:0;min-width:0;background:var(--hpb-color)}
body.light .home-overview .home-platform-breakdown{--hpb-bg:#f7f8fa;--hpb-line:#e3e6ec;--hpb-text:#20252e;--hpb-muted:#687280}
@media(max-width:700px){.home-platform-breakdown .hpb-platforms{grid-template-columns:1fr;padding:4px 17px 9px}.home-platform-breakdown .hpb-platform{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0}.home-platform-breakdown .hpb-platform+.hpb-platform{border-left:0;border-top:1px solid var(--hpb-line)}.home-platform-breakdown .hpb-label{margin:0}.home-platform-breakdown .hpb-values{flex-direction:column;align-items:flex-end}.home-platform-breakdown .hpb-amount{font-size:20px}.home-platform-breakdown .hpb-heading{padding:15px 17px 0}.home-platform-breakdown .hpb-bar{margin:0 17px 17px}}
@media(max-width:400px){.home-platform-breakdown .hpb-label{gap:5px;font-size:12px}.home-platform-breakdown .hpb-logo{width:25px;height:25px}.home-platform-breakdown .hpb-amount{font-size:19px}}
</style><section class="home-platform-breakdown" aria-label="Répartition par plateforme">
<div class="hpb-heading">Répartition par plateforme</div><div class="hpb-platforms">''' + ''.join(cards) + (
        '</div><div class="hpb-bar" aria-hidden="true">' + ''.join(bars) + '</div></section>')
