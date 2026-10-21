import json
import pytest

from mcbh.core import (
    BuildError, Store, block, dimension, pos, tiles, points_on_line,
    compile_op, compile_blueprint, next_commands, review, job_progress,
)


def blueprint():
    return {"title":"Hill workshop","dimension":"minecraft:overworld","phases":[
        {"name":"foundation","operations":[{"type":"box","from":[0,64,0],"to":[20,65,20],"block":"minecraft:stone_bricks"}]},
        {"name":"structure","operations":[{"type":"line","from":[0,66,0],"to":[0,72,0],"block":"minecraft:spruce_log[axis=y]"}]},
        {"name":"interior","operations":[{"type":"set","at":[2,66,2],"block":"minecraft:barrel"}]},
    ]}


def test_validation_rejects_command_injection():
    for invalid in ("minecraft:stone run kill @e", "minecraft:air\nstop", "minecraft:stone{Command:'x'}", "not valid"):
        with pytest.raises(BuildError):
            block(invalid)
    with pytest.raises(BuildError):
        dimension("minecraft:overworld run stop")
    with pytest.raises(BuildError):
        pos([True,64,0])


def test_chunking_never_exceeds_limit_and_coverage():
    boxes=list(tiles((0,64,0),(99,83,99)))
    assert sum((b[0]-a[0]+1)*(b[1]-a[1]+1)*(b[2]-a[2]+1) for a,b in boxes)==200_000
    assert all((b[0]-a[0]+1)*(b[1]-a[1]+1)*(b[2]-a[2]+1)<=16_384 for a,b in boxes)


def test_hollow_large_not_split_wrongly():
    with pytest.raises(BuildError,match="cannot be split"):
        compile_op({"type":"box","from":[0,64,0],"to":[100,80,100],"block":"minecraft:stone","mode":"hollow"})


def test_filtered_single_block_is_conditional():
    commands=compile_op({"type":"box","from":[1,64,1],"to":[1,64,1],"block":"minecraft:stone","replace_only":"minecraft:dirt"})
    assert commands[0][0]=="execute if block 1 64 1 minecraft:dirt run setblock 1 64 1 minecraft:stone"


def test_shape_and_state():
    assert list(points_on_line((0,0,0),(3,0,0)))==[(0,0,0),(1,0,0),(2,0,0),(3,0,0)]
    cmds=compile_op({"type":"ellipsoid","from":[0,0,0],"to":[4,4,4],"block":"minecraft:oak_leaves[persistent=true]"})
    assert all(n>=1 for _,n,_ in cmds)
    assert sum(n for _,n,_ in cmds)<125


def test_stage_progress_and_persistence(tmp_path):
    store=Store(tmp_path)
    job=store.stage(blueprint())
    assert job["status"]=="staged"
    assert job["job_commands"]>0
    assert len(job["approval_token"])==24
    loaded=store.load(job["id"])
    assert next_commands(loaded,"foundation",3)
    with pytest.raises(BuildError,match="earlier phases"):
        next_commands(loaded,"structure",2)
    loaded["phases"][0]["complete"]=True
    assert next_commands(loaded,"structure",2)
    store.save(loaded)
    assert store.load(job["id"])["phases"][0]["complete"]
    assert store.list()[0]["id"]==job["id"]


def test_job_review_catches_missing_phases():
    job=compile_blueprint(blueprint())
    audit=review(job)
    assert "roof" in audit["advisory_warnings"][0]
    assert job_progress({**job,"id":"x","status":"staged"})["phases"][0]["total_commands"]>0


def test_rejects_bad_schema_and_non_integer_geometry():
    bp=blueprint()
    bp["phases"][0]["operations"][0]["from"]=[0.1,64,0]
    with pytest.raises(BuildError):
        compile_blueprint(bp)


def test_large_line_rejected_before_allocating_memory():
    with pytest.raises(BuildError,match="Line too long"):
        compile_op({"type":"line","from":[0,70,0],"to":[80_000,70,0],"block":"minecraft:stone"})
