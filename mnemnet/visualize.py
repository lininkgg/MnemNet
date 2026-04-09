"""
visualize.py — MnemNet graph visualization.

Reads the full Knowledge Graph from mempalace and generates
an interactive HTML file with a D3.js force-directed graph.

Usage:
    mnemnet-graph                        # generates graph.html and opens it
    mnemnet-graph --output ~/my_graph.html
    mnemnet-graph --no-open              # generate only, don't open browser
    python -m mnemnet.visualize
"""

import argparse
import json
import webbrowser
from datetime import date, datetime
from pathlib import Path

from mempalace.knowledge_graph import KnowledgeGraph

from . import config as cfg
from .memory import _decay_weight


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>MnemNet — {agent_name}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0d0d0d; font-family: 'Georgia', serif; overflow: hidden; }}

  #info {{
    position: fixed; top: 20px; left: 20px; z-index: 10;
    color: #888; font-size: 12px; line-height: 1.8;
  }}
  #info h1 {{ color: #c8a882; font-size: 15px; margin-bottom: 6px; font-weight: normal; letter-spacing: 2px; }}
  #stats {{ color: #555; font-size: 11px; margin-top: 4px; }}

  #controls {{
    position: fixed; top: 20px; right: 20px; z-index: 10;
    display: flex; gap: 8px; flex-direction: column; align-items: flex-end;
  }}
  .btn {{
    background: transparent; border: 1px solid #333; color: #666;
    padding: 4px 10px; font-size: 11px; cursor: pointer; border-radius: 2px;
    font-family: 'Georgia', serif;
  }}
  .btn:hover {{ border-color: #666; color: #aaa; }}
  .btn.active {{ border-color: #c8a882; color: #c8a882; }}

  #tooltip {{
    position: fixed; display: none;
    background: rgba(15,15,15,0.95); border: 1px solid #2a2a2a;
    padding: 12px 16px; border-radius: 4px;
    color: #ccc; font-size: 12px; max-width: 320px;
    line-height: 1.6; pointer-events: none; z-index: 100;
  }}
  #tooltip .entity {{ color: #c8a882; font-size: 13px; margin-bottom: 6px; font-weight: normal; }}
  #tooltip .edge {{ margin: 2px 0; }}
  #tooltip .pred {{ color: #7a9e7e; font-size: 11px; }}
  #tooltip .obj {{ color: #888; font-size: 11px; }}
  #tooltip .weight {{ color: #555; font-size: 10px; }}

  #legend {{
    position: fixed; bottom: 20px; left: 20px; z-index: 10;
    color: #555; font-size: 11px; line-height: 2;
  }}
  #legend div {{ display: flex; align-items: center; gap: 8px; }}
  .dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; flex-shrink: 0; }}

  svg {{ width: 100vw; height: 100vh; }}
  .link {{ stroke-opacity: 0.35; transition: stroke-opacity 0.15s; }}
  .link:hover {{ stroke-opacity: 0.9; }}
  .node circle {{ stroke-width: 1.5; cursor: pointer; }}
  .node circle:hover {{ stroke-width: 3; }}
  .node text {{
    fill: #888; font-size: 10px;
    pointer-events: none; text-anchor: middle;
  }}
</style>
</head>
<body>

<div id="info">
  <h1>{agent_name}</h1>
  <div id="stats">{node_count} nodes &middot; {edge_count} edges &middot; {generated}</div>
</div>

<div id="controls">
  <button class="btn" id="btn-tensions" onclick="toggleFilter('tensions')">tensions only</button>
  <button class="btn" id="btn-predictions" onclick="toggleFilter('predictions')">expectations</button>
  <button class="btn" onclick="resetZoom()">reset</button>
</div>

<div id="tooltip"></div>

<div id="legend">
  <div><span class="dot" style="background:#c8a882"></span> high degree</div>
  <div><span class="dot" style="background:#7a9e7e"></span> tension / expectation</div>
  <div><span class="dot" style="background:#7e8fa8"></span> surprise</div>
  <div><span class="dot" style="background:#5a5a5a"></span> other</div>
  <div style="margin-top:6px;color:#444">drag &middot; scroll to zoom &middot; hover</div>
</div>

<svg id="graph"></svg>

<script>
const triples = {triples_json};

function edgeColor(pred) {{
  if (pred.includes("_tension_")) return "#9e7a7a";
  if (pred.includes("_expectation") || pred.includes("_surprise")) return "#7a9e7e";
  if (pred.includes("pulls_question")) return "#a87e9e";
  return "#3a3a3a";
}}

function edgeWidth(pred) {{
  if (pred.includes("_tension_") || pred.includes("_expectation")) return 1.8;
  return 1;
}}

function nodeColor(id, degree) {{
  if (id.includes("_tension_") || id.includes("tension")) return "#9e7a7a";
  if (id.includes("_expectation") || id.includes("expectation") || id.includes("surprise")) return "#7a9e7e";
  if (id.includes("pulls_question") || id.includes("_surprise")) return "#7e8fa8";
  if (degree > 6) return "#c8a882";
  return "#5a5a5a";
}}

// Build graph
const nodesMap = new Map();
const links = [];

triples.forEach(t => {{
  const sKey = t.s;
  const oKey = t.o.length > 35 ? t.o.substring(0, 35) + "…" : t.o;

  if (!nodesMap.has(sKey)) nodesMap.set(sKey, {{id: sKey, full: sKey, degree: 0, weight: t.w || 0.5, predicates: []}});
  if (!nodesMap.has(oKey)) nodesMap.set(oKey, {{id: oKey, full: t.o, degree: 0, weight: t.w || 0.5, predicates: []}});

  nodesMap.get(sKey).degree++;
  nodesMap.get(oKey).degree++;
  nodesMap.get(sKey).predicates.push(t.p);

  links.push({{source: sKey, target: oKey, predicate: t.p, full_o: t.o, weight: t.w || 0.5}});
}});

let nodes = Array.from(nodesMap.values());
let activeFilter = null;

const svg = d3.select("#graph");
const w = window.innerWidth, h = window.innerHeight;
const g = svg.append("g");

const zoom = d3.zoom().scaleExtent([0.1, 5]).on("zoom", e => g.attr("transform", e.transform));
svg.call(zoom);

function resetZoom() {{
  svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity.translate(w/2, h/2).scale(0.9));
}}

// Defs
const defs = svg.append("defs");
const filter = defs.append("filter").attr("id", "glow");
filter.append("feGaussianBlur").attr("stdDeviation", "2.5").attr("result", "coloredBlur");
const feMerge = filter.append("feMerge");
feMerge.append("feMergeNode").attr("in", "coloredBlur");
feMerge.append("feMergeNode").attr("in", "SourceGraphic");

let sim, link, node;

function nodeRadius(d) {{ return Math.max(3, Math.min(18, 3 + d.degree * 1.4)); }}

function build(nodeList, linkList) {{
  g.selectAll("*").remove();

  sim = d3.forceSimulation(nodeList)
    .force("link", d3.forceLink(linkList).id(d => d.id).distance(90))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("center", d3.forceCenter(w/2, h/2))
    .force("collision", d3.forceCollide().radius(d => nodeRadius(d) + 10));

  link = g.append("g").selectAll("line")
    .data(linkList).join("line")
    .attr("class", "link")
    .attr("stroke", d => edgeColor(d.predicate))
    .attr("stroke-width", d => edgeWidth(d.predicate))
    .attr("stroke-opacity", d => 0.15 + d.weight * 0.5);

  node = g.append("g").selectAll("g")
    .data(nodeList).join("g")
    .attr("class", "node")
    .call(d3.drag()
      .on("start", (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
      .on("drag", (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
      .on("end", (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }})
    );

  node.append("circle")
    .attr("r", d => nodeRadius(d))
    .attr("fill", d => nodeColor(d.id, d.degree))
    .attr("fill-opacity", d => 0.5 + d.weight * 0.4)
    .attr("stroke", d => nodeColor(d.id, d.degree))
    .attr("stroke-opacity", 0.5)
    .attr("filter", d => d.degree > 5 ? "url(#glow)" : null);

  node.append("text")
    .text(d => d.id.length > 20 ? d.id.substring(0, 20) + "…" : d.id)
    .attr("dy", d => nodeRadius(d) + 11)
    .style("font-size", d => d.degree > 5 ? "11px" : "9px")
    .style("fill", d => d.degree > 5 ? "#888" : "#555");

  const tooltip = document.getElementById("tooltip");

  node.on("mouseover", function(e, d) {{
    const related = linkList.filter(l => l.source.id === d.id || l.target.id === d.id);
    let html = `<div class="entity">${{d.full}}</div>`;
    related.slice(0, 8).forEach(l => {{
      const isSource = l.source.id === d.id;
      if (isSource) {{
        html += `<div class="edge"><span class="pred">→ ${{l.predicate}}</span><br><span class="obj">${{l.full_o.substring(0,70)}}${{l.full_o.length>70?"…":""}}</span></div>`;
      }} else {{
        html += `<div class="edge"><span class="pred">← ${{l.predicate}}</span><br><span class="obj">${{l.source.id}}</span></div>`;
      }}
    }});
    if (d.weight) html += `<div class="weight" style="margin-top:6px">weight: ${{d.weight.toFixed(2)}}</div>`;
    tooltip.innerHTML = html;
    tooltip.style.display = "block";
    d3.select(this).select("circle").attr("stroke-opacity", 1).attr("stroke-width", 3);
  }})
  .on("mousemove", function(e) {{
    tooltip.style.left = (e.pageX + 14) + "px";
    tooltip.style.top = Math.min(e.pageY - 10, window.innerHeight - 200) + "px";
  }})
  .on("mouseout", function() {{
    tooltip.style.display = "none";
    d3.select(this).select("circle").attr("stroke-opacity", 0.5).attr("stroke-width", 1.5);
  }});

  sim.on("tick", () => {{
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("transform", d => `translate(${{d.x}},${{d.y)}}`);
  }});
}}

function toggleFilter(type) {{
  const btn = document.getElementById("btn-" + type);
  if (activeFilter === type) {{
    activeFilter = null;
    btn.classList.remove("active");
    build(nodes, links);
    return;
  }}
  activeFilter = type;
  document.querySelectorAll(".btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");

  let filtered;
  if (type === "tensions") {{
    filtered = links.filter(l => l.predicate.includes("_tension_"));
  }} else if (type === "predictions") {{
    filtered = links.filter(l => l.predicate.includes("_expectation") || l.predicate.includes("_surprise") || l.predicate.includes("pulls_question"));
  }}
  const ids = new Set(filtered.flatMap(l => [l.source.id || l.source, l.target.id || l.target]));
  build(nodes.filter(n => ids.has(n.id)), filtered);
}}

build(nodes, links);
</script>
</body>
</html>
"""


def _collect_triples() -> list[dict]:
    """Pull all triples from the KG, attach decay weights."""
    kg = KnowledgeGraph()
    predicates = kg.stats().get("relationship_types", [])

    seen = set()
    triples = []

    for predicate in predicates:
        rows = kg.query_relationship(predicate) or []
        for row in rows:
            key = (row.get("subject"), row.get("predicate"), row.get("object"))
            if key in seen:
                continue
            seen.add(key)
            weight = _decay_weight(row.get("valid_from"))
            triples.append({
                "s": row.get("subject", ""),
                "p": row.get("predicate", ""),
                "o": row.get("object", ""),
                "w": round(weight, 3),
            })

    return triples


def generate(output_path: Path | None = None, open_browser: bool = True) -> Path:
    """
    Generate the graph HTML and optionally open it in a browser.
    Returns the path to the generated file.
    """
    if output_path is None:
        output_path = Path.home() / "mnemnet_graph.html"

    triples = _collect_triples()
    if not triples:
        print("KG is empty — nothing to visualize.")
        return output_path

    agent_name = cfg.collector.agent_name
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    node_ids = set()
    for t in triples:
        node_ids.add(t["s"])
        node_ids.add(t["o"][:35] if len(t["o"]) > 35 else t["o"])

    html = _HTML_TEMPLATE.format(
        agent_name=agent_name,
        node_count=len(node_ids),
        edge_count=len(triples),
        generated=today,
        triples_json=json.dumps(triples, ensure_ascii=False),
    )

    output_path.write_text(html, encoding="utf-8")
    print(f"Graph saved: {output_path}")
    print(f"  {len(node_ids)} nodes, {len(triples)} edges")

    if open_browser:
        webbrowser.open(output_path.as_uri())

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate MnemNet knowledge graph visualization")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output HTML path (default: ~/mnemnet_graph.html)")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't open the browser after generating")
    args = parser.parse_args()
    generate(output_path=args.output, open_browser=not args.no_open)


if __name__ == "__main__":
    main()
