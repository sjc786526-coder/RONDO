"""Deterministic, self-contained Team Lens HTML report."""

import json
from pathlib import Path
from typing import Any

from .model import load_team_view, validate_team_view


def render_report(view: dict[str, Any]) -> bytes:
    """Render only a normalized Team View; raw bundles are never accepted here."""

    validate_team_view(view)
    embedded = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    embedded = (
        embedded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return (_HTML_PREFIX + embedded + _HTML_SUFFIX).encode("utf-8")


def write_report(team_view_path: Path, output_path: Path) -> dict[str, Any]:
    """Read one Team View JSON file and write its standalone report."""

    view = load_team_view(team_view_path)
    Path(output_path).write_bytes(render_report(view))
    return view


_HTML_PREFIX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RONDO Team Lens</title>
<style>
:root{color-scheme:dark;--bg:#0b1220;--panel:#111c2f;--panel2:#17243a;--ink:#e7eef9;--muted:#91a4bf;--line:#2a3b55;--cyan:#67e8f9;--green:#86efac;--amber:#fcd34d;--red:#fca5a5;--violet:#c4b5fd}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#18304a 0,var(--bg) 38rem);color:var(--ink);font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
main{max-width:1500px;margin:auto;padding:28px}.hero{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin-bottom:22px}.eyebrow{color:var(--cyan);letter-spacing:.15em;text-transform:uppercase}.hero h1{font:700 38px/1.05 system-ui,sans-serif;margin:.25rem 0}.muted{color:var(--muted)}
.cards,.capabilities{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.card,.panel,.cap{background:linear-gradient(145deg,rgba(23,36,58,.96),rgba(12,23,39,.96));border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 30px rgba(0,0,0,.18)}.card{padding:14px}.metric{font:700 25px/1 system-ui,sans-serif;margin-top:6px}.panel{padding:18px;margin-top:16px}.panel h2{font:650 20px/1.2 system-ui,sans-serif;margin:0 0 14px}.panel h3{font:650 15px/1.2 system-ui,sans-serif;margin:16px 0 8px}.cap{padding:10px}.badge{display:inline-block;border-radius:999px;padding:2px 8px;font-size:12px;border:1px solid currentColor}.available{color:var(--green)}.partial{color:var(--amber)}.unsupported{color:var(--red)}.not_applicable{color:var(--violet)}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}select{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:6px 9px}.lane{display:grid;grid-template-columns:minmax(190px,280px) 1fr;gap:12px;border-top:1px solid var(--line);padding:11px 0}.lane:first-child{border-top:0}.lane-title{overflow-wrap:anywhere}.track{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.activity{padding:4px 7px;border-radius:6px;background:#1e314c;border-left:3px solid var(--cyan)}.activity.tool{border-color:var(--amber)}.activity.wait{border-color:var(--violet)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;min-width:660px}th,td{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px 9px}th{color:var(--muted);font-weight:600}.id{overflow-wrap:anywhere;color:var(--cyan)}.chain{display:flex;gap:8px;align-items:stretch;overflow:auto;padding:4px}.node{min-width:185px;border:1px solid var(--line);border-radius:9px;background:var(--panel2);padding:9px}.node:after{content:""}.facts{display:grid;gap:8px}.fact{border-left:3px solid var(--violet);padding:7px 10px;background:var(--panel2);overflow-wrap:anywhere}.empty{padding:16px;border:1px dashed var(--line);border-radius:9px;color:var(--muted)}footer{color:var(--muted);margin:20px 0 5px;text-align:center}
@media(max-width:700px){main{padding:18px}.hero{display:block}.lane{grid-template-columns:1fr}.hero h1{font-size:30px}}
</style>
</head>
<body>
<main>
<header class="hero"><div><div class="eyebrow">offline native trace view</div><h1>RONDO Team Lens</h1><div id="identity" class="muted"></div></div><div id="trace-status"></div></header>
<section id="summary" class="cards" aria-label="summary"></section>
<section class="panel"><h2>Capability matrix</h2><div id="capabilities" class="capabilities"></div></section>
<section class="panel"><h2>Agent swimlane and timeline</h2><div class="toolbar"><label for="agent-filter">Agent</label><select id="agent-filter"></select><span class="muted">writer sequence breaks same-millisecond ties</span></div><div id="lanes"></div></section>
<section class="grid2"><section class="panel"><h2>Models and tools</h2><div id="models-tools"></div></section><section class="panel"><h2>Communication and waits</h2><div id="interactions"></div></section></section>
<section class="panel"><h2>Team Attention Map</h2><div id="attention"></div></section>
<section class="panel"><h2>Event / Version relations</h2><div id="events"></div></section>
<section class="panel"><h2>Fact flow</h2><div id="facts"></div></section>
<footer>Generated from team_view.json only · no external resources</footer>
</main>
<script id="team-data" type="application/json">"""

_HTML_SUFFIX = """</script>
<script>
"use strict";
const data=JSON.parse(document.getElementById("team-data").textContent);
const byId=id=>document.getElementById(id);
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined&&text!==null)node.textContent=String(text);if(cls)node.className=cls;return node};
const append=(parent,...children)=>{for(const child of children)parent.appendChild(child);return parent};
const value=v=>v===null||v===undefined?"—":String(v);
const short=v=>{const s=value(v);return s.length>28?s.slice(0,12)+"…"+s.slice(-10):s};
const statusBadge=status=>el("span",status,"badge "+status);
function card(label,metric){const n=el("div",null,"card");append(n,el("div",label,"muted"),el("div",metric,"metric"));return n}
function table(headers,rows){if(!rows.length)return el("div","No mechanically available rows.","empty");const wrap=el("div",null,"scroll"),t=el("table"),thead=el("thead"),tr=el("tr");headers.forEach(h=>tr.appendChild(el("th",h)));thead.appendChild(tr);t.appendChild(thead);const body=el("tbody");for(const row of rows){const r=el("tr");row.forEach(cell=>{const td=el("td");if(cell instanceof Node)td.appendChild(cell);else td.textContent=value(cell);r.appendChild(td)});body.appendChild(r)}t.appendChild(body);wrap.appendChild(t);return wrap}
function renderHeader(){byId("identity").textContent=`${data.source.product} · rollout ${data.source.rollout_id} · trace ${data.source.trace_id}`;byId("trace-status").appendChild(statusBadge(data.summary.ended_at_unix_ms===null?"partial":"available"));const s=data.summary;const rows=[["Agents",s.agent_count],["Inferences",s.inference_count],["Tools",s.tool_count],["Interactions",s.interaction_count],["Total tokens",s.usage.total_tokens],["Duration ms",s.duration_ms]];rows.forEach(([a,b])=>byId("summary").appendChild(card(a,value(b))))}
function renderCapabilities(){const root=byId("capabilities");Object.keys(data.availability).sort().forEach(name=>{const row=data.availability[name],box=el("div",null,"cap");append(box,el("div",name),statusBadge(row.status));if(row.reason_codes.length)box.appendChild(el("div",row.reason_codes.join(", "),"muted"));root.appendChild(box)})}
function activities(agent){const rows=[];data.inferences.filter(x=>x.agent_id===agent).forEach(x=>rows.push({seq:x.started_seq,label:`inference ${short(x.inference_id)} · ${x.model}`,kind:"inference"}));data.tools.filter(x=>x.agent_id===agent).forEach(x=>rows.push({seq:x.started_seq,label:`${x.kind} · ${x.name}`,kind:x.kind==="wait_agent"?"wait":"tool"}));return rows.sort((a,b)=>a.seq-b.seq||a.label.localeCompare(b.label))}
function renderLanes(){const select=byId("agent-filter");append(select,el("option","All agents"));data.agents.forEach(a=>{const o=el("option",a.agent_path);o.value=a.agent_id;select.appendChild(o)});const draw=()=>{const root=byId("lanes");root.replaceChildren();const wanted=select.value;data.agents.filter(a=>!wanted||a.agent_id===wanted).forEach(a=>{const lane=el("div",null,"lane"),title=el("div",null,"lane-title"),track=el("div",null,"track");append(title,el("div",a.agent_path,"id"),el("div",`${a.role} · ${a.status} · ${short(a.agent_id)}`,"muted"));const rows=activities(a.agent_id);if(!rows.length)track.appendChild(el("span","No activity","muted"));rows.forEach(x=>track.appendChild(el("span",`#${x.seq} ${x.label}`,"activity "+x.kind)));append(lane,title,track);root.appendChild(lane)})};select.addEventListener("change",draw);draw()}
function renderModelsTools(){const models=new Map();data.inferences.forEach(x=>models.set(`${x.provider} / ${x.model}`,(models.get(`${x.provider} / ${x.model}`)||0)+1));const tools=new Map();data.tools.forEach(x=>tools.set(x.name,(tools.get(x.name)||0)+1));const root=byId("models-tools");root.appendChild(table(["Model / provider","Calls"],[...models].sort().map(x=>x)));root.appendChild(el("h3","Tool activity"));root.appendChild(table(["Tool","Calls"],[...tools].sort().map(x=>x)))}
function renderInteractions(){const rows=data.interactions.map(x=>[x.kind,short(x.source_agent_id),short(x.target_agent_id),x.started_seq,x.status]);const root=byId("interactions");root.appendChild(table(["Kind","From","To","Seq","Status"],rows));const waits=data.tools.filter(x=>x.kind==="wait_agent");root.appendChild(el("h3","Wait activity"));root.appendChild(table(["Agent","Tool","Seq","Status"],waits.map(x=>[short(x.agent_id),x.name,x.started_seq,x.status])))}
function teamUnavailable(id,capability){const row=data.availability[capability],root=byId(id);append(root,statusBadge(row.status),el("span"," "+row.reason_codes.join(", "),"muted"))}
function renderAttention(){if(data.team===null){teamUnavailable("attention","team_events_versions");return}const rows=data.team.attention.map(x=>[short(x.agent_id),short(x.event_id),value(x.visible),value(x.active),x.reasons.join(", "),x.revision]);byId("attention").appendChild(table(["Agent","Event","Visible","Active","Reasons","Revision"],rows));if(!rows.length)teamUnavailable("attention","team_events_versions")}
function renderEvents(){const root=byId("events");if(data.team===null){teamUnavailable("events","team_events_versions");return}if(!data.team.events.length){root.appendChild(el("div","No observed Team Events.","empty"));return}const versions=new Map(data.team.versions.map(v=>[v.version_id,v]));data.team.events.forEach(event=>{const block=el("div");append(block,el("h3",event.event_id,"id"));const chain=el("div",null,"chain");event.version_ids.forEach(id=>{const v=versions.get(id),node=el("div",null,"node");if(v){append(node,el("div",v.version_id,"id"),el("div",`author ${short(v.author_agent_id)}`,"muted"),el("div",`producer ${value(v.producer_state)} · root ${value(v.root_state)}`),el("div",`facts ${v.fact_ref_count} · seq ${v.first_seq}–${v.last_seq}`,"muted"))}else node.textContent=id;chain.appendChild(node)});if(!event.version_ids.length)chain.appendChild(el("div","No observed versions","empty"));append(block,chain);root.appendChild(block)})}
function renderFacts(){const root=byId("facts");if(data.team===null){teamUnavailable("facts","team_facts");return}const box=el("div",null,"facts");data.team.facts.forEach(f=>{const row=el("div",null,"fact");append(row,el("div",f.fact_id,"id"),el("div",`${value(f.category)} · ${value(f.tool)} · ${value(f.availability)}`),el("div",`producer ${short(f.producer_agent_id)} → versions ${f.version_ids.map(short).join(", ")||"—"}`,"muted"));box.appendChild(row)});root.appendChild(data.team.facts.length?box:el("div","No observed Facts.","empty"));if(data.availability.team_facts.status!=="available")append(root,el("div"),statusBadge(data.availability.team_facts.status),el("span"," "+data.availability.team_facts.reason_codes.join(", "),"muted"))}
renderHeader();renderCapabilities();renderLanes();renderModelsTools();renderInteractions();renderAttention();renderEvents();renderFacts();
</script>
</body>
</html>
"""
