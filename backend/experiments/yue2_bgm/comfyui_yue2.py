#!/usr/bin/env python3
"""One-cue-at-a-time YuE2 ComfyUI trial with a model-planned instrumental score."""

import argparse
import hashlib
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from experiment import BACKEND, all_cues, probe, read_json, write_json

SCORE_TOOLS = Path(__file__).resolve().parent / "third_party" / "yue2_score"
sys.path.insert(0, str(SCORE_TOOLS))
from abc_tools import parse_abc  # noqa: E402
from compile_score import compile_events  # noqa: E402
from instrumentalize import convert_score, section_starts  # noqa: E402


class ComfyClient:
    def __init__(self, host):
        self.host = host.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path, *, timeout=30):
        with self.opener.open(self.host + path, timeout=timeout) as response:
            return json.load(response)

    def submit(self, graph, path):
        queue = self.get("/queue", timeout=15)
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise ValueError("ComfyUI 队列已有任务，本实验暂不插队")
        write_json(path.with_name(path.stem + "_request.json"), {"prompt": graph})
        body = {"prompt": graph, "client_id": "codex-yue2-bgm-" + uuid.uuid4().hex}
        request = urllib.request.Request(
            self.host + "/prompt", data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with self.opener.open(request, timeout=30) as response:
            result = json.load(response)
        write_json(path.with_name(path.stem + "_submission.json"), result)
        if result.get("node_errors") or not result.get("prompt_id"):
            raise ValueError(f"ComfyUI 拒绝工作流：{result.get('node_errors')}")
        return result["prompt_id"]

    def wait(self, prompt_id, path, *, deadline=900):
        until = time.monotonic() + deadline
        next_notice = time.monotonic() + 30
        while time.monotonic() < until:
            history = self.get("/history/" + prompt_id, timeout=20).get(prompt_id)
            if history:
                write_json(path.with_name(path.stem + "_history.json"), history)
                status = history.get("status") or {}
                if status.get("status_str") != "success":
                    raise ValueError(f"ComfyUI 任务失败：{status.get('messages', [])[-2:]}")
                return history
            if time.monotonic() >= next_notice:
                print(f"等待 ComfyUI 任务 {prompt_id}...", flush=True)
                next_notice += 30
            time.sleep(3)
        raise TimeoutError(f"ComfyUI 任务超时；prompt_id={prompt_id}，可在 history 中继续核查")

    def fetch_audio(self, file_record, destination):
        query = urllib.parse.urlencode(file_record)
        temporary = destination.with_name("." + destination.name + ".download")
        try:
            with self.opener.open(self.host + "/view?" + query, timeout=120) as response:
                with temporary.open("wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def configured_host(db_path):
    db = Path(db_path).resolve(strict=True)
    connection = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT comfyui_host FROM system_configs WHERE id='default'").fetchone()
    finally:
        connection.close()
    if not row or not row[0].startswith(("http://", "https://")):
        raise ValueError("产品数据库没有有效的 ComfyUI 地址")
    return row[0]


def loader():
    return {"class_type": "YuE2ModelLoader", "inputs": {
        "backend": "torch-eager", "memory_budget_gib": 23.5, "offload_ar": True,
        "nar_attention": "sdpa", "nar_query_chunk_size": 256,
    }}


def style_for(cue):
    return ("Instrumental music only; no singing, no vocals, no spoken voice, no choir. " +
            cue["style"].strip().rstrip(".") +
            ", original instrumental film underscore, restrained dynamics.")


def plan_graph(style, seed):
    return {"1": loader(), "2": {"class_type": "YuE2PlanSong", "inputs": {
        "model": ["1", 0], "style": style, "lyrics": "[instrumental]",
        "cot": "full", "seed": seed, "abc": "",
    }}, "3": {"class_type": "ShowTextNode", "inputs": {"text": ["2", 1]}},
        "4": {"class_type": "ShowTextNode", "inputs": {"text": ["2", 2]}}}


def instrumental_excerpt(original, needed_seconds):
    converted, transfer = convert_score(original)
    score = parse_abc(converted)
    voice, instrument = score.voices["Vocal"], score.voices["Ins"]
    bars = voice.bars
    selected = next((i for i in range(1, len(bars) + 1)
                     if float((bars[i][0] if i < len(bars) else voice.time) * 60 / score.bpm)
                     >= needed_seconds + 4), None)
    if selected is None:
        raise ValueError("模型规划的乐谱不够长，无法覆盖 Cue 与安全余量")
    cutoff = bars[selected][0] if selected < len(bars) else voice.time
    sections = section_starts(converted, score)
    events_bars = []
    for index, (start, _, meter) in enumerate(bars[:selected]):
        key = next(value for at, value in reversed(voice.keys) if at <= start)
        item = {"meter": f"{meter[0]}/{meter[1]}", "key": key}
        if start in sections:
            item["section"] = sections[start]
        events_bars.append(item)
    expected_notes = [(at, pitch, min(length, cutoff - at))
                      for at, pitch, length in instrument.notes if at < cutoff]
    events = {"bpm": score.bpm, "key": voice.keys[0][1], "bars": events_bars,
              "notes": [[str(at), str(length), pitch] for at, pitch, length in expected_notes],
              "chords": [[str(at), symbol] for at, symbol in voice.chords if at < cutoff]}
    short, _ = compile_events(events)
    checked = parse_abc(short)
    if checked.voices["Vocal"].notes or not checked.voices["Ins"].notes:
        raise ValueError("转谱后仍有人声声部音符，或器乐声部为空")
    if [tuple(note) for note in checked.voices["Ins"].notes] != expected_notes:
        raise ValueError("短段乐谱未精确保留模型规划的音符与节奏")
    nominal = float(checked.voices["Ins"].time * 60 / checked.bpm)
    if nominal < needed_seconds + 4:
        raise ValueError("短段乐谱时长不足")
    record = {"source_bars": len(bars), "selected_bars": selected,
              "source_nominal_seconds": transfer["nominal_seconds"],
              "excerpt_nominal_seconds": nominal,
              "vocal_notes_before": transfer["vocal_notes_before"],
              "vocal_notes_after": len(checked.voices["Vocal"].notes),
              "instrumental_notes": len(checked.voices["Ins"].notes),
              "transfer": transfer}
    return converted, short, record


def render_graph(style, score, seed, cue_id):
    mode = "full" if parse_abc(score).voices["Vocal"].chords else "melody"
    return {"1": loader(), "2": {"class_type": "YuE2GenerateSong", "inputs": {
        "model": ["1", 0], "style": style, "lyrics": "[instrumental]", "cot": mode,
        "seed": seed, "cfg_scale": 1.0, "candidates": 1, "abc": score,
    }}, "3": {"class_type": "SaveAudio", "inputs": {
        "audio": ["2", 0], "filename_prefix": "audio/yue2_bgm_" + cue_id + "_" + uuid.uuid4().hex[:8],
    }}, "4": {"class_type": "ShowTextNode", "inputs": {"text": ["2", 2]}}}


def run_cue(client, cue, output, audio_dir, seed):
    cue_id = cue["id"]
    job_dir = output / cue_id
    if job_dir.exists() or (audio_dir / f"{cue_id}.flac").exists():
        raise ValueError(f"{cue_id} 已有实验输出，不自动覆盖或重算")
    job_dir.mkdir(parents=True)
    style = style_for(cue)
    plan_id = client.submit(plan_graph(style, seed), job_dir / "plan")
    planned = client.wait(plan_id, job_dir / "plan")
    original = planned["outputs"]["3"]["text"][0]
    metadata = json.loads(planned["outputs"]["4"]["text"][0])
    if metadata.get("result", {}).get("truncated"):
        raise ValueError("YuE2 乐谱规划被截断")
    (job_dir / "original_score.abc").write_text(original, encoding="utf-8")
    converted, short, check = instrumental_excerpt(original, cue["duration_seconds"])
    (job_dir / "converted_full_score.abc").write_text(converted, encoding="utf-8")
    (job_dir / "instrumental_excerpt.abc").write_text(short, encoding="utf-8")
    write_json(job_dir / "score_check.json", check)
    graph = render_graph(style, short, seed, cue_id)
    render_id = client.submit(graph, job_dir / "render")
    rendered = client.wait(render_id, job_dir / "render")
    file_record = rendered["outputs"]["3"]["audio"][0]
    result = json.loads(rendered["outputs"]["4"]["text"][0])
    if result.get("result", {}).get("partial") or result.get("result", {}).get("truncated", {}).get("semantic"):
        raise ValueError("YuE2 音频生成不完整")
    target = audio_dir / f"{cue_id}.flac"
    client.fetch_audio(file_record, target)
    measured = probe(target)
    if not measured["has_audio"] or measured["duration"] < cue["duration_seconds"] + 0.5:
        raise ValueError(f"YuE2 音频时长不足：{measured['duration']:.2f}s")
    overlong = measured["duration"] > 2 * check["excerpt_nominal_seconds"]
    record = {"cue_id": cue_id,
              "status": "generated_overlong_unreviewed" if overlong else "generated_unreviewed",
              "approved_for_bgm": False,
              "vocal_review_status": "score_passed_audio_pending",
              "duration_anomaly": overlong,
              "plan_prompt_id": plan_id, "render_prompt_id": render_id,
              "source": "YuE2 ComfyUI", "seed": seed,
              "style": style, "lyrics": graph["2"]["inputs"]["lyrics"],
              "score_check": check, "audio_path": str(target),
              "audio_seconds": measured["duration"],
              "audio_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "review_required": "人工听检人声残留、音乐性、环境声和对白可懂度"}
    write_json(job_dir / "result.json", record)
    print(f"{cue_id}: YuE2 音频 {measured['duration']:.2f}s -> {target}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cue-ids", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--audio-dir", required=True)
    parser.add_argument("--seed", type=int, default=20261025)
    args = parser.parse_args()
    manifest = read_json(args.manifest)
    media_root = Path(manifest["media_root"]).resolve(strict=True)
    output = Path(args.out).resolve()
    audio_dir = Path(args.audio_dir).resolve()
    if output.is_relative_to(media_root) or audio_dir.is_relative_to(media_root):
        raise ValueError("实验文件不能写入生产媒体目录")
    if not 0 <= args.seed < 2**63:
        raise ValueError("seed 超出 YuE2 节点允许范围")
    cues = {cue["id"]: cue for cue in all_cues(manifest)}
    if len(set(args.cue_ids)) != len(args.cue_ids) or set(args.cue_ids) - set(cues):
        raise ValueError("Cue ID 重复或不在 manifest 中")
    output.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    client = ComfyClient(configured_host(manifest["db_read_only"]))
    for cue_id in args.cue_ids:
        run_cue(client, cues[cue_id], output, audio_dir, args.seed)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, TimeoutError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
