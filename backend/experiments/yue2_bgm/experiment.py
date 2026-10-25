#!/usr/bin/env python3
"""Offline YuE2 BGM handoff experiment. Never imports the NovelFlow app or calls AI services."""

import argparse
import json
import math
import os
import sqlite3
import subprocess
import sys
import uuid
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent
DEFAULT_NOVEL_ID = "cf65a2bd-5a15-4b65-9c94-0a7746642ec7"
SAMPLE_RATE = 48000


def fail(message):
    raise ValueError(message)


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,duration,nb_frames", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=45, check=False,
    )
    if result.returncode:
        fail(f"ffprobe 失败：{path}: {result.stderr.strip()[:240]}")
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video = next((x for x in streams if x.get("codec_type") == "video"), None)
    audio = next((x for x in streams if x.get("codec_type") == "audio"), None)
    # The production merger normalizes each whole input. Its effective slot
    # length follows the container duration, which may include audio beyond
    # the last encoded video frame (AAC padding / final frame rounding).
    duration = float(payload.get("format", {}).get("duration") or
                     (video or audio or {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        fail(f"无法确定媒体时长：{path}")
    return {"duration": duration, "has_video": video is not None, "has_audio": audio is not None,
            "video_frames": int(video["nb_frames"]) if video and str(video.get("nb_frames") or "").isdigit() else None}


def local_video(media_root, url):
    prefix = "/api/files/"
    if not isinstance(url, str) or not url.startswith(prefix):
        fail(f"只接受本地媒体 URL：{url}")
    root = Path(media_root).resolve(strict=True)
    path = (root / url[len(prefix):]).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        fail(f"媒体路径不在存储目录内：{url}")
    return path


def source_record(path):
    stat = Path(path).stat()
    return {"path": str(Path(path).resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def verify_source(record):
    path = Path(record["path"])
    stat = path.stat()
    if stat.st_size != record["size"] or stat.st_mtime_ns != record["mtime_ns"]:
        fail(f"源视频在准备后发生变化，请重新 prepare：{path}")
    return path


def cue_regions(chapters, cue_spec):
    """Resolve Shot-boundary cues and make the no-music intervals explicit."""
    cues_by_chapter = {}
    seen = set()
    for item in cue_spec["cues"]:
        cue_id = item["id"]
        if cue_id in seen or not cue_id.replace("_", "").isalnum():
            fail(f"重复或非法 cue ID：{cue_id}")
        seen.add(cue_id)
        cues_by_chapter.setdefault(int(item["chapter_number"]), []).append(item)
    if set(cues_by_chapter) - {chapter["number"] for chapter in chapters}:
        fail("cue_spec 引用了小说外的章节")
    for chapter in chapters:
        spans = {item["index"]: item for item in chapter["shots"]}
        resolved = []
        for item in cues_by_chapter.get(chapter["number"], []):
            first, last = int(item["start_shot"]), int(item["end_shot"])
            if first not in spans or last not in spans or first > last:
                fail(f"Cue {item['id']} 的 Shot 范围无效")
            selected = [spans[index] for index in range(first, last + 1) if index in spans]
            if len(selected) != last - first + 1:
                fail(f"Cue {item['id']} 的 Shot 范围不连续")
            start, end = spans[first]["start_seconds"], spans[last]["end_seconds"]
            duration = end - start
            if duration <= 0:
                fail(f"Cue {item['id']} 时长无效")
            fade = float(item.get("fade_seconds", 1.0))
            gain = float(item.get("gain_db", -24))
            if not 0 <= fade <= duration / 2 or not -40 <= gain <= -12:
                fail(f"Cue {item['id']} 的淡入淡出或增益超出实验安全范围")
            resolved.append({"id": item["id"], "start_shot": first, "end_shot": last,
                             "start_seconds": round(start, 6), "end_seconds": round(end, 6),
                             "duration_seconds": round(duration, 6), "gain_db": gain,
                             "fade_seconds": fade, "reason": item["reason"], "style": item["style"],
                             "evidence_quote": item.get("evidence_quote"),
                             "sound_priority": item.get("sound_priority")})
        resolved.sort(key=lambda x: x["start_seconds"])
        no_music = []
        cursor = 0.0
        for cue in resolved:
            if cue["start_seconds"] < cursor - 0.000001:
                fail(f"第 {chapter['number']} 章 Cue 重叠")
            if cue["start_seconds"] > cursor + 0.000001:
                no_music.append({"start_seconds": round(cursor, 6), "end_seconds": cue["start_seconds"]})
            cursor = cue["end_seconds"]
        if cursor < chapter["duration_seconds"] - 0.000001:
            no_music.append({"start_seconds": round(cursor, 6), "end_seconds": chapter["duration_seconds"]})
        chapter["cues"] = resolved
        chapter["no_music_regions"] = no_music
    return chapters


def prepare(args):
    db_path = Path(args.db).resolve(strict=True)
    media_root = Path(args.media_root).resolve(strict=True)
    spec = read_json(args.cue_spec)
    if spec.get("novel_id") != args.novel_id:
        fail("Cue 清单的 novel_id 与目标小说不符")
    connection = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        novel = connection.execute("SELECT id,title FROM novels WHERE id=?", (args.novel_id,)).fetchone()
        if not novel:
            fail(f"小说不存在：{args.novel_id}")
        chapters = []
        for chapter in connection.execute(
            "SELECT id,number,title,final_video FROM chapters WHERE novel_id=? ORDER BY number", (args.novel_id,)
        ):
            if not chapter["final_video"]:
                fail(f"第 {chapter['number']} 章没有最终视频")
            chapter_path = local_video(media_root, chapter["final_video"])
            chapter_probe = probe(chapter_path)
            if not chapter_probe["has_video"] or not chapter_probe["has_audio"]:
                fail(f"第 {chapter['number']} 章成片缺少视频或原声音轨")
            task = connection.execute(
                "SELECT metadata_json FROM tasks WHERE type='chapter_video' AND chapter_id=? "
                "AND status='completed' AND result_url=? ORDER BY completed_at DESC LIMIT 1",
                (chapter["id"], chapter["final_video"]),
            ).fetchone()
            if not task:
                fail(f"第 {chapter['number']} 章缺少当前成片对应的合并任务")
            metadata = json.loads(task["metadata_json"] or "{}")
            if metadata.get("mode") != "shots_only" or not metadata.get("inputs"):
                fail(f"第 {chapter['number']} 章不是可校时的 shots_only 合并")
            shot_rows = connection.execute(
                'SELECT id,"index" FROM shots WHERE chapter_id=?', (chapter["id"],)
            ).fetchall()
            current_shots = {(row["id"], row["index"]) for row in shot_rows}
            task_shots = {(item["shot_id"], int(item["shot_index"])) for item in metadata["inputs"]}
            if len(metadata["inputs"]) != len(shot_rows) or task_shots != current_shots:
                fail(f"第 {chapter['number']} 章成片的 Shot 与当前章节不一致，需单独制作选片时间轴")
            position = 0.0
            shots = []
            for item in sorted(metadata["inputs"], key=lambda x: int(x["shot_index"])):
                shot_path = local_video(media_root, item["video_url"])
                shot_duration = probe(shot_path)["duration"]
                shots.append({"id": item["shot_id"], "index": int(item["shot_index"]),
                              "start_seconds": round(position, 6),
                              "end_seconds": round(position + shot_duration, 6),
                              "source_video": source_record(shot_path)})
                position += shot_duration
            mismatch = position - chapter_probe["duration"]
            if abs(mismatch) > 0.25:
                fail(f"第 {chapter['number']} 章 Shot 累加与成片时长相差 {mismatch:.3f}s，需人工核对")
            shots[-1]["end_seconds"] = round(chapter_probe["duration"], 6)
            chapters.append({"id": chapter["id"], "number": chapter["number"],
                             "title": chapter["title"], "source_video": source_record(chapter_path),
                             "source_video_url": chapter["final_video"],
                             "duration_seconds": round(chapter_probe["duration"], 6),
                             "video_frames": chapter_probe["video_frames"],
                             "shot_duration_mismatch_seconds": round(mismatch, 6),
                             "merge_mode": metadata["mode"], "shots": shots})
    finally:
        connection.close()
    cue_regions(chapters, spec)
    output_dir = Path(args.out).resolve()
    if output_dir == media_root or output_dir.is_relative_to(media_root):
        fail("实验输出目录不能在生产媒体目录内")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "purpose": "offline_yue2_bgm_simulation",
                "created_at": datetime.now(timezone.utc).isoformat(), "novel_id": novel["id"],
                "novel_title": novel["title"], "db_read_only": str(db_path),
                "media_root": str(media_root),
                "cue_spec": str(Path(args.cue_spec).resolve()), "chapters": chapters}
    write_json(output_dir / "manifest.json", manifest)
    requests = [{"cue_id": cue["id"], "chapter_number": chapter["number"],
                 "style_description": cue["style"], "minimum_usable_seconds": cue["duration_seconds"],
                 "suggested_generation_seconds": math.ceil(cue["duration_seconds"] + 2),
                 "required": "instrumental_without_singing_or_speech",
                 "note": "YuE2 纯器乐需使用经确认的器乐流程；生成后人工听检，再以 cue_id.wav/flac/mp3/m4a 导入。"}
                for chapter in chapters for cue in chapter["cues"]]
    write_json(output_dir / "yue2_requests.json", {"requests": requests})
    print(f"已准备 {novel['title']}：{len(chapters)} 章、{len(requests)} 个模拟 Cue；{output_dir}")


def all_cues(manifest):
    return [cue for chapter in manifest["chapters"] for cue in chapter["cues"]]


def mock_generate(args):
    manifest = read_json(args.manifest)
    output_dir = Path(args.out).resolve()
    media_root = Path(manifest["media_root"]).resolve(strict=True)
    if output_dir == media_root or output_dir.is_relative_to(media_root):
        fail("模拟音频输出目录不能在生产媒体目录内")
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    for number, cue in enumerate(all_cues(manifest)):
        path = output_dir / f"{cue['id']}.wav"
        if path.exists() and not args.force:
            fail(f"模拟音频已存在：{path}；使用 --force 才能覆盖")
        seconds = math.ceil(cue["duration_seconds"] + 2)
        frames = seconds * SAMPLE_RATE
        with wave.open(str(path), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            for start in range(0, frames, 4096):
                samples = array("h")
                for index in range(start, min(start + 4096, frames)):
                    t = index / SAMPLE_RATE
                    # Audible test chord, deliberately not presented as generated score.
                    value = 0.12 * (math.sin(2 * math.pi * (196 + number * 11) * t)
                                    + 0.35 * math.sin(2 * math.pi * (294 + number * 13) * t))
                    sample = int(max(-1, min(1, value)) * 32767)
                    samples.extend((sample, sample))
                output.writeframes(samples.tobytes())
        generated.append({"cue_id": cue["id"], "path": str(path), "duration_seconds": seconds})
    write_json(output_dir / "MOCK_AUDIO_ONLY.json", {"warning": "测试音，不是 YuE2 生成音乐", "files": generated})
    print(f"已生成 {len(generated)} 段明确标记为 MOCK 的测试音：{output_dir}")


def mix_one(chapter, audio_dir, output_dir, allow_mock=False, force=False):
    source = verify_source(chapter["source_video"])
    cues = chapter["cues"]
    if not cues:
        return {"chapter_number": chapter["number"], "status": "NO_MUSIC", "original_video": str(source)}
    audio_dir = Path(audio_dir).resolve(strict=True)
    mock = (audio_dir / "MOCK_AUDIO_ONLY.json").exists()
    unreviewed = "unreviewed" in audio_dir.name.lower()
    if mock and not allow_mock:
        fail("检测到 MOCK 测试音，需显式传入 --allow-mock")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    label = "MOCK" if mock else "UNREVIEWED" if unreviewed else "IMPORTED"
    target = output_dir / f"chapter_{chapter['number']:02d}_bgm_{label}.mp4"
    if target == source or target.exists() and not force:
        fail(f"输出已存在或与源视频相同：{target}；使用 --force 才能覆盖现有实验输出")
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-i", str(source)]
    inputs = []
    for cue in cues:
        matches = [audio_dir / f"{cue['id']}{extension}"
                   for extension in (".wav", ".flac", ".mp3", ".m4a")
                   if (audio_dir / f"{cue['id']}{extension}").is_file()]
        if len(matches) != 1:
            fail(f"Cue {cue['id']} 需要唯一的同名 wav/flac/mp3/m4a 音频")
        path = matches[0].resolve(strict=True)
        if not path.is_relative_to(audio_dir) or not path.is_file():
            fail(f"Cue 音频不在导入目录内：{cue['id']}")
        info = probe(path)
        if not info["has_audio"] or info["duration"] + 0.01 < cue["duration_seconds"]:
            fail(f"Cue {cue['id']} 的音频短于目标区间，不自动循环或拉伸")
        inputs.append({"cue_id": cue["id"], "path": str(path), "duration_seconds": info["duration"]})
        command += ["-i", str(path)]
    duration = chapter["duration_seconds"]
    filters = [f"[0:a:0]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
               f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[base]"]
    labels = ["[base]"]
    for index, cue in enumerate(cues, 1):
        length = cue["duration_seconds"]
        fade = cue["fade_seconds"]
        delay = round(cue["start_seconds"] * 1000)
        chain = (f"[{index}:a:0]aresample={SAMPLE_RATE},aformat=channel_layouts=stereo,"
                 f"atrim=duration={length:.6f},asetpts=PTS-STARTPTS")
        if fade:
            chain += f",afade=t=in:st=0:d={fade:.6f},afade=t=out:st={length-fade:.6f}:d={fade:.6f}"
        chain += f",volume={cue['gain_db']:.2f}dB,adelay={delay}|{delay}[cue{index}]"
        filters.append(chain)
        labels.append(f"[cue{index}]")
    filters.append("".join(labels) +
                   f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
                   f"alimiter=limit=0.95:attack=5:release=50:level=0:latency=1,"
                   f"atrim=duration={duration:.6f}[mixed]")
    temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp.mp4")
    command += ["-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[mixed]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                "-y", str(temporary)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
        if result.returncode:
            fail(f"混音失败：{result.stderr.strip()[-800:]}")
        output_info = probe(temporary)
        if not output_info["has_video"] or not output_info["has_audio"]:
            fail("混音产物缺少视频或音轨")
        if abs(output_info["duration"] - duration) > 0.15:
            fail(f"混音产物时长异常：{output_info['duration']:.3f}s vs {duration:.3f}s")
        if chapter["video_frames"] and output_info["video_frames"] != chapter["video_frames"]:
            fail("混音产物视频帧数与原片不同")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    status = "MIXED_MOCK" if mock else "MIXED_UNREVIEWED" if unreviewed else "MIXED_IMPORTED_AUDIO"
    result = {"chapter_number": chapter["number"], "status": status,
              "approved_for_bgm": False,
              "original_video": str(source), "output_video": str(target), "cues": inputs,
              "duration_seconds": output_info["duration"]}
    write_json(output_dir / f"chapter_{chapter['number']:02d}_mix_record.json", result)
    return result


def mix(args):
    manifest = read_json(args.manifest)
    media_root = Path(manifest["media_root"]).resolve(strict=True)
    output_dir = Path(args.out).resolve()
    if output_dir == media_root or output_dir.is_relative_to(media_root):
        fail("混音输出目录不能在生产媒体目录内")
    connection = sqlite3.connect(Path(manifest["db_read_only"]).as_uri() + "?mode=ro", uri=True)
    try:
        for chapter in manifest["chapters"]:
            current = connection.execute(
                "SELECT final_video FROM chapters WHERE id=? AND novel_id=?",
                (chapter["id"], manifest["novel_id"]),
            ).fetchone()
            if not current or current[0] != chapter["source_video_url"]:
                fail(f"第 {chapter['number']} 章当前成片已变更，请重新 prepare")
    finally:
        connection.close()
    selected = set(args.chapters or [chapter["number"] for chapter in manifest["chapters"]])
    available = {chapter["number"] for chapter in manifest["chapters"]}
    if selected - available:
        fail("所选章节不在 manifest 中")
    results = [mix_one(chapter, args.audio_dir, args.out, args.allow_mock, args.force)
               for chapter in manifest["chapters"] if chapter["number"] in selected]
    write_json(Path(args.out) / "mix_summary.json", {"novel_id": manifest["novel_id"], "chapters": results})
    for result in results:
        print(f"第 {result['chapter_number']} 章：{result['status']} {result.get('output_video', '')}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="只读 DB 与媒体，生成小说快照和 YuE2 交接单")
    prep.add_argument("--novel-id", default=DEFAULT_NOVEL_ID)
    prep.add_argument("--db", default=str(BACKEND / "novelflow.db"))
    prep.add_argument("--media-root", default=str(BACKEND / "user_story"))
    prep.add_argument("--cue-spec", default=str(HERE / "cues_yao.json"))
    prep.add_argument("--out", required=True)
    prep.set_defaults(action=prepare)
    mock = commands.add_parser("mock-generate", help="用测试音模拟 YuE2 输出，不调用模型")
    mock.add_argument("--manifest", required=True)
    mock.add_argument("--out", required=True)
    mock.add_argument("--force", action="store_true")
    mock.set_defaults(action=mock_generate)
    render = commands.add_parser("mix", help="导入 cue_id.wav，保留视频及原声并叠加音乐")
    render.add_argument("--manifest", required=True)
    render.add_argument("--audio-dir", required=True)
    render.add_argument("--out", required=True)
    render.add_argument("--chapters", nargs="*", type=int)
    render.add_argument("--allow-mock", action="store_true")
    render.add_argument("--force", action="store_true")
    render.set_defaults(action=mix)
    args = parser.parse_args(argv)
    try:
        args.action(args)
    except (OSError, KeyError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
