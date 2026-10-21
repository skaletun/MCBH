"""Original, bounded architectural design compiler for MCBH.

This is a geometric design assistant, not an LLM or a claim of human-level artistry.
The MCP agent interprets a brief, studies references and reviews the result visually.
The compiler turns controlled design intent into phased, inspectable Minecraft blocks.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import random
from typing import Any

from .core import BuildError, block, compile_blueprint, pos

# Block IDs use the Java 1.21 registry. A modded server may require substitution.
STYLES = {
    "medieval_timber": {
        "wall": "minecraft:calcite", "beam": "minecraft:stripped_spruce_log[axis=y]",
        "floor": "minecraft:spruce_planks", "roof": "minecraft:dark_oak",
        "stone": "minecraft:stone_bricks", "aged": "minecraft:mossy_stone_bricks",
        "window": "minecraft:glass_pane", "accent": "minecraft:dark_oak_planks",
        "door": "minecraft:spruce_door", "fence": "minecraft:spruce_fence",
        "leaf": "minecraft:oak_leaves[persistent=true]", "flat": False,
    },
    "alpine_rustic": {
        "wall": "minecraft:spruce_planks", "beam": "minecraft:spruce_log[axis=y]",
        "floor": "minecraft:spruce_planks", "roof": "minecraft:dark_oak",
        "stone": "minecraft:cobblestone", "aged": "minecraft:mossy_cobblestone",
        "window": "minecraft:glass_pane", "accent": "minecraft:stripped_spruce_wood",
        "door": "minecraft:spruce_door", "fence": "minecraft:spruce_fence",
        "leaf": "minecraft:spruce_leaves[persistent=true]", "flat": False,
    },
    "japanese_traditional": {
        "wall": "minecraft:white_concrete", "beam": "minecraft:dark_oak_log[axis=y]",
        "floor": "minecraft:dark_oak_planks", "roof": "minecraft:deepslate_tile",
        "stone": "minecraft:stone_bricks", "aged": "minecraft:tuff_bricks",
        "window": "minecraft:white_stained_glass_pane", "accent": "minecraft:dark_oak_planks",
        "door": "minecraft:dark_oak_door", "fence": "minecraft:dark_oak_fence",
        "leaf": "minecraft:cherry_leaves[persistent=true]", "flat": False,
    },
    "modern_concrete": {
        "wall": "minecraft:white_concrete", "beam": "minecraft:gray_concrete",
        "floor": "minecraft:smooth_quartz", "roof": "minecraft:smooth_stone",
        "stone": "minecraft:polished_andesite", "aged": "minecraft:stone_bricks",
        "window": "minecraft:glass", "accent": "minecraft:dark_oak_planks",
        "door": "minecraft:dark_oak_door", "fence": "minecraft:iron_bars",
        "leaf": "minecraft:oak_leaves[persistent=true]", "flat": True,
    },
    "desert_adobe": {
        "wall": "minecraft:smooth_sandstone", "beam": "minecraft:stripped_acacia_log[axis=y]",
        "floor": "minecraft:cut_sandstone", "roof": "minecraft:smooth_sandstone",
        "stone": "minecraft:sandstone", "aged": "minecraft:terracotta",
        "window": "minecraft:yellow_stained_glass_pane", "accent": "minecraft:orange_terracotta",
        "door": "minecraft:acacia_door", "fence": "minecraft:acacia_fence",
        "leaf": "minecraft:azalea_leaves[persistent=true]", "flat": True,
    },
    "dark_fantasy": {
        "wall": "minecraft:tuff_bricks", "beam": "minecraft:dark_oak_log[axis=y]",
        "floor": "minecraft:dark_oak_planks", "roof": "minecraft:deepslate_tile",
        "stone": "minecraft:deepslate_bricks", "aged": "minecraft:cracked_deepslate_bricks",
        "window": "minecraft:purple_stained_glass_pane", "accent": "minecraft:polished_blackstone_bricks",
        "door": "minecraft:dark_oak_door", "fence": "minecraft:dark_oak_fence",
        "leaf": "minecraft:oak_leaves[persistent=true]", "flat": False,
    },
}
FUNCTIONS = {"house", "tavern", "workshop", "library", "watchtower"}
PHASES = ("site", "foundation", "structure", "roof", "facade", "interior", "landscape", "lighting")


def _int(value: Any, lo: int, hi: int, name: str) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise BuildError(f"{name} must be an integer {lo}..{hi}")
    return value


def normalize(brief: dict[str, Any]) -> dict[str, Any]:
    """Strictly validate designer inputs instead of trusting agent-generated commands."""
    if not isinstance(brief, dict):
        raise BuildError("The design brief must be an object")
    style = brief.get("style", "medieval_timber")
    if style not in STYLES:
        raise BuildError(f"Unknown style {style!r}. Choose from {sorted(STYLES)}")
    building_type = brief.get("building_type", "house")
    if building_type not in FUNCTIONS:
        raise BuildError(f"Unknown building_type; use {sorted(FUNCTIONS)}")
    width = _int(brief.get("width", 19), 13, 39, "width")
    depth = _int(brief.get("depth", 17), 13, 39, "depth")
    floors = _int(brief.get("floors", 2), 1, 3, "floors")
    seed = _int(brief.get("seed", 17), 0, 2**31 - 1, "seed")
    anchor = pos(brief.get("anchor", [0, 80, 0]))
    if not -60 <= anchor[1] <= 285:
        raise BuildError("Design anchor Y must be -60..285; consider actual dimension height")
    title = brief.get("title", f"{style.replace('_', ' ').title()} {building_type}")
    if not isinstance(title, str) or not 3 <= len(title) <= 120:
        raise BuildError("Title must contain 3..120 characters")
    if "terrain" in brief:
        raw = brief["terrain"]
        if not isinstance(raw, list) or len(raw) > 36:
            raise BuildError("Terrain must contain at most 36 survey samples")
        terrain = []
        for item in raw:
            if not isinstance(item, list) or len(item) != 3:
                raise BuildError("Terrain samples are [local_x, local_z, absolute_surface_y]")
            tx, tz, sy = item
            terrain.append([_int(tx, -40, 80, "terrain x"),
                            _int(tz, -40, 80, "terrain z"),
                            _int(sy, -64, 330, "surface Y")])
    else:
        terrain = []
    roof_pitch = brief.get("roof_pitch", "balanced")
    if roof_pitch not in ("low", "balanced", "steep"):
        raise BuildError("roof_pitch must be low, balanced or steep")
    roof_overhang = _int(brief.get("roof_overhang", 2), 1, 3, "roof_overhang")
    custom = brief.get("material_overrides", {})
    if not isinstance(custom, dict):
        raise BuildError("material_overrides must be an object")
    allowed_roles = set(STYLES[style])-{"flat"}
    if not set(custom).issubset(allowed_roles):
        raise BuildError(f"Only these palette roles may be overridden: {sorted(allowed_roles)}")
    custom = {key: block(value) for key, value in custom.items()}
    if "roof" in custom and not STYLES[style]["flat"]:
        if custom["roof"] not in {
            "minecraft:dark_oak", "minecraft:spruce", "minecraft:oak",
            "minecraft:deepslate_tile", "minecraft:stone_brick", "minecraft:acacia",
            "minecraft:brick", "minecraft:polished_blackstone_brick",
        }:
            raise BuildError("Pitched roof override must be a real Java stair/slab block family")
    if "door" in custom and not custom["door"].endswith("_door"):
        raise BuildError("Door override must name a valid door family")
    if "leaf" in custom and "leaves" not in custom["leaf"]:
        raise BuildError("Leaf material must be a leaves block")
    wing = brief.get("wing", "auto")
    if wing not in (True, False, "auto"):
        raise BuildError("wing must be true, false or auto")
    return {"title": title, "style": style, "building_type": building_type,
            "width": width, "depth": depth, "floors": floors, "seed": seed,
            "anchor": list(anchor), "terrain": terrain, "wing": wing,
            "roof_pitch": roof_pitch, "roof_overhang": roof_overhang,
            "material_overrides": custom}


def _height(samples: list[list[int]], x: int, z: int, baseline: int) -> int:
    """Inverse-distance site estimate: unknown terrain must not be portrayed as surveyed."""
    if not samples:
        return baseline
    weights = []
    for sx, sz, y in samples:
        dist2 = (x-sx)**2 + (z-sz)**2
        if dist2 == 0:
            return y
        weights.append((1.0/dist2, y))
    return round(sum(w*y for w, y in weights)/sum(w for w, _ in weights))


class Mason:
    """Single-owner voxel ledger. Later details replace earlier geometry, not duplicate it."""
    def __init__(self, anchor: list[int]):
        self.anchor = anchor
        self.blocks: dict[tuple[int, int, int], tuple[str, str]] = {}

    def add(self, x: int, y: int, z: int, state: str, stage: str) -> None:
        if stage not in PHASES:
            raise BuildError("Invalid architectural phase")
        if not -32 <= x <= 90 or not -32 <= z <= 90 or not -72 <= y <= 108:
            raise BuildError("Generated voxel exceeds design safety envelope")
        xyz = pos([self.anchor[0]+x, self.anchor[1]+y, self.anchor[2]+z])
        self.blocks[(x, y, z)] = (block(state), stage)

    def remove(self, x: int, y: int, z: int) -> None:
        self.blocks.pop((x, y, z), None)

    def prism(self, xa: int, ya: int, za: int, xb: int, yb: int, zb: int,
              state: str, stage: str) -> None:
        for y in range(min(ya, yb), max(ya, yb)+1):
            for z in range(min(za, zb), max(za, zb)+1):
                for x in range(min(xa, xb), max(xa, xb)+1):
                    self.add(x, y, z, state, stage)

    def phase_ops(self) -> list[dict[str, Any]]:
        """Make deterministic x-axis runs per layer; phase order keeps dependencies readable."""
        grouped: dict[str, dict[tuple[int, int, str], list[int]]] = {
            phase: defaultdict(list) for phase in PHASES
        }
        for (x, y, z), (state, phase) in self.blocks.items():
            grouped[phase][(y, z, state)].append(x)
        result = []
        for phase in PHASES:
            ops = []
            for (y, z, state), xs in sorted(grouped[phase].items()):
                sorted_x = sorted(xs)
                begin = previous = sorted_x[0]
                for x in sorted_x[1:]:
                    if x != previous+1:
                        ops.append(self._op(begin, previous, y, z, state))
                        begin = x
                    previous = x
                ops.append(self._op(begin, previous, y, z, state))
            if ops:
                result.append({"name": phase, "operations": ops})
        return result

    def _op(self, start: int, end: int, y: int, z: int, state: str) -> dict[str, Any]:
        ox, oy, oz = self.anchor
        if start == end:
            return {"type": "set", "at": [ox+start, oy+y, oz+z], "block": state}
        return {"type": "box", "from": [ox+start, oy+y, oz+z],
                "to": [ox+end, oy+y, oz+z], "block": state}

    def structure(self, label: str) -> dict[str, Any]:
        if not self.blocks:
            raise BuildError("Empty architectural design")
        keys = self.blocks.keys()
        minimum = [min(p[i] for p in keys) for i in range(3)]
        maximum = [max(p[i] for p in keys) for i in range(3)]
        voxels = [[x-minimum[0], y-minimum[1], z-minimum[2], state]
                  for (x, y, z), (state, _) in self.blocks.items()]
        voxels.sort(key=lambda v: (v[1], v[2], v[0]))
        return {"name": label, "format": "mcbh-original-architecture",
                "size": [maximum[i]-minimum[i]+1 for i in range(3)],
                "blocks": voxels, "regions": 1, "warnings": [
                    "Design is original algorithmic geometry, not a verified Minecraft screenshot",
                    "Block orientation and modpack resource appearance need in-world review",
                    "Build phases assume clear interior; collision with real terrain/structures is not detected"],
                "local_min": minimum}


def _rect_outline(xa: int, za: int, xb: int, zb: int):
    for x in range(xa, xb+1):
        yield x, za
        yield x, zb
    for z in range(za+1, zb):
        yield xa, z
        yield xb, z


def _roof(m: Mason, x0: int, z0: int, x1: int, z1: int, base: int,
          p: dict[str, str | bool], style: str, rng: random.Random,
          ridge_direction: str = "z", pitch: str = "balanced",
          requested_overhang: int = 2) -> dict[str, int | str]:
    if bool(p["flat"]):
        m.prism(x0-1, base, z0-1, x1+1, base, z1+1, str(p["roof"]), "roof")
        for x, z in _rect_outline(x0-1, z0-1, x1+1, z1+1):
            m.add(x, base+1, z, str(p["accent"]), "roof")
        return {"roof_type": "flat parapet", "eaves": 1, "ridge_y": base}
    # Roof rise depends on actual span; giant 45-degree prisms overwhelm wide buildings.
    overhang = requested_overhang
    ratio = {"low": 0.5, "balanced": 0.75, "steep": 1.0}[pitch]
    if style == "japanese_traditional":
        ratio *= 0.8
    a, b = (x0, x1) if ridge_direction == "z" else (z0, z1)
    mid = (a+b)//2
    radius = (b-a)//2 + overhang
    rise = 0
    for along in range(a-overhang, b+overhang+1):
        dist = abs(along-mid)
        # An asymmetric ridge is resolved naturally on even spans.
        h = max(0, radius-dist)
        height = math.ceil(h * ratio)
        rise = max(rise, height)
        side = "west" if along < mid else "east"
        if ridge_direction != "z":
            side = "north" if along < mid else "south"
        state = f"{p['roof']}_stairs[facing={side},half=bottom]"
        for transverse in range((z0 if ridge_direction == "z" else x0)-overhang,
                                (z1 if ridge_direction == "z" else x1)+overhang+1):
            xx, zz = (along, transverse) if ridge_direction == "z" else (transverse, along)
            if along == mid:
                m.add(xx, base+height, zz, f"{p['roof']}_slab[type=bottom]", "roof")
            else:
                m.add(xx, base+height, zz, state, "roof")
    # Gable triangles behind the eaves, built with actual solid blocks.
    for along in range(a, b+1):
        dist = abs(along-mid)
        h = math.ceil((radius-dist) * ratio)
        for transverse in (z0, z1) if ridge_direction == "z" else (x0, x1):
            for offset in range(max(0, h)):
                xx, zz = (along, transverse) if ridge_direction == "z" else (transverse, along)
                m.add(xx, base+offset, zz, str(p["wall"]), "structure")
    return {"roof_type": "stepped gable", "eaves": overhang, "ridge_y": base+rise}


def _story(m: Mason, x0: int, z0: int, x1: int, z1: int, base: int,
           palette: dict[str, Any], door_at: int | None, level: int, flat: bool,
           opening_side: bool) -> None:
    # Planks are thin horizontal slabs in the silhouette; open living volume starts at y+1.
    m.prism(x0+1, base, z0+1, x1-1, base, z1-1, palette["floor"], "structure")
    for yy in range(base+1, base+5):
        # Inset wall, one block behind exposed posts and edge beams.
        for x in range(x0+1, x1):
            for zz in (z0+1, z1-1):
                is_front_door = door_at is not None and zz == z0+1 and x == door_at and yy <= base+2
                bay = x in (x0+3, x1-3, x0+6, x1-6)
                glass = bay and yy in (base+2, base+3) and not is_front_door
                if not is_front_door:
                    m.add(x, yy, zz, palette["window"] if glass else palette["wall"], "structure")
        for z in range(z0+2, z1-1):
            for xx in (x0+1, x1-1):
                is_arch = opening_side and xx == x1-1 and z in (z0+(z1-z0)//2, z0+(z1-z0)//2+1) and yy < base+4
                bay = z in (z0+4, z1-4)
                if not is_arch:
                    m.add(xx, yy, z, palette["window"] if bay and yy in (base+2, base+3) else palette["wall"], "structure")
    # Outer structural rhythm is geometrically separate from inset plaster.
    def post(x: int, z: int):
        for yy in range(base, base+6):
            if door_at == x and z == z0 and yy in (base+1, base+2):
                continue
            m.add(x, yy, z, palette["beam"], "facade")
    for x in sorted(set((x0, x1, x0+4, x1-4, (x0+x1)//2))):
        post(x, z0)
        post(x, z1)
    for z in sorted(set((z0, z1, z0+4, z1-4, (z0+z1)//2))):
        post(x0, z)
        post(x1, z)
    for x, z in _rect_outline(x0, z0, x1, z1):
        m.add(x, base+5, z, palette["accent"], "facade")
    # Independent stone contact and overhanging window ledges.
    if level == 0:
        for x, z in _rect_outline(x0, z0, x1, z1):
            m.add(x, base, z, palette["stone"], "foundation")
    for x in (x0+3, x1-3):
        for z in (z0-1, z1+1):
            m.add(x, base+1, z, palette["accent"], "facade")
    if door_at is not None:
        # Explicit double-height opening, remove any posts/trim inside it.
        for zz in (z0, z0+1):
            for yy in (base+1, base+2):
                m.remove(door_at, yy, zz)
        # Doors use lower+upper state; facing south means front is z<z0.
        m.add(door_at, base+1, z0+1, f"{palette['door']}[facing=north,half=lower,hinge=left,open=false]", "interior")
        m.add(door_at, base+2, z0+1, f"{palette['door']}[facing=north,half=upper,hinge=left,open=false]", "interior")


def _furnish(m: Mason, w: int, d: int, base: int, level: int,
             p: dict[str, Any], function: str, seed: int) -> None:
    # Furniture follows room purpose, not uniform scattering.
    zsplit = d//2 + (seed%3-1)
    if zsplit < 6 or zsplit > d-6:
        zsplit = d//2
    for x in range(3, w-3):
        if x in (w//2, w//2+1):
            continue
        for yy in range(base+1, base+5):
            m.add(x, yy, zsplit, p["wall"], "interior")
    for z in (zsplit-1, zsplit+1):
        m.add(3, base+1, z, "minecraft:bookshelf", "interior")
        m.add(w-4, base+1, z, "minecraft:barrel", "interior")
    # Focus table uses daylight from a nearby window.
    for x in (w//2-1, w//2):
        for z in (zsplit-4, zsplit-3):
            m.add(x, base+1, z, "minecraft:oak_slab[type=top]", "interior")
    m.add(w//2-2, base+1, zsplit-4, "minecraft:spruce_stairs[facing=east,half=bottom]", "interior")
    m.add(w//2+1, base+1, zsplit-4, "minecraft:spruce_stairs[facing=west,half=bottom]", "interior")
    if function in ("tavern", "house"):
        m.add(4, base+1, d-4, "minecraft:chest[facing=south,type=single]", "interior")
        m.add(5, base+1, d-4, "minecraft:red_bed[facing=east,part=foot]", "interior")
        m.add(6, base+1, d-4, "minecraft:red_bed[facing=east,part=head]", "interior")
    elif function == "workshop":
        m.add(4, base+1, d-4, "minecraft:crafting_table", "interior")
        m.add(5, base+1, d-4, "minecraft:furnace[facing=north,lit=false]", "interior")
        m.add(6, base+1, d-4, "minecraft:barrel[facing=up,open=false]", "interior")
    elif function == "library":
        for x in (4, 5, 6, 7):
            m.add(x, base+1, d-4, "minecraft:bookshelf", "interior")
            m.add(x, base+2, d-4, "minecraft:bookshelf", "interior")
        m.add(w-5, base+1, d-4, "minecraft:lectern[facing=south,has_book=false]", "interior")
    else:
        m.add(4, base+1, d-4, "minecraft:barrel", "interior")
        m.add(5, base+1, d-4, "minecraft:cartography_table", "interior")
    # Tabletop/shelf lanterns have real support below; never suspend lanterns in empty space.
    m.add(w//2-1, base+2, zsplit-4, "minecraft:lantern[hanging=false]", "lighting")
    m.add(3, base+2, zsplit-1, "minecraft:lantern[hanging=false]", "lighting")


def _landscape(m: Mason, w: int, d: int, ybase: int, p: dict[str, Any],
               seed: int, sampled: list[list[int]]) -> None:
    front = w//2
    # Traffic and path connect all the way to the door; variation avoids checkerboard.
    for z in range(-7, 0):
        h = _height(sampled, front, z, ybase-1)
        if h > ybase+1:
            continue
        for x in (front-1, front, front+1):
            if (x+z+seed)%7 == 0:
                state = "minecraft:gravel"
            else:
                state = "minecraft:coarse_dirt"
            m.add(x, h, z, state, "landscape")
    m.add(front, ybase, -1, f"{p['roof']}_slab[type=bottom]" if not p["flat"] else p["stone"], "landscape")
    # Two asymmetric trees/garden masses, located away from door and roof.
    for idx, (tx, tz) in enumerate(((-6, d//2), (w+7, d//2+3))):
        if (seed+idx)%3 == 0:
            continue
        gy = _height(sampled, tx, tz, ybase-1)
        height = 4 + ((seed+idx)%3)
        for v in range(1, height):
            m.add(tx, gy+v, tz, "minecraft:oak_log[axis=y]", "landscape")
        for dy in (-1, 0, 1):
            rad = 2 if dy < 1 else 1
            for dx in range(-rad, rad+1):
                for dz in range(-rad, rad+1):
                    if abs(dx)+abs(dz) <= rad+1 and (dx, dz, dy) != (0, 0, -1):
                        m.add(tx+dx, gy+height+dy, tz+dz, p["leaf"], "landscape")


def quality_report(m: Mason, w: int, d: int, floors: int, ybase: int,
                   roof: dict[str, Any], terrain: list[list[int]], door: int) -> dict[str, Any]:
    """Mechanical gates, not a fake aesthetic quality score."""
    voxels = m.blocks
    doorway = all((door, yy, 0) not in voxels for yy in (ybase+1, ybase+2))
    has_roof = sum(1 for _, (b, stage) in voxels.items() if stage == "roof") > w*d//2
    elevations = len(set(y for (_, y, _), (_, stage) in voxels.items() if stage == "roof"))
    furnishings = sum(1 for _, (b, stage) in voxels.items() if stage == "interior" and
                      any(k in b for k in ("bookshelf", "chest", "furnace", "bed", "barrel", "lectern", "stairs")))
    checks = {
        "doorway_two_blocks_clear": doorway,
        "solid_enough_roof": has_roof,
        "roof_volume_or_intentional_flat": bool(roof.get("roof_type")=="flat parapet" or elevations >= 3),
        "real_furniture": furnishings >= 4,
        "independent_palette_roles": len(set(state.split("[", 1)[0] for state, _ in voxels.values())) >= 8,
        "has_exterior_framing": any(stage == "facade" for _, stage in voxels.values()),
        "has_landscaping": any(stage == "landscape" for _, stage in voxels.values()),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "counts": {"voxels": len(voxels), "unique_materials": len(set(v[0] for v in voxels.values())),
                       "furniture_blocks": furnishings, "roof_y_levels": elevations},
            "limitations": [
                "These are structural heuristic checks, not proof of good-looking architecture",
                "RCON cannot provide photographs or identify all collisions; visually inspect the result",
                "Generated structure assumes a clear interior and needs build-site approval",
                "Terrain samples are interpolated rather than queried unless provided by mcbh_survey_terrain",
            ] + ([] if terrain else ["No actual terrain samples provided; landscape uses assumed flat ground"])}


def generate(brief: dict[str, Any]) -> dict[str, Any]:
    """Original architecture with deterministic but non-identical facade, roof and floorplan."""
    params = normalize(brief)
    p = {**STYLES[params["style"]], **params["material_overrides"]}
    w, d, floors = params["width"], params["depth"], params["floors"]
    seed, base = params["seed"], 0
    rng = random.Random(seed)
    height = 6
    m = Mason(params["anchor"])
    terrain = params["terrain"]
    base_surface = params["anchor"][1] - 1
    # Adapt retaining footings at support points, leave existing hills untouched.
    highest = max((_height(terrain, x, z, base_surface) for x, z in
                   ((0, 0), (w-1, 0), (0, d-1), (w-1, d-1), (w//2, d//2))), default=base_surface)
    if highest > base_surface:
        raise BuildError("Survey indicates terrain above the entrance/floor; raise anchor Y or choose another site. Never silently bulldoze.")
    wing = params["wing"] is True or (params["wing"] == "auto" and w >= 17 and
                                      params["building_type"] in ("tavern", "workshop", "library"))
    # Real supporting columns from floor base to sampled ground elevation.
    supports = {(x, z) for x, z in _rect_outline(0, 0, w-1, d-1)
                if x in (0, w-1) or z in (0, d-1)}
    for x, z in supports:
        gy = _height(terrain, x, z, base_surface)
        if base_surface - gy > 16:
            raise BuildError("Unsupported ravine/deep foundation (>16 blocks); revise design for terrain")
        for yy in range(gy+1-base_surface, 0):
            m.add(x, yy, z, p["stone"] if yy > -3 else p["aged"], "foundation")
    # Connected floor plates and well-framed walls; ground floor is locally y=0.
    door = w//2 + (1 if seed%2 and w%2 == 0 else 0)
    for level in range(floors):
        _story(m, 0, 0, w-1, d-1, level*height, p, door if level == 0 else None,
               level, bool(p["flat"]), opening_side=wing and level==0)
        _furnish(m, w, d, level*height, level, p, params["building_type"], seed+level*5)
    if floors >= 2:
        # Connected staircase; remove the second-story slab where headroom needs to stay open.
        start_x, start_z = w-4, d-4
        for n in range(1, 6):
            m.add(start_x, n, start_z-n+1, "minecraft:spruce_stairs[facing=north,half=bottom]", "interior")
            m.remove(start_x, height, start_z-n+1)
            if n >= 3:
                m.remove(start_x, height+1, start_z-n+1)
        # Balcony physically held by posts.
        for x in range(w//2-3, w//2+4):
            for z in (-2, -1):
                m.add(x, height, z, p["floor"], "facade")
                m.add(x, height+1, -2, p["fence"], "facade")
        for x in (w//2-3, w//2+3):
            for y in range(0, height):
                m.add(x, y, -2, p["beam"], "facade")
    main_roof = _roof(m, 0, 0, w-1, d-1, floors*height, p, params["style"], rng,
                      pitch=params["roof_pitch"], requested_overhang=params["roof_overhang"])
    if wing:
        # A separate attached volume with its own narrower roof ridge, not a prefab sticker.
        za = max(3, d//3)
        zb = min(d-3, za+8)
        wx0, wx1 = w-2, w+6
        _story(m, wx0, za, wx1, zb, 0, p, None, 0, bool(p["flat"]), opening_side=False)
        _roof(m, wx0, za, wx1, zb, height, p, params["style"], rng,
              ridge_direction="x", pitch=params["roof_pitch"], requested_overhang=params["roof_overhang"])
        # Passage through the actual shared wall, with two-block head clearance.
        through_z = za+(zb-za)//2
        for xx in (w-2, w-1):
            for zz in (through_z, through_z+1):
                for yy in (1, 2, 3):
                    m.remove(xx, yy, zz)
        m.add(wx1-2, 1, zb-2, "minecraft:barrel", "interior")
        m.add(wx1-3, 1, zb-2, "minecraft:crafting_table", "interior")
    # Chimney supports itself, breaks symmetry and terminates above roof.
    if params["building_type"] != "watchtower" and not p["flat"]:
        cx = 3 if seed%2 else w-4
        cz = d-4
        for yy in range(height+1, int(main_roof["ridge_y"])+3):
            m.add(cx, yy, cz, "minecraft:bricks", "roof")
        m.add(cx, int(main_roof["ridge_y"])+3, cz, "minecraft:campfire[lit=false]", "roof")
    _landscape(m, w, d, base, p, seed, terrain)
    quality = quality_report(m, w, d, floors, base, main_roof, terrain, door)
    structure = m.structure(params["title"]+".mcbh")
    structure["design_brief"] = params
    structure["design_origin"] = params["anchor"]
    structure["design_quality"] = quality
    blueprint = {"title":params["title"], "dimension":"minecraft:overworld",
                 "intent":{"source":"original MCBH architecture", "style":params["style"],
                           "building_type":params["building_type"],"seed":seed,
                           "designer_quality_is_heuristic":True,
                           "requires_world_collision_review":True,
                           "roof":main_roof},
                 "phases":m.phase_ops()}
    # Compile every block state and coordinate using the existing safety compiler.
    compiled = compile_blueprint(blueprint)
    quality["command_count"] = compiled["job_commands"]
    quality["roof"] = main_roof
    quality["wing"] = wing
    return {"blueprint":blueprint, "structure":structure,
            "quality":quality, "design":params}


def revision(original: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(overrides, dict):
        raise BuildError("Design changes must be a JSON object")
    permitted = {"style", "building_type", "width", "depth", "floors", "seed", "wing", "terrain", "anchor", "title",
                 "roof_pitch", "roof_overhang", "material_overrides"}
    if any(k not in permitted for k in overrides):
        raise BuildError(f"Allowed design changes: {sorted(permitted)}")
    new = dict(original)
    new.update(overrides)
    return generate(new)
