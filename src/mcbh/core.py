"""Pure construction planning, validation, safe command compilation, persistent job state."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
import json
import os
import re
import secrets
import tempfile

ID = re.compile(r"^[a-z0-9_.-]+:[a-z0-9_./-]+$")
BLOCK = re.compile(r"^([a-z0-9_.-]+:[a-z0-9_./-]+)(?:\[([a-z0-9_]+=[a-z0-9_]+(?:,[a-z0-9_]+=[a-z0-9_]+)*)\])?$")
MAX_COORD = 29_999_984
MAX_COMMAND_VOLUME = 16_384  # conservative cross-version command limit
MAX_JOB_COMMANDS = 60_000
MAX_PHASES = 30


class BuildError(ValueError):
    """Unsafe/invalid build input."""


def block(value: str) -> str:
    if not isinstance(value, str) or not BLOCK.fullmatch(value):
        raise BuildError(f"Invalid Java block-state: {value!r}")
    if len(value) > 200:
        raise BuildError("Block state too long")
    return value


def dimension(value: str) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise BuildError(f"Invalid dimension: {value!r}")
    return value


def pos(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise BuildError("Coordinates must be [x,y,z]")
    if any(type(v) is not int for v in value):
        raise BuildError("Coordinates must be integers")
    x, y, z = value
    if abs(x) > MAX_COORD or abs(z) > MAX_COORD or not -2048 <= y <= 4095:
        raise BuildError("Coordinates exceed safe limits")
    return x, y, z


def bounds(a: tuple[int, int, int], b: tuple[int, int, int]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    return tuple(min(x, y) for x, y in zip(a, b)), tuple(max(x, y) for x, y in zip(a, b))


def count_box(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    lo, hi = bounds(a, b)
    return (hi[0]-lo[0]+1)*(hi[1]-lo[1]+1)*(hi[2]-lo[2]+1)


def tiles(a: tuple[int, int, int], b: tuple[int, int, int], limit: int = MAX_COMMAND_VOLUME) -> Iterator[tuple[tuple[int,int,int], tuple[int,int,int]]]:
    """Split rectangular prisms into commands bounded by block count."""
    lo, hi = bounds(a, b)
    # Prefer X rows, then Z bands, then Y slices.
    dx = min(hi[0]-lo[0]+1, limit)
    dz = min(hi[2]-lo[2]+1, max(1, limit // dx))
    dy = max(1, limit // (dx*dz))
    for y in range(lo[1], hi[1]+1, dy):
        for z in range(lo[2], hi[2]+1, dz):
            for x in range(lo[0], hi[0]+1, dx):
                yield (x, y, z), (min(x+dx-1,hi[0]), min(y+dy-1,hi[1]), min(z+dz-1,hi[2]))


def points_on_line(a: tuple[int,int,int], b: tuple[int,int,int]) -> Iterator[tuple[int,int,int]]:
    delta = tuple(v-u for u,v in zip(a,b))
    n = max(abs(v) for v in delta)
    if n == 0:
        yield a
        return
    for i in range(n+1):
        yield tuple(round(u + d*i/n) for u,d in zip(a,delta))


def points_in_ellipsoid(a: tuple[int,int,int], b: tuple[int,int,int], shell: bool = False) -> Iterator[tuple[int,int,int]]:
    lo, hi = bounds(a,b)
    radii = [(hi[i]-lo[i]+1)/2 for i in range(3)]
    centers = [(hi[i]+lo[i])/2 for i in range(3)]
    def inside(x:int,y:int,z:int) -> bool:
        return sum(((t-c)/r)**2 for t,c,r in zip((x,y,z),centers,radii)) <= 1.0
    for y in range(lo[1],hi[1]+1):
        for z in range(lo[2],hi[2]+1):
            for x in range(lo[0],hi[0]+1):
                if inside(x,y,z) and (not shell or any(not inside(x+dx,y+dy,z+dz) for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)))):
                    yield (x,y,z)


def compress_points(points: list[tuple[int,int,int]], material: str) -> list[tuple[str,int]]:
    """Deduplicate and compress contiguous X runs without changing orientation/state."""
    rows: dict[tuple[int,int],set[int]] = {}
    for x,y,z in points:
        rows.setdefault((y,z),set()).add(x)
    out = []
    for (y,z), xs in sorted(rows.items()):
        start = prev = None
        for x in sorted(xs):
            if prev is not None and x != prev+1:
                out.extend((cmd_range(a,b,material),count_box(a,b)) for a,b in tiles((start,y,z),(prev,y,z)))
                start = None
            if start is None:
                start = x
            prev = x
        if start is not None:
            out.extend((cmd_range(a,b,material),count_box(a,b)) for a,b in tiles((start,y,z),(prev,y,z)))
    return out


def cmd_range(a:tuple[int,int,int], b:tuple[int,int,int], material:str, mode:str="replace", filter_block:str|None=None) -> str:
    aa = f"{a[0]} {a[1]} {a[2]}"
    if a == b:
        if filter_block:
            return f"execute if block {aa} {filter_block} run setblock {aa} {material}"
        return f"setblock {aa} {material}" + (" keep" if mode == "keep" else "")
    bb = f"{b[0]} {b[1]} {b[2]}"
    if filter_block:
        return f"fill {aa} {bb} {material} replace {filter_block}"
    return f"fill {aa} {bb} {material}" + (f" {mode}" if mode != "replace" else "")


def compile_op(op:dict[str,Any]) -> list[tuple[str,int,str]]:
    """Return validated (Java command, estimated affected voxels, material)."""
    if not isinstance(op,dict):
        raise BuildError("Each operation must be an object")
    typ = op.get("type")
    material = block(op.get("block"))
    mode = op.get("mode","replace")
    if mode not in ("replace","keep","outline","hollow"):
        raise BuildError("Unsupported fill mode")
    filter_material = block(op["replace_only"]) if "replace_only" in op else None
    if filter_material and mode != "replace":
        raise BuildError("replace_only requires mode=replace")
    if typ == "set":
        if mode not in ("replace","keep") or filter_material:
            raise BuildError("set supports replace/keep only")
        p = pos(op.get("at"))
        return [(cmd_range(p,p,material,mode),1,material)]
    if typ == "box":
        a,b = pos(op.get("from")),pos(op.get("to"))
        if count_box(a,b)>2_000_000:
            raise BuildError("Box too large (max 2M blocks per operation)")
        if mode in ("hollow","outline") and count_box(a,b)>MAX_COMMAND_VOLUME:
            raise BuildError("Large hollow/outline box cannot be split safely; express faces as box operations")
        return [(cmd_range(p,q,material,mode,filter_material),count_box(p,q),material) for p,q in tiles(a,b)]
    if typ in ("line","polyline","ellipsoid","voxels"):
        if mode != "replace" or filter_material:
            raise BuildError("Shape operation supports default replace only")
        if typ == "line":
            a,b=pos(op.get("from")),pos(op.get("to"))
            if max(abs(u-v) for u,v in zip(a,b))>39_999:
                raise BuildError("Line too long")
            points = list(points_on_line(a,b))
        elif typ == "polyline":
            knots = op.get("points")
            if not isinstance(knots,list) or not 2 <= len(knots) <= 256:
                raise BuildError("polyline requires 2..256 points")
            knots = [pos(p) for p in knots]
            if sum(max(abs(u-v) for u,v in zip(a,b))+1 for a,b in zip(knots,knots[1:]))>40_000:
                raise BuildError("Polyline too long")
            points = [p for a,b in zip(knots,knots[1:]) for p in points_on_line(a,b)]
        elif typ == "ellipsoid":
            a,b=pos(op.get("from")),pos(op.get("to"))
            if count_box(a,b)>200_000:
                raise BuildError("Ellipsoid bounding box too large")
            points=list(points_in_ellipsoid(a,b,bool(op.get("shell",False))))
        else:
            raw=op.get("points")
            if not isinstance(raw,list) or not 1<=len(raw)<=20_000:
                raise BuildError("voxels requires 1..20,000 coordinates")
            points=[pos(p) for p in raw]
        if len(points)>40_000:
            raise BuildError("Shape exceeds 40,000 points")
        return [(cmd,n,material) for cmd,n in compress_points(points,material)]
    raise BuildError(f"Unsupported type: {typ}. Use set, box, line, polyline, ellipsoid, voxels")


def compile_blueprint(bp:dict[str,Any]) -> dict[str,Any]:
    if not isinstance(bp,dict):
        raise BuildError("Blueprint must be a JSON object")
    title = bp.get("title")
    if not isinstance(title,str) or not 3<=len(title)<=120:
        raise BuildError("title must be 3..120 characters")
    dim = dimension(bp.get("dimension","minecraft:overworld"))
    phases = bp.get("phases")
    if not isinstance(phases,list) or not 1<=len(phases)<=MAX_PHASES:
        raise BuildError(f"phases must be 1..{MAX_PHASES} elements")
    compiled=[]
    total=0
    materials=Counter()
    used_names=set()
    for phase in phases:
        name = phase.get("name") if isinstance(phase,dict) else None
        if not isinstance(name,str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}",name) or name in used_names:
            raise BuildError("Phase names must be unique lowercase identifiers (2..40 chars)")
        used_names.add(name)
        ops = phase.get("operations")
        if not isinstance(ops,list) or not 1<=len(ops)<=10_000:
            raise BuildError("Each phase must have 1..10,000 operations")
        commands=[]
        for op in ops:
            for cmd,n,material in compile_op(op):
                commands.append(cmd)
                materials[material] += n
                total += n
            if len(commands)>MAX_JOB_COMMANDS:
                raise BuildError("Too many commands; break the blueprint into smaller projects")
        compiled.append({"name":name,"commands":commands,"cursor":0,"complete":False})
    if sum(len(p["commands"]) for p in compiled)>MAX_JOB_COMMANDS:
        raise BuildError("Too many commands")
    return {"title":title,"dimension":dim,"phases":compiled,"materials":dict(materials),"estimated_voxels":total,"job_commands":sum(len(p["commands"]) for p in compiled),"intent":bp.get("intent",{}),"version":1}


def review(bp: dict[str,Any]) -> dict[str,Any]:
    names={p["name"] for p in bp["phases"]}
    stages={"site","foundation","structure","roof","facade","interior","landscape","lighting"}
    missing=sorted(stages-names)
    warnings=[]
    if missing:
        warnings.append("Missing recommended stages: "+", ".join(missing))
    if len(bp["materials"])<5:
        warnings.append("Few materials: consider a primary/secondary/trim/accent/landscape palette")
    if not any("stairs" in s or "slab" in s for s in bp["materials"]):
        warnings.append("No stairs/slabs: roof silhouette and detail depth may be underdeveloped")
    if "minecraft:air" in bp["materials"]:
        warnings.append("Contains destructive air edits; check existing structures and backups")
    if bp["estimated_voxels"]>200_000:
        warnings.append("Large job: build and inspect phase-by-phase")
    return {"advisory_warnings":warnings,"quality_is_heuristic":True,"phases":list(names),"materials":bp["materials"],"estimated_voxels":bp["estimated_voxels"],"command_count":bp["job_commands"]}


@dataclass
class Store:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True,exist_ok=True)
        if os.name != "nt":
            self.root.chmod(0o700)

    def _path(self, job_id:str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{24}",job_id):
            raise BuildError("Invalid job id")
        return self.root / f"{job_id}.json"

    def save(self,job:dict[str,Any]) -> None:
        dest=self._path(job["id"])
        with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=self.root,delete=False) as tmp:
            json.dump(job,tmp,ensure_ascii=False,indent=2)
            temp=Path(tmp.name)
        os.replace(temp,dest)

    def stage(self,bp:dict[str,Any]) -> dict[str,Any]:
        job=compile_blueprint(bp)
        job["id"]=secrets.token_hex(12)
        # Explicit approval is necessary to execute any changes.
        job["approval_token"]=secrets.token_hex(12)
        job["status"]="staged"
        self.save(job)
        return job

    def load(self,job_id:str)->dict[str,Any]:
        path=self._path(job_id)
        if not path.is_file():
            raise BuildError("Unknown job id")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self)->list[dict[str,Any]]:
        result=[]
        for path in sorted(self.root.glob("*.json")):
            try:
                job=json.loads(path.read_text(encoding="utf-8"))
                result.append({"id":job["id"],"title":job["title"],"status":job["status"],"phases":len(job["phases"])})
            except (ValueError,KeyError):
                continue
        return result


def next_commands(job:dict[str,Any],phase_name:str,limit:int) -> list[str]:
    for i,phase in enumerate(job["phases"]):
        if phase["name"]!=phase_name:
            continue
        if any(not prev["complete"] for prev in job["phases"][:i]):
            raise BuildError("Complete earlier phases before this phase")
        if phase["complete"]:
            return []
        return phase["commands"][phase["cursor"]:phase["cursor"]+limit]
    raise BuildError("Unknown phase")


def job_progress(job:dict[str,Any])->dict[str,Any]:
    phases=[{"name":p["name"],"completed_commands":p["cursor"],"total_commands":len(p["commands"]),"complete":p["complete"]} for p in job["phases"]]
    return {"id":job["id"],"title":job["title"],"dimension":job["dimension"],"status":job["status"],"phases":phases,"estimated_voxels":job["estimated_voxels"]}
