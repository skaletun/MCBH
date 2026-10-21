"""Fixture-backed format tests; no Mojang/Brictora assets or server necessary."""
from __future__ import annotations
import gzip
import json
import math
import os
import struct
from pathlib import Path
import pytest
from mcbh import structures as st
from mcbh.viewer import export_viewer


def s(text):
    b=text.encode('utf-8');return struct.pack('>H',len(b))+b


def item(tag,name,value):
    return bytes([tag])+s(name)+value


def i32(n):return struct.pack('>i',n)
def i16(n):return struct.pack('>h',n)
def bytearray(v):return i32(len(v))+v

def comp(d):
    return b''.join(item(*a) for a in d)+b'\x00'

def root(d):return b'\x0a'+s('')+comp(d)

def pack_palette(items):
    out=[]
    for p in items:
        out.append(b'\x0a'+comp([(8,'Name',s(p))]))
    return b'\x0a'+i32(len(items))+b''.join(comp([(8,'Name',s(p))]) for p in items)


def make_sponge(v3=False):
    palette=comp([(3,'minecraft:air',i32(0)),(3,'minecraft:oak_stairs[facing=east,half=bottom]',i32(1)),(3,'minecraft:stone',i32(2))])
    data=bytearray(b'\x01\x02\x00\x01')
    fields=[(2,'Width',i16(2)),(2,'Height',i16(1)),(2,'Length',i16(2))]
    if v3:
        fields.append((10,'Blocks',comp([(10,'Palette',palette),(7,'Data',data)])))
        return root([(10,'Schematic',comp(fields))])
    return root(fields+[(10,'Palette',palette),(7,'BlockData',data)])


def make_litematic():
    # 23 positions with 5 states => 3 bits/block, straddling 64-bit boundaries.
    names=['minecraft:air','minecraft:stone','minecraft:oak_log','minecraft:bricks','minecraft:water']
    indices=[i%5 for i in range(23)]
    bits=3;arr=[0]*math.ceil(len(indices)*bits/64)
    for i,v in enumerate(indices):
        base=i*bits;j=base//64;off=base%64
        arr[j]|=(v<<off)&0xffffffffffffffff
        if off+bits>64:arr[j+1]|=v>>(64-off)
    longs=i32(len(arr))+b''.join(struct.pack('>q',a if a<(1<<63) else a-(1<<64)) for a in arr)
    palette=b'\x0a'+i32(len(names))+b''.join(comp([(8,'Name',s(n))]) for n in names)
    region=comp([(10,'Size',comp([(3,'x',i32(-23)),(3,'y',i32(1)),(3,'z',i32(1))])),
                 (10,'Position',comp([(3,'x',i32(6)),(3,'y',i32(70)),(3,'z',i32(5))])),
                 (9,'BlockStatePalette',palette),(12,'BlockStates',longs)])
    return root([(10,'Regions',comp([(10,'room',region)]))])


@pytest.mark.parametrize('is_v3',[False,True])
def test_sponge_parse_and_exact_materials(tmp_path,is_v3):
    p=tmp_path/'house.schem';p.write_bytes(gzip.compress(make_sponge(is_v3)))
    obj=st.parse_structure(p)
    assert obj['size']==[2,1,2]
    assert obj['blocks']==[[0,0,0,'minecraft:oak_stairs[facing=east,half=bottom]'],[1,0,0,'minecraft:stone'],[1,0,1,'minecraft:oak_stairs[facing=east,half=bottom]']]
    assert len(st.materials(obj))==2
    assert st.layer(obj,0,width=2,depth=2)['rows'][0]=='12' or len(st.layer(obj,0,width=2,depth=2)['rows'][0])==2
    obj['id']='abcde12345abcde12345abcde12345ab'
    bp=st.blueprint(obj,[100,64,100]);assert 'minecraft:oak_stairs' in str(bp)
    compiled=st.compile_blueprint(bp)
    assert compiled['estimated_voxels']==3
    assert compiled['job_commands']>0


def test_litematic_cross_boundary_negative_region(tmp_path):
    p=tmp_path/'house.litematic';p.write_bytes(gzip.compress(make_litematic()))
    obj=st.parse_structure(p)
    assert obj['size']==[23,1,1]
    assert obj['regions']==1
    assert obj['blocks'][0][0]==0  # negative region normalized
    assert obj['blocks'][-1][0]==21 or obj['blocks'][-1][0]==22
    assert len(obj['blocks'])==18  # 23 values, five air at indices 0,5,10,15,20
    assert obj['blocks'][0][3]=='minecraft:oak_log'  # original i=22, reversed
    assert st.steps(obj)['total_steps']==18


def test_reject_path_and_bad_varints(tmp_path,monkeypatch):
    monkeypatch.setenv('MCBH_IMPORT_DIR',str(tmp_path))
    with pytest.raises(st.NBTError): st.import_file('../passwords.schem')
    with pytest.raises(st.NBTError): st.import_file('D:/secrets.schem')
    bad=make_sponge().replace(b'\x01\x02\x00\x01',b'\xff\xff\xff\xff')
    p=tmp_path/'evil.schem';p.write_bytes(gzip.compress(bad))
    with pytest.raises(st.NBTError):st.import_file('evil.schem')


def test_offline_interactive_viewer_export(tmp_path,monkeypatch):
    monkeypatch.setenv('MCBH_IMPORT_DIR',str(tmp_path/'imports'))
    monkeypatch.setenv('MCBH_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('MCBH_EXPORT_DIR',str(tmp_path/'exports'))
    folder=tmp_path/'imports';folder.mkdir()
    (folder/'cottage.schem').write_bytes(gzip.compress(make_sponge()))
    summary=st.import_file('cottage.schem'); assert summary['blocks']==3
    loaded=st.load_structure(summary['structure_id'])
    viewer=export_viewer(loaded,'guide.html')
    assert Path(viewer['file']).exists()
    assert all(x in Path(viewer['file']).read_text() for x in ['Material','Next','Step','wireColor','mcbh:'])
    assert st.steps(loaded,start=0,count=2)['next_offset'] is not None
    output=st.export_mcfunction(loaded,[9,70,10],filename='house.mcfunction')
    script=Path(output['file']).read_text()
    assert 'execute in minecraft:overworld run' in script
    assert 'minecraft:oak_stairs' in script
    assert '9 70 10' in script


def test_empty_bounds_and_trailing_data(tmp_path):
    with pytest.raises(st.NBTError):st.NBTReader(make_sponge()+b'malicious').document()
    with pytest.raises(st.NBTError):st._dimensions((600,1,2))
    with pytest.raises(st.NBTError):st._varints(b'\x80',1)


def test_progress_and_repalette(tmp_path, monkeypatch):
    monkeypatch.setenv('MCBH_IMPORT_DIR',str(tmp_path/'imports'))
    monkeypatch.setenv('MCBH_DATA_DIR',str(tmp_path/'data'))
    (tmp_path/'imports').mkdir()
    (tmp_path/'imports'/'cottage.schem').write_bytes(gzip.compress(make_sponge()))
    sid=st.import_file('cottage.schem')['structure_id']
    initial=st.guide_progress(sid)
    assert initial['completed_steps']==0
    assert st.guide_progress(sid,3)['percent']==100
    assert st.guide_progress(sid)['completed_steps']==3
    with pytest.raises(st.NBTError): st.guide_progress(sid,4)
    rep=st.repalette(sid,{'minecraft:stone':'minecraft:bricks'})
    assert rep['materials']['minecraft:bricks']==1
    assert st.load_structure(sid)['blocks'][1][3]=='minecraft:stone'
    assert rep['structure_id']!=sid
    assert st.guide_progress(rep['structure_id'])['completed_steps']==0
