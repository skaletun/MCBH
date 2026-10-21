"""MCP v2 stdio server; universal Java 1.21+ RCON transport."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any
import json
import os
import re
import secrets

from mcp.server import MCPServer
from .core import Store, BuildError, block, dimension, pos, compile_blueprint, review, job_progress, next_commands
from .rcon import Rcon, RconError
from . import structures as st
from .viewer import export_viewer
from .architect import generate as design_generate, revision as design_revision, STYLES, FUNCTIONS

mcp = MCPServer("MCBH - MinecraftBuildHumanized")


def _store() -> Store:
    return Store(Path(os.getenv("MCBH_DATA_DIR",str(Path.home()/".mcbh"/"jobs"))))


def _rcon() -> Rcon:
    return Rcon(os.getenv("MCBH_RCON_HOST","127.0.0.1"),int(os.getenv("MCBH_RCON_PORT","25575")),os.getenv("MCBH_RCON_PASSWORD",""),float(os.getenv("MCBH_RCON_TIMEOUT","8")))


def _data(file: str) -> str:
    return (files("mcbh")/"data"/file).read_text(encoding="utf-8")


def _safe_response(response: str) -> str:
    return response[:1200]


def _looks_like_error(response: str) -> bool:
    # Minecraft can be localized; do not mistake empty/ambiguous output for confirmed success.
    return bool(re.search(r"unknown or incomplete command|unknown command|incorrect argument|too many blocks|outside of the world|not loaded|failed to execute|syntax error|invalid .*block|could not|cannot place",response,re.I))


@mcp.tool()
def mcbh_connection() -> dict[str,Any]:
    """Check the RCON connection; reports server response, never exposes password."""
    try:
        with _rcon() as session:
            result=session.command("list")
        return {"connected":True,"response":_safe_response(result),"transport":"RCON","loader":"Any Java dedicated server with RCON"}
    except (OSError,ValueError,RconError) as exc:
        return {"connected":False,"error":str(exc),"hint":"Enable RCON in server.properties and set MCBH_RCON_PASSWORD"}


@mcp.tool()
def mcbh_read_skill(section: str = "all") -> str:
    """Read human-professional builder methodology: terrain, massing, roofs, facades, palettes, interior and QA. Read this BEFORE planning."""
    content=_data("SKILL.md")
    if section=="all":
        return content
    marker=f"## {section}"
    if marker not in content:
        return "Unknown section. Use all or exact section title from SKILL.md."
    return marker+content.split(marker,1)[1].split("\n## ",1)[0]


@mcp.resource("mcbh://skill")
def resource_skill() -> str:
    """Complete integrated builder skill instructions."""
    return _data("SKILL.md")


@mcp.resource("mcbh://visuals")
def resource_visuals() -> str:
    """Index of screenshot URLs with attribution and internal original SVG teaching plates."""
    return _data("visual_index.json")


@mcp.tool()
def mcbh_visual_guides(topic: str = "all", max_results: int = 25) -> dict[str, Any]:
    """Visual apprenticeship: Minecraft screenshots, accurate image source links, diagram URLs and lessons. Filter by construction, palettes, exterior, roofs, interior, terrain."""
    db=json.loads(_data("visual_index.json"))
    needle=topic.strip().lower()
    matched=[a for a in db["items"] if needle=="all" or needle in (a["topic"]+" "+a["title"]+" "+a["id"]).lower()]
    return {"total":len(matched),"items":matched[:max(1,min(40,max_results))],
            "illustrated_walkthrough":"https://github.com/skaletun/MCBH/blob/main/docs/VISUAL_ATLAS.md",
            "caution":"External images need browsing/vision in the MCP client. SVGs are original diagrams, not game screenshots. RCON cannot provide game screenshots."}


@mcp.resource("mcbh://palettes")
def resource_palettes() -> str:
    """Architectural block palette and application guidance."""
    return _data("palettes.json")


@mcp.resource("mcbh://references")
def resource_references() -> str:
    """Verified links to building inspiration, articles and Minecraft command references."""
    return _data("references.json")


@mcp.prompt()
def professional_builder_task(user_request: str) -> str:
    """Full professional builder workflow for a user architecture request."""
    return ("You are a professional Minecraft builder, not a pre-made house generator. "
            "First call mcbh_read_skill('all'), mcbh_visual_guides('all'), and read mcbh://architect. For a new original building, translate the user's intent into a structured brief and call mcbh_design_build; for an existing file read mcbh://guided-builder and use import tools. "
            "Survey terrain when connected; ask for dimensions/placement only if truly necessary. "
            "Develop a unique silhouette, material hierarchy, terrain adaptation, varied roofline, "
            "3D facade depths, buildable floor plans, human-scale furnishing and landscape. "
            "Stage actual block-coordinate geometry as a phased blueprint, inspect preview warnings, "
            "and obtain explicit approval before execution. Inspect after each phase. "
            "After designing, export the offline 3D-like viewer and ask for real screenshot feedback. Refine using mcbh_refine_design after critiquing silhouette, all four facades, roofing, interior access, palette hierarchy and terrain. Never claim visual inspection without actual screenshot evidence. "
            f"User request: {user_request}")


@mcp.tool()
def mcbh_palettes(style: str = "all") -> dict[str,Any]:
    """Curated block palettes grouped by architecture and terrain, with weight/contrast design logic."""
    data=json.loads(_data("palettes.json"))
    if style=="all":
        return data
    return {"style":style,"palette":data["palettes"].get(style),"available":sorted(data["palettes"])}


@mcp.tool()
def mcbh_references(topic: str = "all") -> list[dict[str,str]]:
    """Source URLs for real builders, visual references and technical command documentation; no copyrighted image copying."""
    data=json.loads(_data("references.json"))
    return [r for r in data if topic=="all" or topic.lower() in (r["topic"].lower()+" "+r["title"].lower())]


@mcp.tool()
def mcbh_validate_blueprint(blueprint: dict[str,Any]) -> dict[str,Any]:
    """Compile and audit a proposed JSON blueprint WITHOUT touching Minecraft; see skill schema."""
    try:
        job=compile_blueprint(blueprint)
        return {"valid":True,**review(job),"note":"Validation checks command safety, not actual world collisions or visual quality."}
    except (BuildError,TypeError) as exc:
        return {"valid":False,"error":str(exc)}


@mcp.tool()
def mcbh_stage_blueprint(blueprint: dict[str,Any]) -> dict[str,Any]:
    """Persist a complete phased blueprint (does NOT execute). Returns job ID + one-time approval token."""
    try:
        job=_store().stage(blueprint)
        return {"staged":True,"job_id":job["id"],"approval_token":job["approval_token"],"audit":review(job),"instruction":"Show the design, terrain impact and block counts to user. Require explicit approval before mcbh_execute_phase."}
    except (BuildError,TypeError,OSError) as exc:
        return {"staged":False,"error":str(exc)}


@mcp.tool()
def mcbh_preview(job_id: str, phase: str = "all", first_commands: int = 10) -> dict[str,Any]:
    """Show material estimate, phase progress and representative exact world commands without executing."""
    try:
        job=_store().load(job_id)
        n=max(0,min(30,first_commands))
        chosen=[p for p in job["phases"] if phase=="all" or p["name"]==phase]
        if not chosen:
            raise BuildError("Phase not found")
        return {**job_progress(job),"audit":review(job),"sample_commands":{p["name"]:p["commands"][:n] for p in chosen},"limitations":"No world collision detection; screenshot review requires external visual access."}
    except (BuildError,OSError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_jobs() -> list[dict[str,Any]]:
    """List local persisted staged/partial/complete jobs."""
    return _store().list()


@mcp.tool()
def mcbh_execute_phase(job_id: str, phase: str, approval_token: str, batch_size: int = 32) -> dict[str,Any]:
    """Explicitly approved, resumable execution of ONE build phase, max 128 commands per call. Use repeated calls until complete."""
    store=_store()
    try:
        job=store.load(job_id)
        if not secrets.compare_digest(approval_token,job["approval_token"]):
            raise BuildError("Approval token mismatch")
        if job["status"] in ("uncertain","paused"):
            raise BuildError("Job paused. Inspect server and call mcbh_resume_reviewed before retry")
        n=max(1,min(128,batch_size))
        commands=next_commands(job,phase,n)
        if not commands:
            return {**job_progress(job),"batch_executed":0}
        target=next(p for p in job["phases"] if p["name"]==phase)
        response=""
        with _rcon() as session:
            for cmd in commands:
                full=f"execute in {job['dimension']} run {cmd}"
                # Ambiguous network failures are never silently retried.
                try:
                    response=session.command(full)
                except (OSError,RconError) as exc:
                    job["status"]="uncertain"
                    job["last_error"]=f"RCON result uncertain for {full}: {exc}"
                    store.save(job)
                    return {**job_progress(job),"error":job["last_error"],"action":"Inspect world before resuming; command may have run"}
                if _looks_like_error(response):
                    job["status"]="paused"
                    job["last_error"]=f"{full}: {_safe_response(response)}"
                    store.save(job)
                    return {**job_progress(job),"error":job["last_error"],"action":"Review failed command and world state"}
                target["cursor"]+=1
                job["status"]="building"
                store.save(job)
        if target["cursor"]==len(target["commands"]):
            target["complete"]=True
        if all(p["complete"] for p in job["phases"]):
            job["status"]="complete"
        store.save(job)
        return {**job_progress(job),"batch_executed":len(commands),"last_server_response":_safe_response(response),"note":"RCON response does not prove visual/build correctness; inspect in game."}
    except (BuildError,OSError,RconError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_resume_reviewed(job_id: str, approval_token: str, confirm_world_checked: bool) -> dict[str,Any]:
    """Unpause after a human has inspected an uncertain/failed command; may repeat one command."""
    try:
        store=_store()
        job=store.load(job_id)
        if not secrets.compare_digest(approval_token,job["approval_token"]) or not confirm_world_checked:
            raise BuildError("Approval and inspected-world confirmation required")
        if job["status"] not in ("paused","uncertain"):
            raise BuildError("Job is not paused")
        job["status"]="building"
        job.pop("last_error",None)
        store.save(job)
        return job_progress(job)
    except (BuildError,OSError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_survey_terrain(points: list[list[int]], dimension_id: str = "minecraft:overworld", heightmap: str = "motion_blocking_no_leaves") -> dict[str,Any]:
    """Non-block-editing heightmap survey (1..36 x/z samples) using short-lived marker entities. Chunks must be loaded."""
    if heightmap not in {"world_surface","motion_blocking","motion_blocking_no_leaves","ocean_floor"}:
        return {"error":"Unsupported heightmap"}
    try:
        dim=dimension(dimension_id)
        if not isinstance(points,list) or not 1<=len(points)<=36:
            raise BuildError("Supply 1..36 points [x,z]")
        checked=[]
        for p in points:
            if not isinstance(p,list) or len(p)!=2 or any(type(n)!=int for n in p):
                raise BuildError("Each sample must be [x,z] integers")
            pos((p[0],64,p[1]))
            checked.append(p)
        results=[]
        with _rcon() as session:
            for x,z in checked:
                tag="mcbh_"+secrets.token_hex(8)
                summon=f'execute in {dim} positioned {x} 64 {z} positioned over {heightmap} run summon minecraft:marker ~ ~ ~ {{Tags:["{tag}"]}}'
                try:
                    spawned=session.command(summon)
                    query=session.command(f"execute in {dim} run data get entity @e[type=minecraft:marker,tag={tag},limit=1] Pos[1]")
                    match=re.search(r"(-?\d+(?:\.\d+)?)d\b",query)
                    y=float(match.group(1)) if match else None
                    results.append({"x":x,"z":z,"surface_y":y,"valid":y is not None,"response":_safe_response(query) if y is None else ""})
                finally:
                    session.command(f"execute in {dim} run kill @e[type=minecraft:marker,tag={tag}]")
        valid=[r["surface_y"] for r in results if r["valid"]]
        return {"dimension":dim,"heightmap":heightmap,"samples":results,"min_surface_y":min(valid) if valid else None,"max_surface_y":max(valid) if valid else None,"note":"Loaded-chunk heightmap only; does not identify materials, caves or existing buildings."}
    except (BuildError,OSError,RconError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_check_block(x: int,y: int,z: int,candidates: list[str],dimension_id: str="minecraft:overworld") -> dict[str,Any]:
    """Test up to 32 specific block IDs/states at a coordinate (no arbitrary vanilla read-block capability)."""
    try:
        dim=dimension(dimension_id)
        xyz=pos((x,y,z))
        if not isinstance(candidates,list) or not 1<=len(candidates)<=32:
            raise BuildError("Supply 1..32 candidate block states")
        checked=[block(s) for s in candidates]
        with _rcon() as session:
            for candidate in checked:
                nonce="MCBHFOUND"+secrets.token_hex(6)
                output=session.command(f"execute in {dim} if block {xyz[0]} {xyz[1]} {xyz[2]} {candidate} run say {nonce}")
                if nonce in output and not _looks_like_error(output):
                    return {"match":candidate,"known":True,"at":xyz}
        return {"match":None,"known":False,"tested":checked,"note":"Unknown means none of supplied candidates matched; not that the block is air."}
    except (BuildError,OSError,RconError) as exc:
        return {"error":str(exc)}


@mcp.resource("mcbh://guided-builder")
def resource_guided_builder() -> str:
    """Original architecture of the guide engine based on observed public user workflows."""
    return _data("GUIDED_BUILDER.md")


@mcp.tool()
def mcbh_import_structure(filename: str) -> dict[str,Any]:
    """Safely parse a local .schem (Sponge v2/v3) or .litematic from MCBH_IMPORT_DIR; returns exact material bill, geometry and stable ID without touching the Minecraft world."""
    try:
        return st.import_file(filename)
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc),"import_dir":str(st._root_dir('MCBH_IMPORT_DIR','imports'))}


@mcp.tool()
def mcbh_structure_materials(structure_id: str, mode: str="survival") -> dict[str,Any]:
    """Exact material checklist and 64-item stack counts for all non-air blocks; never invents crafting recipes."""
    try:
        if mode not in ('survival','creative'):
            raise BuildError('Mode must be survival or creative')
        obj=st.load_structure(structure_id)
        return {"structure_id":structure_id,"mode":mode,"materials":st.materials(obj,mode=='survival'),"total":len(obj['blocks'])}
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_structure_steps(structure_id: str, offset: int=0, count: int=20, mode: str="survival") -> dict[str,Any]:
    """Actual coordinate-accurate construction steps grouped as connected same-block horizontal runs, with safe paginated navigation."""
    try:
        return st.steps(st.load_structure(structure_id),offset,count,mode)
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_structure_layer(structure_id: str, y: int, x_from: int=0, z_from: int=0, width: int=32, depth: int=32) -> dict[str,Any]:
    """A true top-down 2D slice of the imported structure, with symbol-to-block-state legend and up-to-64x64 crop."""
    try:
        return st.layer(st.load_structure(structure_id),y,x_from,z_from,width,depth)
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_structure_summary(structure_id: str) -> dict[str,Any]:
    """Geometry, block counts, region counts, per-height histogram and format caveats."""
    try:
        return st.summary(st.load_structure(structure_id))
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_stage_structure(structure_id: str, at: list[int], dimension_id: str="minecraft:overworld", clear_air: bool=False) -> dict[str,Any]:
    """Convert an imported structure into real validated RCON building phases and stage it for human approval. No world changes until approved execution. clear_air is destructive and defaults off."""
    try:
        bp=st.blueprint(st.load_structure(structure_id),at,dimension_id,clear_air)
        staged=_store().stage(bp)
        return {"staged":True,"job_id":staged['id'],"approval_token":staged['approval_token'],"audit":review(staged),
                "warning":"Preview and obtain explicit human approval before calling mcbh_execute_phase. clear_air may destroy existing landscape/builds."}
    except (BuildError,OSError,ValueError) as exc:
        return {"staged":False,"error":str(exc)}


@mcp.tool()
def mcbh_guided_progress(structure_id: str, completed_steps: int|None=None, mode: str="survival") -> dict[str,Any]:
    """Read/update persisted manual step progress; survives restarts on the same MCBH host. Zero resets, and values never exceed the actual step count."""
    try:
        return st.guide_progress(structure_id,completed_steps,mode)
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_repalette_structure(structure_id: str, replacements: dict[str,str]) -> dict[str,Any]:
    """Create a NEW local variant using validated block-state-to-block-state substitutions (paint-bucket equivalent); original stays intact."""
    try:
        return st.repalette(structure_id,replacements)
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_structure_measure(a: list[int], b: list[int]) -> dict[str,Any]:
    """Precisely measure axis offsets, Manhattan distance, Euclidean span and inclusive voxel extents between two local model points."""
    try:
        start,end=pos(a),pos(b)
        import math
        delta=[abs(end[i]-start[i]) for i in range(3)]
        return {"delta_xyz":delta,"inclusive_extent":[v+1 for v in delta],
                "manhattan":sum(delta),"euclidean":round(math.dist(start,end),4)}
    except (BuildError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_export_viewer(structure_id: str, filename: str="mcbh-guide.html") -> dict[str,Any]:
    """Export a single-file offline interactive guide with 3D-like isometric orbit, layers, steps, checklist, grid, progress and measurements."""
    try:
        return export_viewer(st.load_structure(structure_id), filename)
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}


@mcp.tool()
def mcbh_export_mcfunction(structure_id: str, at: list[int], dimension_id: str="minecraft:overworld", clear_air: bool=False, filename: str="mcbh-import.mcfunction") -> dict[str,Any]:
    """Write an exact Java Edition function file inside MCBH_EXPORT_DIR. This does not change the world; users install it into their datapack."""
    try:
        return st.export_mcfunction(st.load_structure(structure_id),at,dimension_id,clear_air,filename)
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}




def _publish_architecture(result: dict[str, Any]) -> dict[str, Any]:
    """Persist geometry for reuse with guide tools; stage construction for human approval."""
    import hashlib
    import gzip
    content=result["structure"]
    canonical=json.dumps(content,sort_keys=True,ensure_ascii=False,separators=(",",":"))
    sid=hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    content["id"]=sid
    root=st._root_dir("MCBH_DATA_DIR","jobs")/"structures"
    root.mkdir(parents=True,exist_ok=True)
    destination=root/f"{sid}.json.gz"
    if not destination.exists():
        st._atomic_gzip(destination,json.dumps(content,ensure_ascii=False).encode("utf-8"))
    design=result["design"]
    outcome={"structure_id":sid,"style":design["style"],"building_type":design["building_type"],
             "seed":design["seed"],"size":content["size"],
             "absolute_origin":design["anchor"],"quality":result["quality"],
             "materials":st.materials(content,True)[:20],
             "human_review_required":True,
             "warning":"Only geometry has been evaluated. Actual screenshots, collisions and environmental fit require in-game review."}
    if not result["quality"]["passed"]:
        outcome["stage_error"]="Mechanical quality gates failed; design was saved but not staged."
        return outcome
    job=_store().stage(result["blueprint"])
    outcome.update({"staged":True,"job_id":job["id"],"approval_token":job["approval_token"],
                    "audit":review(job),"next_steps":"Inspect structure via mcbh_export_viewer and mcbh_structure_layer, obtain human approval, then execute phases in order."})
    return outcome


@mcp.resource("mcbh://architect")
def resource_architect() -> str:
    """Original professional-builder decision protocol and design acceptance criteria."""
    return _data("ARCHITECTURE.md")


@mcp.tool()
def mcbh_architect_capabilities() -> dict[str, Any]:
    """Supported architectural styles, building types, input schema, limitations and reference-driven workflow."""
    return {"styles":sorted(STYLES),"building_types":sorted(FUNCTIONS),
            "brief_schema":{"title":"string, optional","style":"one of styles",
                            "building_type":"one of building_types",
                            "width":"int 13..39","depth":"int 13..39","floors":"int 1..3",
                            "seed":"int 0..2147483647","anchor":"[world_x, floor_y, world_z]",
                            "terrain":"[[local_x, local_z, world_surface_y], ...] max 36 samples",
                            "wing":"true|false|auto"},
            "read_first":["mcbh://architect","mcbh://skill","mcbh://visuals"],
            "limitations":["No built-in neural image generator or free-form language model; the MCP host agent must interpret the user's prompt",
                           "Generates architectural houses and related small buildings; not arbitrary castles, sculptures or cities",
                           "No world screenshot/collision feedback over RCON; real inspection is a separate step",
                           "Building is staged, not executed, until explicitly approved"]}


@mcp.tool()
def mcbh_design_build(brief: dict[str, Any]) -> dict[str, Any]:
    """Create original, seed-variable architecture (terrain, silhouette, roof, real facade depth, interior, landscaping) from a structured AI design brief. Produce a reusable guide and staged RCON job; never executes without separate human approval."""
    try:
        return _publish_architecture(design_generate(brief))
    except (BuildError,OSError,ValueError) as exc:
        return {"staged":False,"error":str(exc)}


@mcp.tool()
def mcbh_refine_design(structure_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Rebuild an original design as a NEW preserved version after user/vision critique. Accepts changed dimensions, seed, style, program, terrain, floors and attached wing; never changes the original."""
    try:
        old=st.load_structure(structure_id)
        if not isinstance(old.get("design_brief"),dict):
            raise BuildError("This structure is not an original MCBH architecture; use mcbh_design_build")
        return _publish_architecture(design_revision(old["design_brief"],changes))
    except (BuildError,OSError,ValueError) as exc:
        return {"staged":False,"error":str(exc)}


@mcp.tool()
def mcbh_architecture_review(structure_id: str) -> dict[str, Any]:
    """Check a generated design's measured block geometry, deterministic design brief and mechanical quality gates; does NOT claim a visual screenshot review."""
    try:
        src=st.load_structure(structure_id)
        if src.get("format")!="mcbh-original-architecture":
            raise BuildError("Only MCBH-designed architecture can be reviewed with this tool")
        counts={}
        for *xyz,state in src["blocks"]:
            stage = "unknown"
            if "stairs" in state or "slab" in state: stage="shaped_block"
            counts[stage]=counts.get(stage,0)+1
        return {"structure_id":structure_id,"quality":src.get("design_quality"),
                "block_count":len(src["blocks"]),"size":src["size"],
                "shaped_blocks":counts.get("shaped_block",0),
                "brief":src["design_brief"],
                "visual_inspection":"NOT PERFORMED. Screenshot review is mandatory for a professional-quality claim.",
                "required_views":["front","back","left","right","roof","each inhabited floor","terrain connections"]}
    except (BuildError,OSError,ValueError) as exc:
        return {"error":str(exc)}


def main() -> None:
    mcp.run(transport="stdio")


if __name__=="__main__":
    main()
