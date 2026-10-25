"""Export A/C review evidence without changing the frozen A artifacts."""
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from run import C, ROOT, OUTPUT, read, save, sha

REVIEW = C / "review"
SOURCES = {"A": ROOT / "output/optimized_original_duration.mp4", "C": OUTPUT}


def ffmpeg(args):
    result = subprocess.run(["ffmpeg", "-hide_banner", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result


def main():
    assert not (REVIEW / "frame_manifest.json").exists(), "Preserve an existing evidence export"
    REVIEW.mkdir(exist_ok=True)
    events = read(C / "canonical_dialogue.json")
    per_event = {}
    for e in events:
        start, end = e["start_time"] + 0.15, e["end_time"] - 0.15
        per_event[e["dialogue_id"]] = [round(start + (end - start) * i / 5, 4) for i in range(6)]
    anchors = [0, 4.95, 13, 13.4]
    old_cuts = [164 / 24, 165 / 24, 224 / 24, 225 / 24]
    indices = sorted({round(t * 24) for times in per_event.values() for t in times} |
                     {round(t * 24) for t in anchors + old_cuts})
    manifest, scenes, clips = {}, {}, []
    select = "+".join(f"eq(n,{index})" for index in indices)
    for name, source in SOURCES.items():
        target = REVIEW / "frames" / name
        target.mkdir(parents=True, exist_ok=True)
        ffmpeg(["-v", "error", "-i", str(source), "-vf", f"select='{select}'",
                "-fps_mode", "vfr", "-q:v", "2", "-threads", "2", str(target / "%03d.jpg")])
        produced = sorted(target.glob("*.jpg"))
        assert len(produced) == len(indices)
        manifest[name] = {str(index): {"path": str(path), "native_frame": index, "pts_seconds": index / 24}
                          for index, path in zip(indices, produced)}
    save("review/frame_manifest.json", {"fps": 24, "native_frame_indices_zero_based": True,
                                       "event_requested_sample_times": per_event, "frames": manifest})

    def frame(name, time):
        return Image.open(manifest[name][str(round(time * 24))]["path"]).convert("RGB")

    # Per-event sequences retain every selected full frame; no face crops or ASR inference.
    for event, times in per_event.items():
        for name in SOURCES:
            sheet = Image.new("RGB", (3 * 864, 2 * 512), "#eeeeee")
            draw = ImageDraw.Draw(sheet)
            for i, t in enumerate(times):
                x, y = (i % 3) * 864, (i // 3) * 512
                sheet.paste(frame(name, t), (x, y + 32))
                draw.text((x + 12, y + 9), f"{name} / {event} / frame {round(t * 24)} / PTS {round(t * 24) / 24:.6f}s", fill="black")
            sheet.save(REVIEW / f"{name}_{event}_sequence.jpg", quality=94)

    for label, t, picture in [("KF1", 0, 1), ("KF2", 4.95, 2), ("KF3", 13, 3)]:
        sheet = Image.new("RGB", (3 * 864, 592), "#eeeeee")
        draw = ImageDraw.Draw(sheet)
        images = [Image.open(ROOT / f"inputs/picture_{picture:02d}.png").convert("RGB"), frame("A", t), frame("C", t)]
        for i, (name, im) in enumerate(zip(["Reference (contained; no crop)", "A", "C"], images)):
            contained = ImageOps.contain(im, (864, 560))
            sheet.paste(contained, (i * 864 + (864 - contained.width) // 2, 32 + (560 - contained.height) // 2))
            draw.text((i * 864 + 12, 9), f"{label} / {name} / requested {t}s", fill="black")
        sheet.save(REVIEW / f"{label}_reference_A_C.jpg", quality=94)

    sheet = Image.new("RGB", (2 * 864, len(old_cuts) * 512), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for row, t in enumerate(old_cuts):
        for col, name in enumerate(SOURCES):
            sheet.paste(frame(name, t), (col * 864, row * 512 + 32))
            draw.text((col * 864 + 12, row * 512 + 9), f"{name} / native frame {round(t * 24)} / PTS {t:.6f}s", fill="black")
    sheet.save(REVIEW / "previous_baseline_cut_boundaries_A_C.jpg", quality=94)

    decode = ffmpeg(["-v", "error", "-xerror", "-i", str(OUTPUT), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"])
    save("review/decode_check.json", {"source": str(OUTPUT), "sha256": sha(OUTPUT), "exit_code": decode.returncode,
                                     "stderr": decode.stderr, "video_and_audio_fully_decoded": True})
    scene = ffmpeg(["-i", str(OUTPUT), "-vf", "select='gt(scene,0.2)',showinfo", "-an", "-f", "null", "-"])
    (REVIEW / "C_scene_detection.log").write_text(scene.stderr)
    candidates = [float(t) for t in re.findall(r"\bn:\s*\d+\s+pts:\s*\d+\s+pts_time:([\d.]+)", scene.stderr)]
    scenes = {"A": read(ROOT / "review/scene_detection.json")["optimized_original_duration"],
              "C": {"exit_code": scene.returncode, "threshold": 0.2, "candidate_times_seconds": candidates,
                    "limitation": "No scene-score candidates is not proof that no camera cut exists."}}
    save("review/scene_detection.json", scenes)
    finish()


def finish():
    events = read(C / "canonical_dialogue.json")
    clips = []
    indices = read(REVIEW / "frame_manifest.json")["frames"]["C"]
    candidates = read(REVIEW / "scene_detection.json")["C"]["candidate_times_seconds"]
    embedded = json.loads(read(C / "media_probe.json")["format"]["tags"]["prompt"])
    submitted = read(C / "comfyui/workflow.json")
    normalized = json.loads(json.dumps(embedded))
    cache_fields = []
    for asset in read(ROOT / "baseline/input_assets.json"):
        node = asset["workflow_node_id"]
        assert embedded[node]["is_changed"] == [asset["original_sha256"]]
        assert "is_changed" not in submitted[node]
        cache_fields.append({"node": node, "field": "is_changed", "value": embedded[node]["is_changed"],
                             "matches_original_reference_sha256": True})
        del normalized[node]["is_changed"]
    initial = REVIEW / "embedded_workflow_check.json"
    if initial.exists() and not (REVIEW / "embedded_workflow_initial_check.json").exists():
        (REVIEW / "embedded_workflow_initial_check.json").write_bytes(initial.read_bytes())
    save("review/embedded_workflow_check.json", {
        "raw_metadata_graph_matches_submission": embedded == submitted,
        "matches_actual_submitted_C_graph_after_cache_metadata_removal": normalized == submitted,
        "only_metadata_difference": "ComfyUI adds nine LoadImage is_changed reference SHA256 cache fingerprints to embedded MP4 metadata.",
        "added_cache_fingerprints": cache_fields,
        "history_graph_matches_submission": read(C / "comfyui/history.json")[read(C / "comfyui/execution.json")["prompt_id"]]["prompt"][2] == submitted,
    })
    assert normalized == submitted

    # Padded clips are review derivatives. Their windows do not assert actual speech timing.
    for e in events:
        begin, finish = max(0, e["start_time"] - 0.2), min(13.666667, e["end_time"] + 0.2)
        paths = {}
        for name, source in SOURCES.items():
            destination = REVIEW / "clips" / f"{name}_{e['dialogue_id']}.mp4"
            destination.parent.mkdir(exist_ok=True)
            ffmpeg(["-v", "error", "-ss", str(begin), "-i", str(source), "-t", str(finish - begin),
                    "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264", "-threads", "2", "-crf", "18",
                    "-c:a", "aac", "-b:a", "160k", "-map_metadata", "-1", str(destination)])
            paths[name] = str(destination)
        clips.append({"event": e["dialogue_id"], "canonical_speaker": e["subject"], "exact_dialogue": e["text"],
                      "canonical_start": e["start_time"], "canonical_end": e["end_time"],
                      "review_source_start": begin, "review_source_end": finish,
                      "canonical_start_within_review_clip": 0.2,
                      "audio": "original soundtrack re-encoded as AAC; no muting or voice changes",
                      "actual_speech_timing_verified": False, "paths": paths})
    save("review/dialogue_clip_manifest.json", clips)
    ffmpeg(["-v", "error", "-i", str(SOURCES["A"]), "-i", str(OUTPUT),
            "-filter_complex", "[0:v][1:v]hstack=inputs=2[v]", "-map", "[v]", "-an",
            "-c:v", "libx264", "-threads", "2", "-crf", "20", "-map_metadata", "-1", str(REVIEW / "A_C_comparison_silent.mp4")])
    save("review/evidence_export.json", {"complete": True, "full_frames_per_video": len(indices),
                                        "dialogue_clips_with_audio": len(clips) * 2, "llm_calls": 0,
                                        "comparison_left": "A", "comparison_right": "C", "comparison_audio": False})
    print(json.dumps({"frames_per_video": len(indices), "C_scene_candidates": candidates,
                      "decode": "PASS", "embedded_graph": "PASS", "clips_with_audio": len(clips) * 2}))


if __name__ == "__main__":
    finish() if sys.argv[1:] == ["finish"] else main()
