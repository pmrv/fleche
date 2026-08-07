# Run collect.sh first; see README.md.
import csv, datetime as dt, statistics as st
from collections import Counter, defaultdict

Y = 2026
def parse(s):
    if not s: return None
    return dt.datetime.strptime(f"{Y}-{s}", "%Y-%m-%dT%H:%M:%S")

rows=[]
for n,c,cl,cm in csv.reader(open("prs.csv")):
    rows.append(dict(n=int(n), created=parse(c), closed=parse(cl), comments=int(cm)))

merged=set(int(l) for l in open("merged.txt"))
unmerged=set(int(l) for l in open("closed-unmerged.txt"))
diff={}
for n,a,d,f in csv.reader(open("diffstat.csv")):
    diff[int(n)]=(int(a),int(d),int(f))

for r in rows:
    r["merged"] = (r["closed"] is not None) and (r["n"] not in unmerged)
    r["open"]   = r["closed"] is None

N=len(rows)
NM=sum(r["merged"] for r in rows)
NO=sum(r["open"] for r in rows)
first=min(r["created"] for r in rows); last=max(r["created"] for r in rows)
days=(last-first).days+1

print(f"PROJECT WINDOW  {first:%Y-%m-%d} -> {last:%Y-%m-%d}   ({days} days, {days/7:.1f} weeks)")
print(f"PRs opened      {N}")
print(f"PRs merged      {NM}  ({NM/N:.0%})")
NMAIN=sum(1 for r in rows if r["n"] in merged)
print(f"  ├─ squash-merged into main    {NMAIN}")
print(f"  └─ merged into another PR branch (stacked)  {NM-NMAIN}")
print(f"PRs closed unmerged {N-NM-NO}   still open {NO}")
print(f"Merge rate      {NM/days:.2f}/day   {NM/days*7:.1f}/week")
tot_add=sum(v[0] for v in diff.values()); tot_del=sum(v[1] for v in diff.values())
print(f"Lines merged    +{tot_add:,} / -{tot_del:,}  across {sum(v[2] for v in diff.values()):,} file-touches")
print(f"Comments        {sum(r['comments'] for r in rows):,} conversation comments on PRs")
print()

def hist(title, labels, counts, width=44, note=""):
    m=max(counts) or 1
    w=max(len(l) for l in labels)
    print(f"── {title} " + "─"*(max(0,58-len(title))))
    for l,c in zip(labels,counts):
        bar="█"*round(c/m*width)
        print(f"  {l:>{w}} │{bar:<{width}} {c}")
    if note: print(f"  {note}")
    print()

# 1. PRs merged per week
wk=Counter()
for r in rows:
    if r["merged"]:
        d=r["closed"] or r["created"]
        wk[(d - dt.timedelta(days=d.weekday())).date()]+=1
weeks=sorted(wk)
allw=[]
d=weeks[0]
while d<=weeks[-1]:
    allw.append(d); d+=dt.timedelta(days=7)
hist("PRs merged per week", [f"{w:%b %d}" for w in allw], [wk.get(w,0) for w in allw])

# 2. PRs opened per month
mo=Counter(f"{r['created']:%Y-%m}" for r in rows)
ms=sorted(mo)
hist("PRs opened per month", ms, [mo[m] for m in ms])

# 3. Open duration (merged PRs)
durs=sorted((r["closed"]-r["created"]).total_seconds()/3600 for r in rows if r["merged"] and r["closed"])
bins=[(0,1,"< 1 h"),(1,4,"1–4 h"),(4,12,"4–12 h"),(12,24,"12–24 h"),(24,48,"1–2 d"),(48,168,"2–7 d"),(168,1e9,"> 7 d")]
hist("PR open duration (merged PRs)",
     [b[2] for b in bins],
     [sum(1 for d in durs if b[0]<=d<b[1]) for b in bins])
q=lambda p: durs[min(len(durs)-1,int(p*len(durs)))]
print(f"  median {q(.5):.1f} h   p25 {q(.25):.1f} h   p75 {q(.75):.1f} h   p90 {q(.9):.1f} h   max {durs[-1]/24:.1f} d")
print(f"  {sum(1 for d in durs if d<24)/len(durs):.0%} of merged PRs landed within 24 h")
print()

# 4. Comments per PR
cbins=[(0,1,"0"),(1,2,"1"),(2,3,"2"),(3,5,"3–4"),(5,9,"5–8"),(9,15,"9–14"),(15,25,"15–24"),(25,1e9,"25+")]
cs=[r["comments"] for r in rows]
hist("Conversation comments per PR",
     [b[2] for b in cbins],
     [sum(1 for c in cs if b[0]<=c<b[1]) for b in cbins])
scs=sorted(cs)
print(f"  total {sum(cs):,}   mean {sum(cs)/len(cs):.1f}   median {scs[len(scs)//2]}   busiest PR #{max(rows,key=lambda r:r['comments'])['n']} with {max(cs)} comments")
print(f"  {sum(1 for c in cs if c>0)/len(cs):.0%} of PRs drew at least one comment")
print()

# 5. PR size (merged, by lines changed)
sizes=sorted(diff[n][0]+diff[n][1] for n in diff)
sbins=[(0,10,"< 10"),(10,50,"10–49"),(50,200,"50–199"),(200,500,"200–499"),(500,1500,"500–1499"),(1500,1e9,"1500+")]
hist("PR size — lines changed (merged)",
     [b[2] for b in sbins],
     [sum(1 for s in sizes if b[0]<=s<b[1]) for b in sbins])
print(f"  median {sizes[len(sizes)//2]:,} lines   mean {sum(sizes)/len(sizes):,.0f}   largest {max(sizes):,}")
print()

# 6. Day of week / hour of day
dow=Counter(r["created"].strftime("%a") for r in rows)
order=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
hist("PRs opened by weekday", order, [dow[d] for d in order])

hr=Counter(r["created"].hour//3 for r in rows)
hist("PRs opened by hour (UTC)", [f"{h*3:02d}–{h*3+2:02d}" for h in range(8)], [hr.get(h,0) for h in range(8)])
