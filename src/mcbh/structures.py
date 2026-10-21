"""Local, bounded Sponge v2/v3 and Litematica structure-to-instructions engine.

This is an independently authored implementation informed by documented formats,
not a copy of Brictora's application code. The input directory is deliberately
restricted: untrusted agents may not open arbitrary files via the MCP server.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import gzip
import hashlib
import json
import math
import os
import re
import struct
import tempfile
import zlib

from .core import BuildError, block, compile_blueprint, pos

MAX_FILE = 16 * 1024 * 1024
MAX_INFLATED = 64 * 1024 * 1024
MAX_DIM = 512
MAX_VOXELS = 500_000
MAX_NON_AIR = 250_000
MAX_DEPTH = 35
NAME = re.compile(r"^[a-zA-Z0-9_-]{1,90}\.(schem|litematic)$", re.I)
STRUCT_ID = re.compile(r"^[0-9a-f]{32}$")


class NBTError(BuildError):
    """Malformed or unsupported structure NBT."""


class NBTReader:
    def __init__(self, payload: bytes):
        self.data = memoryview(payload)
        self.offset = 0

    def take(self, n: int) -> memoryview:
        if n < 0 or n > len(self.data) - self.offset:
            raise NBTError('Truncated NBT payload or invalid array length')
        result = self.data[self.offset:self.offset+n]
        self.offset += n
        return result

    def number(self, fmt: str) -> Any:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def string(self) -> str:
        n = self.number('>H')
        try:
            return self.take(n).tobytes().decode('utf-8')
        except UnicodeDecodeError as exc:
            raise NBTError('Invalid NBT UTF-8 string') from exc

    def payload(self, tag: int, depth: int = 0) -> Any:
        if depth > MAX_DEPTH:
            raise NBTError('NBT nesting exceeds safety limit')
        if tag in (1, 2, 3, 4, 5, 6):
            return self.number({1:'>b',2:'>h',3:'>i',4:'>q',5:'>f',6:'>d'}[tag])
        if tag == 7:
            return self.take(self.number('>i')).tobytes()
        if tag == 8:
            return self.string()
        if tag == 9:
            kind = self.number('>B')
            count = self.number('>i')
            if count < 0 or count > MAX_VOXELS * 4 or (kind == 0 and count):
                raise NBTError('NBT list length/type invalid')
            return [self.payload(kind, depth+1) for _ in range(count)]
        if tag == 10:
            out: dict[str,Any] = {}
            while True:
                kind = self.number('>B')
                if kind == 0:
                    return out
                key = self.string()
                if key in out:
                    raise NBTError('Duplicate NBT compound key')
                out[key] = self.payload(kind,depth+1)
                if len(out) > 300_000:
                    raise NBTError('Too many NBT compound keys')
        if tag in (11, 12):
            n = self.number('>i')
            fmt = 'i' if tag == 11 else 'q'
            width = 4 if tag == 11 else 8
            if n < 0 or n > MAX_VOXELS*4:
                raise NBTError('NBT numeric array too large')
            data = self.take(n * width)
            return list(struct.unpack(f'>{n}{fmt}', data))
        raise NBTError(f'Unsupported NBT tag {tag}')

    def document(self) -> dict[str,Any]:
        if self.number('>B') != 10:
            raise NBTError('NBT root is not a compound')
        self.string()  # named root, often blank
        root = self.payload(10)
        if self.offset != len(self.data):
            raise NBTError('Trailing NBT data')
        return root


def _read_bounded(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size > MAX_FILE:
        raise NBTError('Input must be an existing file of at most 16 MiB')
    raw = path.read_bytes()
    if len(raw) > MAX_FILE:
        raise NBTError('Input too large')
    if raw[:2] == b'\x1f\x8b':
        bits = 31
    elif raw[:1] == b'\x78':
        bits = zlib.MAX_WBITS
    else:
        if len(raw) > MAX_INFLATED:
            raise NBTError('Uncompressed NBT exceeds safety budget')
        return raw
    try:
        obj = zlib.decompressobj(bits)
        data = obj.decompress(raw, MAX_INFLATED + 1)
        if len(data) > MAX_INFLATED or not obj.eof or obj.unused_data:
            raise NBTError('Compressed NBT exceeds 64 MiB, is incomplete, or contains trailing data')
        data += obj.flush(MAX_INFLATED + 1 - len(data))
    except zlib.error as exc:
        raise NBTError('Invalid compressed NBT data') from exc
    if len(data) > MAX_INFLATED:
        raise NBTError('Decompressed NBT exceeds limit')
    return data


def _dimensions(size: tuple[int,int,int]) -> tuple[int,int,int]:
    if any(not isinstance(d,int) or d == 0 or abs(d) > MAX_DIM for d in size):
        raise NBTError('Invalid dimension; individual axes must be between 1 and 512')
    if math.prod(map(abs,size)) > MAX_VOXELS:
        raise NBTError('Structure volume exceeds 500,000 positions')
    return size


def _is_air(material: str) -> bool:
    return material in ('minecraft:air','minecraft:cave_air','minecraft:void_air')


def _varints(data: bytes, count: int) -> list[int]:
    result=[]; cursor=0
    for _ in range(count):
        value=0
        for k in range(5):
            if cursor >= len(data):
                raise NBTError('Truncated block palette varint array')
            b=data[cursor];cursor+=1
            value |= (b & 127) << (7*k)
            if b & 128 == 0:
                break
        else:
            raise NBTError('Varint exceeds 5 bytes')
        if value > 0x7fffffff:
            raise NBTError('Invalid block palette varint')
        result.append(value)
    if cursor != len(data):
        raise NBTError('Block palette indices count disagrees with structure dimensions')
    return result


def _sponge(root: dict[str,Any]) -> dict[str,Any]:
    nbt = root.get('Schematic', root)
    if not isinstance(nbt, dict):
        raise NBTError('Invalid Schematic compound')
    w,h,l = _dimensions(tuple(nbt.get(k,0) for k in ('Width','Height','Length')))
    blocks=nbt.get('Blocks')
    palette,encoded = (blocks.get('Palette'), blocks.get('Data')) if isinstance(blocks,dict) else (nbt.get('Palette'),nbt.get('BlockData'))
    if not isinstance(palette,dict) or not isinstance(encoded,(bytes,bytearray)):
        raise NBTError('Sponge .schem requires Palette and VarInt BlockData / Blocks.Data')
    id_to_block={}
    for name,index in palette.items():
        if type(index) is not int or index < 0 or index in id_to_block:
            raise NBTError('Sponge palette has an invalid or duplicate index')
        id_to_block[index]=block(name)
    ids=_varints(encoded,w*h*l)
    tiles=[]
    for i,palette_id in enumerate(ids):
        if palette_id not in id_to_block:
            raise NBTError(f'Palette index {palette_id} does not exist')
        name=id_to_block[palette_id]
        if not _is_air(name):
            x=i % w; z=(i // w) % l; y=i // (w*l)
            tiles.append([x,y,z,name])
            if len(tiles)>MAX_NON_AIR:
                raise NBTError('Too many non-air blocks; split the structure')
    offset=nbt.get('Offset',[0,0,0])
    warnings=[]
    if offset != [0,0,0]:
        warnings.append('Schematic Offset metadata is not applied; structure is normalized to 0,0,0')
    entities = nbt.get('Entities',[]) or []
    block_entities=nbt.get('BlockEntities',nbt.get('TileEntities',[])) or []
    if entities or block_entities:
        warnings.append(f'Entities ({len(entities)}) and block entities ({len(block_entities)}) not imported; no NBT injection')
    return {'format':'sponge-schem','size':[w,h,l],'blocks':tiles,'warnings':warnings,'regions':1}


def _litematic_state(nbt:dict[str,Any]) -> str:
    if not isinstance(nbt,dict):
        raise NBTError('Invalid Litematica block state')
    name=nbt.get('Name')
    if not isinstance(name,str):
        raise NBTError('Litematica block state missing Name')
    props=nbt.get('Properties',{})
    if not isinstance(props,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in props.items()):
        raise NBTError('Invalid Litematica block properties')
    raw=name + ('['+','.join(f'{k}={v}' for k,v in sorted(props.items()))+']' if props else '')
    return block(raw)


def _litematic(root:dict[str,Any]) -> dict[str,Any]:
    regions=root.get('Regions')
    if not isinstance(regions,dict) or not regions or len(regions)>128:
        raise NBTError('Litematica has no valid regions')
    all_tiles:dict[tuple[int,int,int],str]={}
    overall_min=[0,0,0];overall_max=[0,0,0]; first=True
    warnings=[];total_volume=0; overwritten=0
    for name,reg in sorted(regions.items()):
        if not isinstance(reg,dict):
            raise NBTError('Invalid Litematica region')
        size=reg.get('Size',{});origin=reg.get('Position',{})
        if not isinstance(size,dict) or not isinstance(origin,dict):
            raise NBTError('Invalid Litematica region coordinates')
        dims=_dimensions(tuple(size.get(k,0) for k in ('x','y','z')))
        xyz=tuple(origin.get(k,0) for k in ('x','y','z'))
        if any(type(v) is not int for v in xyz):
            raise NBTError('Region positions must be integers')
        w,h,l=[abs(v) for v in dims]
        total_volume+=w*h*l
        if total_volume>MAX_VOXELS:
            raise NBTError('Combined region volume exceeds safety limit')
        a=[xyz[j]+min(0,dims[j]+1) for j in range(3)]
        b=[xyz[j]+max(0,dims[j]-1) for j in range(3)]
        for j in range(3):
            if first:overall_min[j],overall_max[j]=a[j],b[j]
            else:overall_min[j]=min(overall_min[j],a[j]);overall_max[j]=max(overall_max[j],b[j])
        first=False
        palette=reg.get('BlockStatePalette',[])
        longs=reg.get('BlockStates',[])
        if not isinstance(palette,list) or not palette or not isinstance(longs,list):
            raise NBTError('Region missing palette or packed block states')
        names=[_litematic_state(x) for x in palette]
        bits=max(2,(len(names)-1).bit_length()); mask=(1<<bits)-1
        size_total=w*h*l
        if len(longs)!=math.ceil(size_total*bits/64):
            raise NBTError('Litematica packed long-array length mismatch')
        unsigned=[x&0xffffffffffffffff for x in longs]
        for i in range(size_total):
            bit=i*bits;word=bit//64;shift=bit%64
            index=(unsigned[word]>>shift)&mask
            if shift+bits>64:
                index |= (unsigned[word+1]<<(64-shift))&mask
            if index>=len(names):
                raise NBTError('Litematica palette bit index out of range')
            x=i%w;z=(i//w)%l;y=i//(w*l)
            coord=(xyz[0]+x*(1 if dims[0]>0 else -1),xyz[1]+y*(1 if dims[1]>0 else -1),xyz[2]+z*(1 if dims[2]>0 else -1))
            if coord in all_tiles:
                overwritten+=1
            all_tiles[coord]=names[index]
        entities=reg.get('Entities',[]) or []
        block_entities=reg.get('TileEntities',[]) or []
        if entities or block_entities:
            warnings.append(f'{name}: {len(entities)} entities and {len(block_entities)} block entities skipped')
    if overwritten:
        warnings.append(f'{overwritten} overlapping region positions resolved by region name order')
    size=[overall_max[k]-overall_min[k]+1 for k in range(3)]
    if math.prod(size)>MAX_VOXELS:
        raise NBTError('Union bounding volume exceeds limit')
    tiles=[[x-overall_min[0],y-overall_min[1],z-overall_min[2],state]
           for (x,y,z),state in all_tiles.items() if not _is_air(state)]
    if len(tiles)>MAX_NON_AIR:
        raise NBTError('Too many non-air blocks; split the structure')
    tiles.sort(key=lambda v:(v[1],v[2],v[0]))
    return {'format':'litematic','size':size,'blocks':tiles,'warnings':warnings,'regions':len(regions)}


def parse_structure(path: Path) -> dict[str,Any]:
    if path.suffix.lower() not in ('.schem','.litematic'):
        raise NBTError('Only .schem and .litematic files are supported')
    payload=_read_bounded(path)
    nbt=NBTReader(payload).document()
    result=(_sponge(nbt) if path.suffix.lower()=='.schem' else _litematic(nbt))
    result['source_digest']=hashlib.sha256(payload).hexdigest()
    result['name']=path.name
    result['blocks'].sort(key=lambda a:(a[1],a[2],a[0]))
    return result


def _safe_filename(filename:str) -> str:
    if not isinstance(filename,str) or not NAME.fullmatch(filename):
        raise NBTError('Use a plain .schem or .litematic filename, no paths')
    return filename


def _root_dir(env_name:str, fallback:str) -> Path:
    return Path(os.environ.get(env_name,str(Path.home()/'.mcbh'/fallback))).expanduser().resolve()


def import_file(filename:str) -> dict[str,Any]:
    name=_safe_filename(filename)
    root=_root_dir('MCBH_IMPORT_DIR','imports')
    path=(root/name).resolve()
    if not path.is_relative_to(root):
        raise NBTError('Import path escapes the configured import directory')
    content=parse_structure(path)
    blob=json.dumps(content,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    sid=hashlib.sha256(blob).hexdigest()[:32]
    content['id']=sid
    folder=_root_dir('MCBH_DATA_DIR','jobs')/'structures'
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/f'{sid}.json.gz'
    if not target.exists():
        _atomic_gzip(target,json.dumps(content,ensure_ascii=False).encode('utf-8'))
    return summary(content)


def _atomic_gzip(target:Path, data:bytes) -> None:
    import io
    compressed=gzip.compress(data,mtime=0)
    fd,tmp=tempfile.mkstemp(dir=target.parent,prefix='.structure-',suffix='.tmp')
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(compressed);out.flush();os.fsync(out.fileno())
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def load_structure(sid:str) -> dict[str,Any]:
    if not isinstance(sid,str) or not STRUCT_ID.fullmatch(sid):
        raise NBTError('Invalid structure ID')
    path=_root_dir('MCBH_DATA_DIR','jobs')/'structures'/f'{sid}.json.gz'
    if not path.is_file() or path.stat().st_size>MAX_INFLATED:
        raise NBTError('Structure not found or invalid')
    with gzip.open(path,'rt',encoding='utf-8') as file:
        content=json.load(file)
    if content.get('id')!=sid:
        raise NBTError('Structure identity mismatch')
    return content


def summary(structure:dict[str,Any]) -> dict[str,Any]:
    count=Counter(item[3] for item in structure['blocks'])
    per_y=Counter(item[1] for item in structure['blocks'])
    return {'structure_id':structure['id'],'filename':structure['name'], 'format':structure['format'],
            'size':structure['size'], 'region_count':structure['regions'], 'blocks':sum(count.values()),
            'unique_materials':len(count),'materials':dict(count.most_common()),
            'layers':{str(y):per_y[y] for y in sorted(per_y)},'warnings':structure['warnings'],
            'non_destructive':True}


def materials(structure:dict[str,Any],survival:bool=True) -> list[dict[str,Any]]:
    counts=Counter(v[3] for v in structure['blocks'])
    return [{'block':name,'count':quantity,'stacks':quantity//64,'remainder':quantity%64,
             'survival_note':('Check recipe/rarity in actual version and modpack' if survival else 'Creative inventory')} for name,quantity in counts.most_common()]


def _runs(structure:dict[str,Any]) -> list[dict[str,Any]]:
    result=[]; prev=None
    for x,y,z,material in structure['blocks']:
        if prev is not None and prev['y']==y and prev['z']==z and prev['block']==material and prev['x_to']+1==x:
            prev['x_to']=x;prev['count']+=1
        else:
            prev={'y':y,'z':z,'x_from':x,'x_to':x,'count':1,'block':material}
            result.append(prev)
    return result


def steps(structure:dict[str,Any],start:int=0,count:int=20, mode:str='survival') -> dict[str,Any]:
    if mode not in ('survival','creative'):
        raise NBTError('Mode must be survival or creative')
    if not 0 <= start <= MAX_NON_AIR or not 1 <= count <= 100:
        raise NBTError('Step range invalid')
    groups=_runs(structure)
    out=[]
    for idx,run in enumerate(groups[start:start+count],start=start):
        kind=run['block'].split('[',1)[0]
        support=any(s in kind for s in ('torch','lantern','rail','flower','button','lever','vine','carpet','wall_sign'))
        out.append({'step':idx+1,'total_steps':len(groups),'layer':run['y'],'material':run['block'],
                    'count':run['count'],'from':[run['x_from'],run['y'],run['z']],
                    'to':[run['x_to'],run['y'],run['z']],
                    'tip':('Check adjacent support/attachment first' if support else 'Lay left-to-right along this row'),
                    'mode':mode})
    return {'total_steps':len(groups),'from_step':start+1 if groups else 0,'steps':out,
            'next_offset':start+len(out) if start+len(out)<len(groups) else None,
            'warning':'Bottom-up geometry order is not a full physics dependency solver; inspect falling/support blocks.'}


def layer(structure:dict[str,Any],y:int, x_from:int=0,z_from:int=0,width:int=32,depth:int=32)->dict[str,Any]:
    w,h,l=structure['size']
    if not (0<=y<h and 0<=x_from<w and 0<=z_from<l and 1<=width<=64 and 1<=depth<=64):
        raise NBTError('Invalid layer or crop; maximum viewport 64x64')
    xmax=min(w,x_from+width);zmax=min(l,z_from+depth)
    section={(x,z):state for x,yy,z,state in structure['blocks'] if yy==y and x_from<=x<xmax and z_from<=z<zmax}
    unique=sorted(set(section.values()))
    symbols='123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!@#$%^&*'
    if len(unique)>len(symbols):
        raise NBTError('Too many materials in this viewport; reduce area')
    enc=dict(zip(unique,symbols))
    return {'y':y,'x_origin':x_from,'z_origin':z_from,'width':xmax-x_from,'depth':zmax-z_from,
            'rows':[ ''.join(enc.get(section.get((x,z)),'.') for x in range(x_from,xmax)) for z in range(z_from,zmax)],
            'legend':{enc[k]:k for k in unique},'empty':'.','orientation':'Rows are Z increasing (north→south), columns are X increasing (west→east)'}


def blueprint(structure:dict[str,Any],at:list[int],dim:str='minecraft:overworld',clear_air:bool=False) -> dict[str,Any]:
    anchor=pos(at)
    runs=_runs(structure)
    ops=[]
    if clear_air:
        # Explicit destructive clearing phase, separate from construction.
        far=tuple(anchor[i]+structure['size'][i]-1 for i in range(3))
        pos(far)
        ops.append({'name':'clear_area','operations':[{'type':'box','from':list(anchor),'to':list(far),'block':'minecraft:air'}]})
    if not runs:
        raise NBTError('The structure contains no non-air blocks')
    chunk=[];num=0
    for run in runs:
        x1,y,z=run['x_from'],run['y'],run['z']
        x2=run['x_to']
        a=[anchor[0]+x1,anchor[1]+y,anchor[2]+z]
        b=[anchor[0]+x2,anchor[1]+y,anchor[2]+z]
        pos(a);pos(b)
        chunk.append({'type':'set','at':a,'block':run['block']} if x1==x2 else
                     {'type':'box','from':a,'to':b,'block':run['block']})
        if len(chunk)==8_000:
            ops.append({'name':f'placement_{num:03d}','operations':chunk})
            num+=1;chunk=[]
    if chunk:
        ops.append({'name':f'placement_{num:03d}','operations':chunk})
    if len(ops)>30:
        raise NBTError('Structure has too many build phases; split into smaller files')
    bp={'title':'Imported '+structure['name'], 'dimension':dim,
        'intent':{'source':'local structure import','source_format':structure['format'],
                  'structure_id':structure['id'],'human_review_required':True,'clear_air':clear_air},
        'phases':ops}
    compile_blueprint(bp)
    return bp


def export_mcfunction(structure:dict[str,Any],at:list[int],dim:str='minecraft:overworld',clear_air:bool=False,filename:str='mcbh-import.mcfunction')->dict[str,Any]:
    if not isinstance(filename,str) or not re.fullmatch(r'[a-z0-9_./-]{1,100}\.mcfunction',filename) or filename.startswith('/') or '..' in filename:
        raise NBTError('Invalid relative mcfunction export filename')
    bp=blueprint(structure,at,dim,clear_air)
    compiled=compile_blueprint(bp)
    root=_root_dir('MCBH_EXPORT_DIR','exports')
    dst=(root/filename).resolve()
    if not dst.is_relative_to(root):
        raise NBTError('Export path escapes sandbox')
    dst.parent.mkdir(parents=True,exist_ok=True)
    content='\n'.join('execute in '+dim+' run '+cmd for ph in compiled['phases'] for cmd in ph['commands'])+'\n'
    fd,tmp=tempfile.mkstemp(dir=dst.parent,prefix='.mcfunction-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(tmp,dst)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return {'file':str(dst),'commands':compiled['job_commands'],'voxels':compiled['estimated_voxels'],
            'warning':'Review world coordinates; .mcfunction must be installed/run by your datapack and may overwrite existing blocks.'}


def guide_progress(sid:str, set_completed:int|None=None, mode:str='survival')->dict[str,Any]:
    """Progress stored per structure in the same sandbox; does not claim remote sync."""
    obj=load_structure(sid)
    total=len(_runs(obj))
    if mode not in ('survival','creative'):
        raise NBTError('Mode must be survival or creative')
    folder=_root_dir('MCBH_DATA_DIR','jobs')/'guide-progress'
    folder.mkdir(parents=True,exist_ok=True)
    file=folder/f'{sid}.{mode}.json'
    completed=0
    if file.is_file():
        try:
            value=json.loads(file.read_text(encoding='utf-8'))
            completed=value['completed_steps']
            if type(completed) is not int or not 0<=completed<=total:
                raise ValueError('Invalid progress state')
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
            raise NBTError('Invalid saved progress state') from exc
    if set_completed is not None:
        if type(set_completed) is not int or not 0<=set_completed<=total:
            raise NBTError(f'Completed steps must be integer 0..{total}')
        completed=set_completed
        fd,temp=tempfile.mkstemp(dir=folder,prefix='.progress-')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump({'completed_steps':completed,'mode':mode,'structure_id':sid},stream)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temp,file)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return {'structure_id':sid,'mode':mode,'completed_steps':completed,'total_steps':total,
            'percent':round(completed*100/total,2) if total else 100,
            'next_offset':completed if completed<total else None,
            'storage':'Local persisted MCBH_DATA_DIR; not cloud or cross-machine sync'}


def repalette(sid:str,changes:dict[str,str])->dict[str,Any]:
    """Duplicate an imported structure with safe material substitution, preserving spatial state positions."""
    source=load_structure(sid)
    if not isinstance(changes,dict) or not 1<=len(changes)<=128:
        raise NBTError('Supply 1..128 block-state substitutions')
    transform={block(a):block(b) for a,b in changes.items()}
    if any(_is_air(b) for b in transform.values()):
        raise NBTError('Repalette cannot replace material with air; explicit terrain editing must be reviewed')
    new={k:v for k,v in source.items() if k not in ('id','blocks','source_digest')}
    new['blocks']=[[x,y,z,transform.get(material,material)] for x,y,z,material in source['blocks']]
    new['warnings']=list(source['warnings'])+['Material swaps do not automatically rotate block-states, guarantee support or validate mods']
    new['name']='repalette-'+sid[:12]+'.schem'
    new['origin_id']=sid
    compressed=json.dumps(new,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    new_sid=hashlib.sha256(compressed).hexdigest()[:32]
    new['id']=new_sid
    folder=_root_dir('MCBH_DATA_DIR','jobs')/'structures';folder.mkdir(parents=True,exist_ok=True)
    target=folder/f'{new_sid}.json.gz'
    if not target.exists():
        _atomic_gzip(target,json.dumps(new,ensure_ascii=False).encode('utf-8'))
    return summary(new)
