from app.services.file_storage import FileStorageService


def test_video_merge_signature_tracks_mode_order_and_content(tmp_path):
    storage = FileStorageService(str(tmp_path / "storage"))
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"first-video")
    second.write_bytes(b"second-video")

    segments = [
        {"kind": "shot", "key": "1", "path": str(first)},
        {"kind": "shot", "key": "2", "path": str(second)},
    ]
    signature = storage.get_video_merge_signature("shots_only", segments)

    assert signature == storage.get_video_merge_signature("shots_only", segments)
    assert signature != storage.get_video_merge_signature("shots_with_transitions", segments)
    assert signature != storage.get_video_merge_signature("shots_only", list(reversed(segments)))

    second.write_bytes(b"updated-second-video")
    assert signature != storage.get_video_merge_signature("shots_only", segments)
