# Run collect.sh first; see README.md.
import csv, datetime as dt, html
from collections import Counter

Y=2026
p=lambda s: dt.datetime.strptime(f"{Y}-{s}","%Y-%m-%dT%H:%M:%S") if s else None
rows=[dict(n=int(n),created=p(c),closed=p(cl),comments=int(cm)) for n,c,cl,cm in csv.reader(open("prs.csv"))]
mainm={int(l) for l in open("merged.txt")}
unm={int(l) for l in open("closed-unmerged.txt")}
diff={int(n):(int(a),int(d),int(f)) for n,a,d,f in csv.reader(open("diffstat.csv"))}
for r in rows:
    r["merged"]= r["closed"] is not None and r["n"] not in unm

N=len(rows); NM=sum(r["merged"] for r in rows); NMAIN=sum(1 for r in rows if r["n"] in mainm)
first=min(r["created"] for r in rows); last=max(r["created"] for r in rows)
days=(last-first).days+1
durs=sorted((r["closed"]-r["created"]).total_seconds()/3600 for r in rows if r["merged"])
q=lambda f: durs[min(len(durs)-1,int(f*len(durs)))]
cs=[r["comments"] for r in rows]
sizes=sorted(v[0]+v[1] for v in diff.values())
add=sum(v[0] for v in diff.values()); dele=sum(v[1] for v in diff.values())

def bucket(vals,bins): return [sum(1 for v in vals if lo<=v<hi) for lo,hi,_ in bins]

# series
wk=Counter()
for r in rows:
    if r["merged"]:
        d=r["closed"]; wk[(d-dt.timedelta(days=d.weekday())).date()]+=1
w=min(wk); allw=[]
while w<=max(wk): allw.append(w); w+=dt.timedelta(days=7)
S_week=([f"{x:%b %-d}" for x in allw],[wk.get(x,0) for x in allw],"PRs merged, week of {l}: {v}")

mo=Counter(f"{r['created']:%Y-%m}" for r in rows); ms=sorted(mo)
S_month=([dt.datetime.strptime(m,"%Y-%m").strftime("%b") for m in ms],[mo[m] for m in ms],"{l}: {v} PRs opened")

DB=[(0,1,"<1h"),(1,4,"1–4h"),(4,12,"4–12h"),(12,24,"12–24h"),(24,48,"1–2d"),(48,168,"2–7d"),(168,1e9,">7d")]
S_dur=([b[2] for b in DB],bucket(durs,DB),"{l} to merge: {v} PRs")
CB=[(0,1,"0"),(1,2,"1"),(2,3,"2"),(3,5,"3–4"),(5,9,"5–8"),(9,15,"9–14"),(15,25,"15–24"),(25,1e9,"25+")]
S_com=([b[2] for b in CB],bucket(cs,CB),"{l} comments: {v} PRs")
SB=[(0,10,"<10"),(10,50,"10–49"),(50,200,"50–199"),(200,500,"200–499"),(500,1500,"500–1499"),(1500,1e9,"1500+")]
S_size=([b[2] for b in SB],bucket(sizes,SB),"{l} lines changed: {v} PRs")
order=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]; dow=Counter(r["created"].strftime("%a") for r in rows)
S_dow=(order,[dow[d] for d in order],"{l}: {v} PRs opened")
hr=Counter(r["created"].hour//3 for r in rows)
S_hr=([f"{h*3:02d}" for h in range(8)],[hr.get(h,0) for h in range(8)],"{l}:00–{l}:59 UTC block: {v} PRs opened")

def chart(cid,title,sub,series,unit="",every=1,wide=False):
    labels,vals,tip=series
    m=max(vals) or 1
    cols=""; ticks=""
    for i,(l,v) in enumerate(zip(labels,vals)):
        t=html.escape(tip.replace("{l}",l).replace("{v}",f"{v:,}"))
        cap=f'<span class="cap">{v}</span>' if (v==m or len(labels)<=8) else ""
        cols+=(f'<div class="col">{cap}'
               f'<div class="bar" style="height:{v/m*100:.2f}%"></div>'
               f'<span class="tip">{t}</span></div>')
        ticks+=f'<div class="tk">{html.escape(l) if i%every==0 else ""}</div>'
    tbl="".join(f"<tr><td>{html.escape(l)}</td><td>{v:,}</td></tr>" for l,v in zip(labels,vals))
    return f'''<figure class="card{" wide" if wide else ""}">
<figcaption><h3>{title}</h3><p>{sub}</p></figcaption>
<div class="plot" role="img" aria-label="{html.escape(title)}. {html.escape(sub)}">
<div class="cols">{cols}</div><div class="ticks">{ticks}</div></div>
<details><summary>Table</summary><table><thead><tr><th>{unit or "Bucket"}</th><th>PRs</th></tr></thead><tbody>{tbl}</tbody></table></details>
</figure>'''

def tile(label,value,note):
    return f'<div class="tile"><span class="tl">{label}</span><span class="tv">{value}</span><span class="tn">{note}</span></div>'

CSS = """
:root{color-scheme:light;--plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--base:#c3c2b7;--series:#2a78d6;--ring:rgba(11,11,11,0.10);--tipbg:#0b0b0b;--tipfg:#fcfcfb;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--plane:#0d0d0d;--surface:#1a1a19;
--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--base:#383835;--series:#3987e5;
--ring:rgba(255,255,255,0.10);--tipbg:#fcfcfb;--tipfg:#0b0b0b;}}
:root[data-theme="dark"]{color-scheme:dark;--plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--base:#383835;--series:#3987e5;--ring:rgba(255,255,255,0.10);--tipbg:#fcfcfb;--tipfg:#0b0b0b;}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1040px;margin:0 auto;padding:40px 20px 64px}
header{margin-bottom:28px}
h1{font-size:30px;line-height:1.2;margin:0 0 6px;letter-spacing:-0.01em}
.sub{color:var(--ink2);margin:0;font-size:15px}
.hero{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:22px 24px;margin:24px 0 28px}
.heron{font-size:52px;font-weight:600;line-height:1;letter-spacing:-0.02em;display:block}
.herol{color:var(--ink2);font-size:14px;display:block;margin-top:8px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:10px;margin-bottom:28px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:15px 17px;
display:flex;flex-direction:column;gap:4px}
.tl{color:var(--ink2);font-size:12.5px}
.tv{font-size:26px;font-weight:600;letter-spacing:-0.01em}
.tn{color:var(--muted);font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:14px;padding:18px 20px 14px;margin:0}
.card.wide{grid-column:1/-1}
figcaption h3{margin:0;font-size:15px;font-weight:600}
figcaption p{margin:3px 0 18px;color:var(--ink2);font-size:12.5px}
.plot{overflow-x:auto;overflow-y:hidden;padding-bottom:2px;margin-bottom:14px}
.cols{display:flex;align-items:flex-end;gap:2px;height:150px;border-bottom:1px solid var(--base);min-width:100%}
.col{flex:1 1 0;min-width:20px;height:100%;display:flex;flex-direction:column;
justify-content:flex-end;align-items:center;position:relative}
.bar{width:100%;max-width:24px;min-height:2px;background:var(--series);border-radius:4px 4px 0 0}
.cap{font-size:10.5px;color:var(--ink2);font-variant-numeric:tabular-nums;margin-bottom:3px;white-space:nowrap;line-height:1}
.ticks{display:flex;gap:2px;margin-top:7px;min-width:100%}
.tk{flex:1 1 0;min-width:20px;text-align:center;font-size:10.5px;color:var(--muted);
white-space:nowrap;font-variant-numeric:tabular-nums}
.tip{position:absolute;bottom:calc(100% + 4px);left:50%;transform:translateX(-50%);background:var(--tipbg);
color:var(--tipfg);font-size:11.5px;padding:5px 9px;border-radius:7px;white-space:nowrap;opacity:0;
pointer-events:none;transition:opacity .1s;z-index:5}
.col:hover .tip{opacity:1}
.col:hover .bar{filter:brightness(1.15)}
details{margin-top:4px;border-top:1px solid var(--grid);padding-top:8px}
summary{cursor:pointer;font-size:12px;color:var(--muted)}
table{border-collapse:collapse;margin-top:8px;font-size:12.5px;width:100%}
th,td{text-align:left;padding:3px 10px 3px 0;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums}
th{color:var(--ink2);font-weight:600}
.note{color:var(--ink2);font-size:13px;margin:26px 0 0;padding-top:18px;border-top:1px solid var(--grid)}
.note strong{color:var(--ink)}
h2{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
margin:32px 0 12px}
"""

body=f'''<div class="wrap">
<header>
<h1>fleche, six months in</h1>
<p class="sub">Every pull request from #1 to #{max(r["n"] for r in rows)} — {first:%-d %B} to {last:%-d %B %Y}.</p>
</header>

<div class="hero"><span class="heron">{NM:,}</span>
<span class="herol">pull requests merged in {days} days — one every {days*24/NM:.1f} hours, around the clock</span></div>

<div class="tiles">
{tile("Opened",f"{N:,}","PRs, all time")}
{tile("Merged",f"{NM/N:.0%}","{} of {} — only {} closed unmerged".format(NM,N,N-NM-sum(1 for r in rows if r["closed"] is None)))}
{tile("Median time to merge",f"{q(.5):.0f} h","p90 {:.0f} h".format(q(.9)))}
{tile("Landed same day",f"{sum(1 for d in durs if d<24)/len(durs):.0%}","merged within 24 h")}
{tile("Lines merged",f"+{add/1000:.1f}k","−{:,} removed".format(dele))}
{tile("Releases",f"{41}","tagged versions")}
</div>

<h2>Throughput</h2>
<div class="grid">
{chart("w","PRs merged per week","Weeks starting Monday — every merge, into main or into a stacked branch.",S_week,"Week",every=3,wide=True)}
{chart("m","PRs opened per month","August is a partial month, through the 7th.",S_month,"Month")}
{chart("d","Time from open to merge","{:,} merged PRs. Median {:.0f} h, p75 {:.0f} h, longest {:.0f} days.".format(len(durs),q(.5),q(.75),max(durs)/24),S_dur,"Duration")}
{chart("c","Conversation comments per PR","{:,} comments across {:,} PRs. {:.0%} drew at least one.".format(sum(cs),N,sum(1 for c in cs if c>0)/len(cs)),S_com,"Comments")}
{chart("s","PR size, lines changed","{:,} PRs squash-merged into main. Median {:,} lines.".format(len(sizes),sizes[len(sizes)//2]),S_size,"Lines")}
{chart("dw","PRs opened by weekday","Monday is the biggest day by a wide margin.",S_dow,"Day")}
{chart("h","PRs opened by hour, UTC","Three-hour blocks. The 03:00–06:00 spike is scheduled automation.",S_hr,"Hour (UTC)")}
</div>

<p class="note"><strong>Where the numbers come from.</strong> PR timings and comment counts
come from the GitHub API; sizes, merge dates and commit counts from the git history of
<code>main</code>. &ldquo;Merged&rdquo; counts every PR that landed somewhere — {NMAIN:,} squash-merged
straight into <code>main</code>, another {NM-NMAIN:,} merged into a parent PR branch first.
Comment counts are conversation comments; inline review-thread comments are a separate
per-PR API call and are not included. Pre-squash commit counts are not recoverable —
the squash messages don&rsquo;t carry the original commit list.</p>
</div>'''

open("stats.html","w").write(f"<title>fleche, six months in</title>\n<style>{CSS}</style>\n{body}\n")
print("wrote stats.html", len(open("stats.html").read()), "bytes")
print(f"check: N={N} NM={NM} NMAIN={NMAIN} durs={len(durs)} sizes={len(sizes)}")
