#!/usr/bin/env python3
"""Assemble ONE self-contained, tabbed HTML dashboard for a run, so the QA team
has everything in a single file: the narrative report, every test case (plan +
result), the per-test request/response evidence, the stress run and the
findings register.

Self-contained: all data is embedded as JSON and rendered by inline vanilla JS;
no network, no CDN — it opens from a file:// path. Light/dark via the OS theme.

Inputs (all optional, best-effort):
  docs/<service>/<run>/QA-REPORT.html   (Overview tab; falls back to QA-REPORT.md)
  test-cases/<service>/<run>/index.csv + <category>/<ID>.md   (Test cases tab)
  docs/<service>/<run>/evidence/<ID>/req*.json + resp*.json   (Request/Response tab)
  docs/<service>/<run>/stress/summary.json + stress-results.md (Stress tab)
  docs/<service>/<run>/results/*.json                          (status/observed/severity)

Output: docs/<service>/<run>/QA-REPORT-full.html

Usage:
  python -I scripts/build_html_report.py --run-dir docs/<service>/<run>
  (test-cases dir is derived; override with --cases-dir)
"""
import argparse
import csv
import glob
import html
import json
import os
import re

CATEGORIES = ["functional", "regression", "non-functional", "security", "stress"]
SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "": 9, None: 9}


def parse_case(path):
    text = open(path, encoding="utf-8").read()
    out = {"fields": {}, "sections": {}}
    m = re.search(r"^#\s+(.*)$", text, re.M)
    line = m.group(1).strip() if m else os.path.basename(path)
    tm = re.match(r"\s*([A-Z]+-\d+)\s*[—-]\s*(.*)", line)
    out["id"] = tm.group(1) if tm else os.path.splitext(os.path.basename(path))[0]
    out["title"] = tm.group(2).strip() if tm else line
    for k, v in re.findall(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$", text, re.M):
        key = k.strip().lower()
        if key in ("field", "") or re.fullmatch(r":?-{2,}:?", key):
            continue
        out["fields"][key] = v.strip()
    for sec, body in re.findall(r"^##\s+(.+?)\s*$\n(.*?)(?=^##\s|\Z)", text, re.M | re.S):
        out["sections"][sec.strip().lower()] = body.strip()
    return out


def load_index(cases_dir):
    idx = {}
    p = os.path.join(cases_dir, "index.csv")
    if os.path.exists(p):
        for row in csv.DictReader(open(p, encoding="utf-8")):
            idx[row["id"]] = row
    return idx


def collect_cases(cases_dir):
    idx = load_index(cases_dir)
    cases = []
    for cat in CATEGORIES:
        for f in sorted(glob.glob(os.path.join(cases_dir, cat, "*.md"))):
            c = parse_case(f)
            row = idx.get(c["id"], {})
            fld, sec = c["fields"], c["sections"]
            actual = sec.get("actual result", "")
            sm = re.search(r"Status:\s*([A-Z ]+)", actual)
            vm = re.search(r"Severity:?\s*\**\s*([A-Za-z]+)", actual)
            obs = re.search(r"Observed:\s*(.*)", actual)
            cases.append({
                "id": c["id"], "category": cat, "title": c["title"],
                "priority": fld.get("priority", row.get("priority", "")),
                "endpoint": fld.get("endpoint", row.get("endpoint", "")),
                "traces": fld.get("traces to", row.get("traces_to", "")),
                "preconditions": fld.get("preconditions", ""),
                "testData": fld.get("test data", ""),
                "automation": fld.get("automation", ""),
                "steps": sec.get("steps", ""),
                "expected": sec.get("expected result", ""),
                "status": (row.get("status") or (sm.group(1).strip() if sm else "NOT RUN")),
                "severity": (vm.group(1).upper() if vm and vm.group(1).upper() in SEV_ORDER else ""),
                "observed": (obs.group(1).strip() if obs else ""),
            })
    return cases


def collect_evidence(run_dir):
    evid = os.path.join(run_dir, "evidence")
    out = []
    if not os.path.isdir(evid):
        return out
    for tid in sorted(os.listdir(evid)):
        d = os.path.join(evid, tid)
        if not os.path.isdir(d):
            continue
        pairs = []
        reqs = sorted(glob.glob(os.path.join(d, "req*.json")),
                      key=lambda p: int(re.search(r"(\d+)", os.path.basename(p)).group(1)))
        for rq in reqs:
            n = re.search(r"(\d+)", os.path.basename(rq)).group(1)
            rsp = os.path.join(d, f"resp{n}.json")
            try:
                req = json.load(open(rq, encoding="utf-8"))
            except Exception:
                continue
            resp = json.load(open(rsp, encoding="utf-8")) if os.path.exists(rsp) else None
            pairs.append({"n": n, "req": req, "resp": resp})
        if pairs:
            out.append({"id": tid, "pairs": pairs})
    return out


def overview_html(run_dir):
    hp = os.path.join(run_dir, "QA-REPORT.html")
    if os.path.exists(hp):
        t = open(hp, encoding="utf-8").read()
        m = re.search(r"<body[^>]*>(.*)</body>", t, re.S | re.I)
        if m:
            return m.group(1)
    mp = os.path.join(run_dir, "QA-REPORT.md")
    if os.path.exists(mp):
        return "<pre class='mdfallback'>" + html.escape(open(mp, encoding="utf-8").read()) + "</pre>"
    return "<p>No QA-REPORT found.</p>"


def stress_data(run_dir):
    sd = os.path.join(run_dir, "stress")
    summ = os.path.join(sd, "summary.json")
    notes = os.path.join(sd, "stress-results.md")
    return {
        "summary": json.load(open(summ, encoding="utf-8")) if os.path.exists(summ) else None,
        "notes": open(notes, encoding="utf-8").read() if os.path.exists(notes) else "",
    }


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1c2128;--mut:#5b6572;--line:#d8dee4;--accent:#2563eb;
--pass:#1b7f3b;--fail:#c0271c;--blk:#7b3ff2;--notrun:#6b7280;
--CRIT:#b71c1c;--HIGH:#e65100;--MED:#b58100;--LOW:#2e7d32;--codebg:#f3f5f8;}
@media (prefers-color-scheme:dark){:root{--bg:#0f1318;--panel:#171c22;--ink:#e6edf3;--mut:#9aa6b2;
--line:#2a313a;--accent:#5b9bff;--codebg:#11161c;--MED:#d7a200;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
header{padding:20px 16px 0;max-width:1200px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:12px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.chip{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:12px;font-weight:600}
.chip b{font-weight:800}
.verdict{display:inline-block;border-radius:6px;padding:4px 12px;font-weight:800;font-size:12px;color:#fff;background:var(--accent)}
nav{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);margin-top:14px}
.navinner{max-width:1200px;margin:0 auto;display:flex;gap:4px;padding:0 12px;overflow-x:auto}
.tab{appearance:none;border:0;background:none;color:var(--mut);font:inherit;font-weight:600;
padding:12px 14px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap}
.tab[aria-selected=true]{color:var(--accent);border-color:var(--accent)}
main{max-width:1200px;margin:0 auto;padding:18px 16px 60px}
.view{display:none}.view.active{display:block}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;align-items:center}
input[type=search]{flex:1;min-width:200px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink)}
.filterbtn{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:5px 11px;cursor:pointer;font-size:12px;font-weight:600}
.filterbtn.on{background:var(--accent);color:#fff;border-color:var(--accent)}
table{border-collapse:collapse;width:100%;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:9px 11px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top;font-size:13px}
th{background:color-mix(in srgb,var(--panel) 85%,var(--line));font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
tr:last-child td{border-bottom:0}
tr.caserow{cursor:pointer}
tr.caserow:hover td{background:color-mix(in srgb,var(--panel) 80%,var(--accent) 8%)}
.badge{display:inline-block;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:800;color:#fff}
.PASS{background:var(--pass)}.FAIL{background:var(--fail)}.BLOCKED{background:var(--blk)}
.NOTRUN,.PLANNED{background:var(--notrun)}.UNVERIFIED{background:var(--blk)}
.sev{display:inline-block;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:800;color:#fff}
.sev.CRITICAL{background:var(--CRIT)}.sev.HIGH{background:var(--HIGH)}.sev.MEDIUM{background:var(--MED)}.sev.LOW{background:var(--LOW)}
.detail td{background:var(--codebg)}
.kv{display:grid;grid-template-columns:140px 1fr;gap:4px 12px;margin:2px 0 10px}
.kv div:nth-child(odd){color:var(--mut);font-weight:600}
.pre{white-space:pre-wrap;word-break:break-word;background:var(--codebg);border:1px solid var(--line);border-radius:8px;padding:10px;font:12px/1.5 Consolas,ui-monospace,Menlo,monospace;margin:4px 0}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:8px 0;overflow:hidden}
summary{cursor:pointer;padding:11px 14px;font-weight:700;display:flex;gap:10px;align-items:center}
summary::-webkit-details-marker{display:none}
summary .mut{color:var(--mut);font-weight:500}
.evbody{padding:0 14px 12px}
.reqline{font:12px Consolas,ui-monospace,monospace;font-weight:700;margin:8px 0 2px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:10px;padding:12px 14px}
.card h3{margin:0 0 4px;font-size:14px}
.card.CRITICAL{border-left-color:var(--CRIT)}.card.HIGH{border-left-color:var(--HIGH)}
.card.MEDIUM{border-left-color:var(--MED)}.card.LOW{border-left-color:var(--LOW)}
.ov :is(h1,h2,h3){border:0}.ov table{margin:10px 0}.ov code{background:var(--codebg);padding:1px 5px;border-radius:4px}
.ov pre{background:var(--codebg);padding:10px;border-radius:8px;overflow:auto}
.empty{color:var(--mut);padding:24px;text-align:center}
.meters{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:4px 0 14px}
.meter{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.meterhd{font-size:13px;margin-bottom:8px}.meterhd b{font-size:16px}
.bar{height:8px;background:color-mix(in srgb,var(--line) 70%,transparent);border-radius:99px;overflow:hidden}
.bar span{display:block;height:100%;background:var(--accent);border-radius:99px}
#regression h3{margin:18px 0 6px;font-size:14px;border:0}
.chip b.good,.good{color:var(--pass)}.chip b.bad,.bad{color:var(--fail)}
.count{color:var(--mut);font-size:12px;margin-left:auto}
@media(max-width:560px){.kv{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="sub" id="sub"></div>
  <div class="chips" id="chips"></div>
</header>
<nav><div class="navinner" id="tabs" role="tablist"></div></nav>
<main>
  <section class="view active" id="view-overview"><div class="ov" id="overview"></div></section>
  <section class="view" id="view-cases">
    <div class="toolbar">
      <input type="search" id="caseSearch" placeholder="Filter cases by id, title, endpoint, status…">
      <span id="catFilters"></span><span class="count" id="caseCount"></span>
    </div>
    <table><thead><tr><th>Test #</th><th>Cat</th><th>Pri</th><th>Title</th><th>Endpoint</th><th>Status</th><th>Sev</th></tr></thead>
    <tbody id="caseBody"></tbody></table>
  </section>
  <section class="view" id="view-evidence">
    <div class="toolbar"><input type="search" id="evSearch" placeholder="Filter by test id…"><span class="count" id="evCount"></span></div>
    <div id="evidence"></div>
  </section>
  <section class="view" id="view-stress"><div id="stress"></div></section>
  <section class="view" id="view-findings"><div class="cards" id="findings"></div></section>
  <section class="view" id="view-coverage"><div id="coverage"></div></section>
  <section class="view" id="view-regression"><div id="regression"></div></section>
</main>
<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const esc = s => (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const stClass = s => (s||'').toUpperCase().replace(' ','');
const pj = o => { try { return JSON.stringify(o,null,2); } catch(e){ return String(o); } };

// header
$('#sub').textContent = `${DATA.meta.service}  ·  branch ${DATA.meta.branch}  ·  env ${DATA.meta.env}  ·  run ${DATA.meta.run}`;
const c = DATA.counts;
$('#chips').innerHTML =
  `<span class="chip"><span class="verdict">${esc(DATA.meta.verdict)}</span></span>`+
  `<span class="chip">Total <b>${c.total}</b></span>`+
  `<span class="chip" style="color:var(--pass)">PASS <b>${c.PASS||0}</b></span>`+
  `<span class="chip" style="color:var(--fail)">FAIL <b>${c.FAIL||0}</b></span>`+
  `<span class="chip">BLOCKED <b>${c.BLOCKED||0}</b></span>`;

// tabs
const TABS=[['overview','Overview'],['cases','Test cases'],['evidence','Request / Response'],['stress','Stress'],['findings','Findings'],['coverage','Coverage'],['regression','Regression']];
const tabsEl=$('#tabs');
TABS.forEach(([id,label],i)=>{const b=document.createElement('button');b.className='tab';b.textContent=label;
  b.setAttribute('role','tab');b.setAttribute('aria-selected',i===0);b.onclick=()=>select(id);tabsEl.appendChild(b);b.dataset.id=id;});
function select(id){document.querySelectorAll('.tab').forEach(t=>t.setAttribute('aria-selected',t.dataset.id===id));
  document.querySelectorAll('.view').forEach(v=>v.classList.toggle('active',v.id==='view-'+id));
  if(location.hash.slice(1)!==id) history.replaceState(null,'','#'+id);}

// overview
$('#overview').innerHTML = DATA.overviewHtml;

// cases
let catFilter='all', q='';
const cats=['all',...[...new Set(DATA.cases.map(x=>x.category))]];
$('#catFilters').innerHTML=cats.map(k=>`<button class="filterbtn${k==='all'?' on':''}" data-cat="${k}">${k}</button>`).join(' ');
$('#catFilters').onclick=e=>{const b=e.target.closest('[data-cat]');if(!b)return;catFilter=b.dataset.cat;
  document.querySelectorAll('#catFilters .filterbtn').forEach(x=>x.classList.toggle('on',x.dataset.cat===catFilter));renderCases();};
$('#caseSearch').oninput=e=>{q=e.target.value.toLowerCase();renderCases();};
function renderCases(){
  const rows=DATA.cases.filter(x=>(catFilter==='all'||x.category===catFilter)&&
    (!q||[x.id,x.title,x.endpoint,x.status,x.severity].join(' ').toLowerCase().includes(q)));
  $('#caseCount').textContent=`${rows.length} / ${DATA.cases.length} cases`;
  const tb=$('#caseBody');tb.innerHTML='';
  rows.forEach(x=>{
    const tr=document.createElement('tr');tr.className='caserow';
    tr.innerHTML=`<td><b>${esc(x.id)}</b></td><td>${esc(x.category)}</td><td>${esc(x.priority)}</td>`+
      `<td>${esc(x.title)}</td><td><code>${esc(x.endpoint)}</code></td>`+
      `<td><span class="badge ${stClass(x.status)}">${esc(x.status)}</span></td>`+
      `<td>${x.severity?`<span class="sev ${x.severity}">${x.severity}</span>`:''}</td>`;
    const det=document.createElement('tr');det.className='detail';det.style.display='none';
    det.innerHTML=`<td colspan="7"><div class="kv">
      <div>Traces to</div><div>${esc(x.traces)}</div>
      <div>Preconditions</div><div>${esc(x.preconditions)}</div>
      <div>Test data</div><div>${esc(x.testData)}</div>
      <div>Automation</div><div>${esc(x.automation)}</div></div>
      <b>Steps (what is executed)</b><div class="pre">${esc(x.steps)}</div>
      <b>Expected result</b><div class="pre">${esc(x.expected)}</div>
      ${x.observed?`<b>Observed</b><div class="pre">${esc(x.observed)}</div>`:''}
      ${DATA.evidence.find(e=>e.id===x.id)?`<button class="filterbtn" onclick="gotoEvidence('${x.id}')">See request/response →</button>`:''}</td>`;
    tr.onclick=()=>{det.style.display=det.style.display==='none'?'':'none';};
    tb.appendChild(tr);tb.appendChild(det);
  });
  if(!rows.length)tb.innerHTML='<tr><td colspan="7" class="empty">No matching cases.</td></tr>';
}
window.gotoEvidence=id=>{select('evidence');$('#evSearch').value=id;renderEv(id.toLowerCase());
  const el=document.getElementById('ev-'+id);if(el){el.open=true;el.scrollIntoView({behavior:'smooth',block:'start'});}};

// evidence
function renderEv(filter){
  const box=$('#evidence');box.innerHTML='';
  const list=DATA.evidence.filter(e=>!filter||e.id.toLowerCase().includes(filter));
  $('#evCount').textContent=`${list.length} / ${DATA.evidence.length} tests`;
  list.forEach(e=>{
    const d=document.createElement('details');d.id='ev-'+e.id;
    const n=e.pairs.length;
    d.innerHTML=`<summary>${esc(e.id)} <span class="mut">${n} call${n>1?'s':''}</span></summary>`+
      '<div class="evbody">'+e.pairs.map(p=>{
        const st=p.resp?p.resp.status:'';const cls=(String(st)[0]==='2')?'PASS':(String(st)[0]==='4'||String(st)[0]==='5')?'FAIL':'NOTRUN';
        return `<div class="reqline">▸ ${esc(p.req.method||'')} ${esc(p.req.url||'')}</div>`+
          `<div class="pre">${esc(pj(p.req.body!==undefined?{headers:p.req.headers,body:p.req.body}:p.req))}</div>`+
          (p.resp?`<div class="reqline">◂ <span class="badge ${cls}">HTTP ${esc(st)}</span> ${p.resp.ms!=null?esc(p.resp.ms)+' ms':''}</div>`+
            `<div class="pre">${esc(pj({headers:p.resp.headers,body:p.resp.body}))}</div>`:'<div class="mut">no response captured</div>');
      }).join('')+'</div>';
    box.appendChild(d);
  });
  if(!list.length)box.innerHTML='<div class="empty">No evidence for this filter.</div>';
}
$('#evSearch').oninput=e=>renderEv(e.target.value.toLowerCase());

// stress
(function(){const s=DATA.stress;const box=$('#stress');
  if(!s||!s.summary){box.innerHTML='<div class="empty">No stress run in this report.</div>';return;}
  const su=s.summary;const top=Object.entries(su).filter(([,v])=>typeof v!=='object');
  const groups=Object.entries(su).filter(([,v])=>v&&typeof v==='object');
  let h='<table><thead><tr><th>Run parameter</th><th>Value</th></tr></thead><tbody>'+
    top.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')+'</tbody></table><br>';
  if(groups.length){const mk=['n','p50','p95','p99','max','mean'];
    h+='<table><thead><tr><th>Group</th>'+mk.map(x=>`<th>${x}</th>`).join('')+'<th>status</th></tr></thead><tbody>'+
      groups.map(([g,v])=>`<tr><td><b>${esc(g)}</b></td>`+mk.map(x=>`<td>${esc(v[x])}</td>`).join('')+
      `<td>${esc(JSON.stringify(v.status||{}))}</td></tr>`).join('')+'</tbody></table>';}
  if(s.notes)h+='<div class="pre" style="margin-top:14px">'+esc(s.notes)+'</div>';
  box.innerHTML=h;
})();

// findings
(function(){const f=DATA.findings;const box=$('#findings');
  if(!f.length){box.innerHTML='<div class="empty">No failing cases — nothing in the findings register.</div>';return;}
  box.innerHTML=f.map(x=>`<div class="card ${x.severity}">
    <h3>${esc(x.id)} — ${esc(x.title)}</h3>
    <div style="margin:4px 0"><span class="sev ${x.severity}">${x.severity||'—'}</span> <code>${esc(x.endpoint)}</code></div>
    <div class="mut" style="font-size:12px;margin-top:6px">${esc(x.observed)}</div></div>`).join('');
})();

// coverage
(function(){const cv=DATA.coverage;const box=$('#coverage');
  if(!cv){box.innerHTML='<div class="empty">No coverage.json in this run.</div>';return;}
  const s=cv.summary;const meter=(l,o)=>`<div class="meter"><div class="meterhd">${l} <b>${o.covered}/${o.total}</b> <span class="mut">(${o.pct}%)</span></div>
    <div class="bar"><span style="width:${o.pct}%"></span></div></div>`;
  let h='<div class="meters">'+meter('Endpoints exercised',s.endpoints)+meter('Request fields seen',s.fields)+meter('Error codes reproduced',s.error_codes)+'</div>';
  h+='<p class="mut" style="font-size:12px">Derived from the executed request/response evidence — not self-reported.</p>';
  h+='<table><thead><tr><th>Endpoint</th><th>Exercised</th><th>Reqs</th><th>Fields</th><th>Error codes</th><th>Gaps</th></tr></thead><tbody>';
  cv.endpoints.forEach(r=>{const gaps=[];if(!r.exercised)gaps.push('endpoint untested');
    if(r.fields_missing.length)gaps.push('fields: '+r.fields_missing.join(', '));
    if(r.errors_missing.length)gaps.push('errors: '+r.errors_missing.join(', '));
    h+=`<tr><td><code>${esc(r.endpoint)}</code></td>
      <td>${r.exercised?'<span class="badge PASS">yes</span>':'<span class="badge FAIL">NO</span>'}</td>
      <td>${r.requests}</td><td>${r.fields_seen.length}/${r.fields_documented.length}</td>
      <td>${r.errors_seen.length}/${r.errors_documented.length}</td>
      <td class="mut">${esc(gaps.join('; ')||'—')}</td></tr>`;});
  box.innerHTML=h+'</tbody></table>';
})();

// regression
(function(){const rg=DATA.regression;const box=$('#regression');
  if(!rg){box.innerHTML='<div class="empty">No regression.json in this run.</div>';return;}
  if(!rg.previous_run){box.innerHTML=`<div class="empty">${esc(rg.note||'No previous run — baseline.')}</div>`;return;}
  const c=rg.counts;
  const chip=(l,n,cls)=>`<span class="chip">${l} <b class="${cls||''}">${n}</b></span>`;
  let h=`<p class="mut">Current <code>${esc(rg.run)}</code> vs previous <code>${esc(rg.previous_run)}</code></p>
    <div class="chips">${chip('Regressed',c.regressed,'bad')}${chip('Fixed',c.fixed,'good')}${chip('Still failing',c.still_failing)}${chip('New',c.new)}${chip('Removed',c.removed)}${chip('Unchanged',c.unchanged)}</div>`;
  const sec=(title,rows,cls)=>{if(!rows||!rows.length)return `<h3>${title} <span class="mut">— none</span></h3>`;
    return `<h3 class="${cls||''}">${title} <span class="mut">(${rows.length})</span></h3>
      <table><thead><tr><th>Test #</th><th>Title</th><th>Was → Now</th></tr></thead><tbody>`+
      rows.map(r=>`<tr><td><b>${esc(r.id)}</b></td><td>${esc(r.title)}</td><td>${esc(r.was||'')} → ${esc(r.now||'')}</td></tr>`).join('')+'</tbody></table>';};
  h+=sec('⚠ Regressed (PASS → FAIL)',rg.regressed,'bad');
  h+=sec('✓ Fixed (was failing → PASS)',rg.fixed,'good');
  h+=sec('Still failing',rg.still_failing);
  h+=sec('New cases',rg.new);
  h+=sec('Removed cases',rg.removed);
  box.innerHTML=h;
})();

renderCases();renderEv('');
const h=location.hash.slice(1);if(TABS.some(t=>t[0]===h))select(h);
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="docs/<service>/<run>")
    ap.add_argument("--cases-dir", help="test-cases/<service>/<run> (derived if omitted)")
    ap.add_argument("--meta", help="JSON with service/branch/env/run/verdict overrides")
    ap.add_argument("--out")
    args = ap.parse_args()
    run_dir = os.path.normpath(args.run_dir)
    parts = run_dir.replace("\\", "/").split("/")
    service = parts[-2] if len(parts) >= 2 else "service"
    run = parts[-1]
    cases_dir = args.cases_dir or os.path.join("test-cases", service, run)

    cases = collect_cases(cases_dir)
    evidence = collect_evidence(run_dir)
    stress = stress_data(run_dir)

    counts = {"total": len(cases)}
    for c in cases:
        st = c["status"].upper().replace(" ", "")
        counts[st] = counts.get(st, 0) + 1
    counts["PASS"] = counts.get("PASS", 0)
    counts["FAIL"] = counts.get("FAIL", 0)
    counts["BLOCKED"] = counts.get("BLOCKED", 0)

    findings = sorted([{"id": c["id"], "title": c["title"], "severity": c["severity"],
                        "endpoint": c["endpoint"], "observed": c["observed"]}
                       for c in cases if c["status"].upper() == "FAIL"],
                      key=lambda x: SEV_ORDER.get(x["severity"], 9))

    meta = {"service": service, "run": run, "branch": "", "env": "TEST", "verdict": ""}
    # best-effort pull branch/env/verdict from the report
    rp = os.path.join(run_dir, "QA-REPORT.md")
    if os.path.exists(rp):
        rt = open(rp, encoding="utf-8").read()
        mb = re.search(r"branch[^\n|]*\|\s*`?development`?[^\n]*\((`?\w+`?)\)", rt, re.I)
        mv = re.search(r"Verdict[:*\s]+([A-Z][A-Z ]+?)(?:\.|\*|<|\n)", rt)
        if mv:
            meta["verdict"] = mv.group(1).strip()
        mbr = re.search(r"@\s*`?[\w./-]*?`?\s*\(`?([0-9a-f]{6,40})`?\)", rt)
        meta["branch"] = "development @ " + mbr.group(1) if mbr else "development"
        mns = re.search(r"namespace\s+`?([\w-]+)`?", rt)
        if mns:
            meta["env"] = "TEST / " + mns.group(1)
    if args.meta:
        meta.update(json.loads(args.meta))
    if not meta["verdict"]:
        meta["verdict"] = "SEE REPORT"

    def load_json(name):
        p = os.path.join(run_dir, name)
        if not os.path.exists(p):
            return None
        try:
            return json.load(open(p, encoding="utf-8"))
        except UnicodeDecodeError:
            return json.load(open(p, encoding="utf-8", errors="replace"))

    data = {"meta": meta, "counts": counts, "cases": cases, "evidence": evidence,
            "stress": stress, "findings": findings, "overviewHtml": overview_html(run_dir),
            "coverage": load_json("coverage.json"), "regression": load_json("regression.json")}

    title = f"QA — {service} — {run}"
    # Embed JSON safely inside an inline <script>: escape the characters that
    # could terminate the tag or break parsing (e.g. a '</script>' captured as
    # test data, like an XSS payload). The browser decodes these back, so the
    # data is unchanged.
    data_json = (json.dumps(data, ensure_ascii=False)
                 .replace("<", "\\u003c").replace(">", "\\u003e")
                 .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    # Each replacement targets a literal character (never an existing '\'-escape),
    # inserting a JSON unicode escape that JSON.parse restores exactly. This
    # neutralizes '</script>', '<script' and '<!--' embedded anywhere in the data.
    htmlout = (TEMPLATE
               .replace("__TITLE__", html.escape(title))
               .replace("__DATA__", data_json))
    out = args.out or os.path.join(run_dir, "QA-REPORT-full.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    size = os.path.getsize(out)
    print(f"wrote {out}  ({len(cases)} cases, {len(evidence)} evidence sets, "
          f"{len(findings)} findings, {size//1024} KB)")


if __name__ == "__main__":
    main()
