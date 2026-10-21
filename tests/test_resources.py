from importlib.resources import files
import json


def test_included_resource_library():
    root = files('mcbh') / 'data'
    assert '## 15. Visual apprenticeship is mandatory' in (root/'SKILL.md').read_text(encoding='utf-8')
    assert 'visual' in (root/'REFERENCE_ATLAS.md').read_text(encoding='utf-8')
    assert 'medieval_timber' in json.loads((root/'palettes.json').read_text(encoding='utf-8'))['palettes']
    assert len(json.loads((root/'references.json').read_text(encoding='utf-8'))) >= 12
    visual=json.loads((root/'visual_index.json').read_text(encoding='utf-8'))
    assert len(visual['items']) == 20
    assert sum(x['type']=='external-screenshot' for x in visual['items']) == 8
    assert all(x['image_url'].startswith('https://') and x['source_url'].startswith('https://') for x in visual['items'])
