"""PROP cache must match selected stable members and their selected asset bytes."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from app.models.novel import Novel, Chapter, Prop
from app.models.shot import Shot
from app.services.file_storage import FileStorageService
from app.services.shot_keyframe_service import ShotKeyframeService
from app.utils.image_utils import merge_prop_images
import app.services.shot_keyframe_service as module


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def props(db_session, tmp_path, monkeypatch):
    storage = FileStorageService(str(tmp_path))
    def to_path(url):
        return str(tmp_path / url.removeprefix('/api/files/')) if url else None
    def to_url(path):
        return '/api/files/' + str(Path(path).relative_to(tmp_path))
    def asset(name, color):
        path = tmp_path / (name + '.png'); Image.new('RGB', (80, 96), color).save(path)
        return to_url(path)
    monkeypatch.setattr(module, 'file_storage', storage)
    monkeypatch.setattr(module, 'url_to_local_path', to_path)
    monkeypatch.setattr(module, 'local_path_to_url', to_url)
    novel = Novel(id='prop-novel', title='props')
    chapter = Chapter(id='prop-chapter', novel_id=novel.id, number=1, title='chapter')
    members = [Prop(id=f'p{i}', novel_id=novel.id, name=f'道具{i}', existence='REAL',
                    image_url=asset(f'p{i}', (20 + i * 60, 80, 90))) for i in range(3)]
    shot = Shot(id='prop-shot', chapter_id=chapter.id, index=6, characters='[]', keyframes='[]',
                props=json.dumps([p.name for p in members]))
    db_session.add_all([novel, chapter, shot, *members]); db_session.commit()
    legacy = merge_prop_images(novel.id, chapter.id, shot.index,
                              [(p.name, to_path(p.image_url)) for p in members], storage)
    shot.merged_prop_image = to_url(legacy); db_session.commit()
    service = ShotKeyframeService()
    def candidates():
        return service._build_reference_candidates(db_session, novel, shot,
            [{'description': ' '.join(p.name for p in members)}], 0)
    def resolve(chosen, available=None):
        return service._resolve_reference_manifest(db_session, novel, shot,
            {'selected_references': [{'type': 'PROP', 'ref_ids': [f'PROP:{p.name}' for p in chosen]}]},
            candidates() if available is None else available)
    return SimpleNamespace(**locals())


def test_subset_cache_and_asset_versions(props, db_session):
    p = props; old = digest(p.legacy)
    item = p.resolve(p.members[:2])[0]
    assert item['prop_ids'] == ['p0', 'p1'] and item['composed']
    assert item['path'] != p.legacy and digest(p.legacy) == old
    with Image.open(item['path']) as merged:
        for index, member in enumerate(p.members[:2]):
            with Image.open(p.to_path(member.image_url)) as source:
                y = 59 + index * (96 + 44)
                assert merged.crop((15, y, 95, y + 96)).tobytes() == source.tobytes()
    assert p.resolve(p.members[:2])[0]['path'] == item['path']
    assert p.resolve(p.members[1:])[0]['path'] != item['path']
    available = p.candidates()
    p.members[0].image_url = p.asset('p0-new', (250, 250, 10)); db_session.commit()
    assert p.resolve(p.members[:2], available)[0]['path'] == item['path']
    assert p.resolve(p.members[:2])[0]['path'] != item['path']
    assert digest(p.legacy) == old and Path(item['path']).is_file()
    assert p.shot.merged_prop_image == p.to_url(p.legacy)


def test_single_and_no_legacy_keep_existing_slot_budget(props):
    p = props
    one = p.resolve(p.members[:1]); assert len(one) == 1 and not one[0]['composed']
    assert one[0]['url'] == p.members[0].image_url
    p.shot.merged_prop_image = None
    items = p.resolve(p.members[:2])
    assert len(items) == 2
    assert [item['url'] for item in items] == [x.image_url for x in p.members[:2]]
    assert [item['picture'] for item in items] == [1, 2]


def test_changed_bytes_and_foreign_identity_rejected(props):
    p = props; available = p.candidates()
    p.asset('p0', (0, 0, 0))
    with pytest.raises(ValueError, match='版本已变化'):
        p.resolve(p.members[:2], available)
    available = p.candidates(); available[0]['prop_id'] = 'foreign'
    with pytest.raises(ValueError, match='稳定 ID'):
        p.resolve(p.members[:2], available)
