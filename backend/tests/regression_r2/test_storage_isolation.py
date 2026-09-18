import hashlib
from pathlib import Path
import pytest
from app.services.file_storage import FileStorageService
from app.utils.path_utils import url_to_local_path,local_path_to_url


pytestmark=pytest.mark.PURE


def test_explicit_execution_storage_root_is_shared_by_producers_and_url_resolution(tmp_path,monkeypatch):
    monkeypatch.setenv('NOVELFLOW_STORAGE_ROOT',str(tmp_path))
    storage=FileStorageService()
    assert storage.base_dir==tmp_path
    path=storage._get_story_dir('r2-fixture-id')/'reference.wav';path.write_bytes(b'fixture bytes')
    url=local_path_to_url(str(path))
    assert url=='/api/files/story_r2-fixtu/reference.wav'
    assert Path(url_to_local_path(url))==path


def test_default_storage_root_still_targets_existing_backend_story_dir(monkeypatch):
    created=[]
    monkeypatch.delenv('NOVELFLOW_STORAGE_ROOT',raising=False)
    monkeypatch.setattr(Path,'mkdir',lambda self,*args,**kwargs:created.append(self))
    storage=FileStorageService()
    assert storage.base_dir==(Path(__file__).parents[2]/'user_story').resolve()
    assert created==[storage.base_dir]


def test_storage_root_symlink_alias_round_trips_canonical_bytes(tmp_path,monkeypatch):
    canonical=tmp_path/'canonical';canonical.mkdir()
    alias=tmp_path/'alias';alias.symlink_to(canonical,target_is_directory=True)
    monkeypatch.setenv('NOVELFLOW_STORAGE_ROOT',str(alias))
    storage=FileStorageService()
    path=storage._get_story_dir('alias-fixture')/'reference.bin';payload=b'canonical storage bytes';path.write_bytes(payload)
    alias_path=alias/path.relative_to(canonical)
    url=local_path_to_url(str(alias_path))
    resolved=Path(url_to_local_path(url))
    assert storage.base_dir==canonical.resolve()
    assert url==local_path_to_url(str(path))=='/api/files/story_alias-fi/reference.bin'
    assert resolved==path.resolve() and resolved.read_bytes()==alias_path.read_bytes()==payload
    assert hashlib.sha256(resolved.read_bytes()).hexdigest()==hashlib.sha256(alias_path.read_bytes()).hexdigest()
    assert url_to_local_path('/api/files/story_alias-fi/missing.bin') is None
    outside=tmp_path/'outside.bin';outside.write_bytes(b'outside')
    escape=canonical/'escape.bin';escape.symlink_to(outside)
    assert url_to_local_path('/api/files/../outside.bin') is None
    assert url_to_local_path('/api/files/escape.bin') is None
    assert local_path_to_url(str(outside)) is None
