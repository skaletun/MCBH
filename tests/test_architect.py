"""Structural tests for original Minecraft building design, no game server required."""
from mcbh.architect import generate, normalize, revision, quality_report
from mcbh.core import BuildError, compile_blueprint
import pytest


@pytest.mark.parametrize("style", [
    "medieval_timber", "alpine_rustic", "japanese_traditional",
    "modern_concrete", "desert_adobe", "dark_fantasy"])
def test_every_architecture_style_builds_valid_phased_geometry(style):
    result = generate({"style": style, "width": 17, "depth": 17, "floors": 2,
                       "seed": 21, "anchor": [100, 90, 100]})
    assert result["quality"]["passed"], result["quality"]
    assert result["structure"]["format"] == "mcbh-original-architecture"
    assert len(result["structure"]["blocks"]) > 400
    assert len(result["blueprint"]["phases"]) >= 6
    assert compile_blueprint(result["blueprint"])["job_commands"] > 100
    assert "minecraft:air" not in compile_blueprint(result["blueprint"])["materials"]


def test_design_seed_is_reproducible_and_changes_real_voxels():
    a = {"style": "medieval_timber", "building_type": "tavern", "seed": 14}
    first = generate(a)
    assert first["structure"]["blocks"] == generate(a)["structure"]["blocks"]
    second = generate({**a, "seed": 15})
    assert first["structure"]["blocks"] != second["structure"]["blocks"]


def test_site_validation_does_not_bulldoze_terrain():
    with pytest.raises(BuildError, match="raise anchor Y"):
        generate({"anchor": [0, 64, 0], "terrain": [[0, 0, 69], [15, 15, 65]]})
    good = generate({"anchor": [0, 80, 0], "terrain": [[0, 0, 70], [18, 16, 73]],
                     "seed": 22})
    assert good["quality"]["passed"]


def test_door_and_material_roles_and_multiple_storeys():
    build = generate({"style": "alpine_rustic", "floors": 3, "seed": 5})
    assert build["quality"]["checks"]["doorway_two_blocks_clear"]
    assert build["quality"]["checks"]["independent_palette_roles"]
    assert build["quality"]["counts"]["roof_y_levels"] >= 3
    assert build["quality"]["counts"]["furniture_blocks"] >= 4


def test_revision_does_not_mutate_original_and_rejects_unknown_params():
    first = generate({"width": 21, "seed": 3})
    previous = first["design"].copy()
    second = revision(previous, {"width": 23, "seed": 9})
    assert first["design"] == previous
    assert second["design"]["width"] == 23
    assert first["structure"]["blocks"] != second["structure"]["blocks"]
    with pytest.raises(BuildError):
        revision(previous, {"execute_command": "kill @e"})


def test_rejects_invalid_brief_and_world_coordinates():
    with pytest.raises(BuildError):
        normalize({"width": 3})
    with pytest.raises(BuildError):
        normalize({"seed": True})
    with pytest.raises(BuildError):
        normalize({"anchor": [True, 80, 0]})
    with pytest.raises(BuildError):
        normalize({"terrain": [[0, 0, "unknown"]]})
    with pytest.raises(BuildError):
        generate({"anchor": [29999980, 90, 29999980]})


def test_building_type_and_reproducible_stages():
    a = generate({"building_type":"workshop","wing":True, "seed":7})
    b = generate({"building_type":"house","wing":False, "seed":7})
    assert a["quality"]["wing"]
    assert not b["quality"]["wing"]
    assert a["structure"]["blocks"] != b["structure"]["blocks"]
    assert "roof" in [p["name"] for p in a["blueprint"]["phases"]]


def test_roof_pitch_and_original_material_role_overrides():
    default = generate({"width": 27, "roof_pitch": "balanced", "seed": 27})
    shallow = generate({"width": 27, "roof_pitch": "low", "seed": 27,
                        "roof_overhang": 3,
                        "material_overrides": {"wall": "minecraft:birch_planks"}})
    assert shallow["quality"]["roof"]["ridge_y"] < default["quality"]["roof"]["ridge_y"]
    assert shallow["quality"]["roof"]["eaves"] == 3
    assert any(block == "minecraft:birch_planks" for *_,block in shallow["structure"]["blocks"])


def test_material_override_injection_and_bad_roof_families():
    with pytest.raises(BuildError):
        normalize({"material_overrides":{"wall":"minecraft:stone run say hacked"}})
    with pytest.raises(BuildError):
        normalize({"material_overrides":{"roof":"minecraft:dirt"}})
    with pytest.raises(BuildError):
        normalize({"material_overrides":{"teleport":"minecraft:stone"}})
    with pytest.raises(BuildError):
        normalize({"roof_overhang":100})


def test_ground_floor_circulation_is_really_reachable():
    from mcbh.architect import Mason, walkability
    good = generate({"width":17,"depth":17,"seed":22,"floors":1})
    assert good["quality"]["walkability"]["reachable"]
    m=Mason([0,80,0])
    for z in range(2,15):
        for x in range(2,15):
            m.add(x, 1, z, "minecraft:stone", "interior")
    assert not walkability(m, 17, 17, 0, 8)["reachable"]


def test_original_architecture_persists_and_exports(tmp_path, monkeypatch):
    from mcbh.server import _publish_architecture
    from mcbh import structures as st
    from mcbh.viewer import export_viewer
    monkeypatch.setenv("MCBH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MCBH_EXPORT_DIR", str(tmp_path/"exports"))
    output = _publish_architecture(generate({"style":"medieval_timber","anchor":[200,88,300],"seed":41}))
    assert output["staged"]
    assert output["job_id"] and output["approval_token"]
    obj = st.load_structure(output["structure_id"])
    assert st.summary(obj)["blocks"] == output["quality"]["counts"]["voxels"]
    assert len(st.materials(obj)) > 5
    assert st.steps(obj, 0, 3)["total_steps"] > 3
    viewer = export_viewer(obj, "generated-showcase.html")
    assert (tmp_path/"exports"/"generated-showcase.html").exists()
    assert viewer
    local_min = obj["local_min"]
    assert output["structure_export_anchor"] == [
        200+local_min[0], 88+local_min[1], 300+local_min[2]]
