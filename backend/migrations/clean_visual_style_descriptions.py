"""Clean exact current visual-style copies from authoritative Shot data.

Run from the repository root:
  python backend/migrations/clean_visual_style_descriptions.py --database backend/novelflow.db
  python backend/migrations/clean_visual_style_descriptions.py --database backend/novelflow.db --apply

The first invocation is a read-only preview. The apply invocation makes a
SQLite backup before changing descriptions and synchronizing the three affected
system prompt templates. Historical AI responses and generated prompts remain
untouched because they are records of completed work, not visual-state inputs.
"""

import argparse
import json
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app.services.visual_style_authority import strip_embedded_visual_style  # noqa: E402


TEMPLATES = {
    ("chapter_split", "章节分镜导演解析"): "05_NovelFlow_VideoDirector_ShotDirector_V1.txt",
    ("keyframe_planner", "关键帧时间轴规划"): "08_NovelFlow_VideoDirector_KeyframePlanner_V2_3Frame4Frame.txt",
    ("keyframe_transition", "关键帧过渡规划"): "10_NovelFlow_KeyframeTransition_Planner_V1.txt",
}


def clean_entries(entries, field, label, style, counts):
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get(field), str):
            continue
        before = entry[field]
        after = strip_embedded_visual_style(before, style)
        if before != after:
            entry[field] = after
            counts[label] += 1


def report_unmatched(entries, field, label, shot_id, reason, unmatched):
    if not isinstance(entries, list):
        return
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        text = entry.get(field)
        if isinstance(text, str) and ("style, high quality, detailed" in text or "##STYLE##" in text):
            unmatched.append({
                "shot_id": shot_id,
                "field": f"{label}[{index}]",
                "reason": reason,
            })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db_path = args.database.resolve(strict=True)
    if db_path.name != "novelflow.db":
        parser.error("database must explicitly name novelflow.db")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    changes = []
    counts = Counter()
    unmatched = []
    template_updates = []
    try:
        default_style_row = connection.execute(
            "SELECT template FROM prompt_templates WHERE type='style' AND is_system=1 "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        fallback_style = default_style_row["template"] if default_style_row else "anime style, high quality, detailed"
        style_by_novel = {}
        explicit_style_novels = set()
        for row in connection.execute(
            "SELECT n.id, n.style_prompt_template_id, p.template AS style "
            "FROM novels n LEFT JOIN prompt_templates p ON p.id = n.style_prompt_template_id"
        ):
            style_by_novel[row["id"]] = row["style"] or fallback_style
            if row["style"]:
                explicit_style_novels.add(row["id"])

        for row in connection.execute(
            "SELECT s.id, c.novel_id, s.description, s.keyframes, s.video_director_plan "
            "FROM shots s JOIN chapters c ON c.id = s.chapter_id"
        ):
            style = style_by_novel.get(row["novel_id"])
            description = strip_embedded_visual_style(row["description"] or "", style)
            keyframes = json.loads(row["keyframes"] or "[]")
            plan = json.loads(row["video_director_plan"] or "{}")
            before_keyframes = json.dumps(keyframes, ensure_ascii=False)
            before_plan = json.dumps(plan, ensure_ascii=False)
            clean_entries(keyframes, "description", "shot.keyframes[].description", style, counts)
            clean_entries(plan.get("keyframes"), "description", "plan.keyframes[].description", style, counts)
            clean_entries(plan.get("transitions"), "transition_description", "plan.transitions[].transition_description", style, counts)
            if description != (row["description"] or ""):
                counts["shot.description"] += 1
            reason = (
                "style differs from current fallback visual_style"
                if row["novel_id"] not in explicit_style_novels
                else "unrecognized description style block"
            )
            if "style, high quality, detailed" in description or "##STYLE##" in description:
                unmatched.append({"shot_id": row["id"], "field": "shot.description", "reason": reason})
            report_unmatched(keyframes, "description", "shot.keyframes", row["id"], reason, unmatched)
            report_unmatched(plan.get("keyframes"), "description", "plan.keyframes", row["id"], reason, unmatched)
            report_unmatched(
                plan.get("transitions"), "transition_description", "plan.transitions",
                row["id"], reason, unmatched,
            )
            if (description != (row["description"] or "")
                    or json.dumps(keyframes, ensure_ascii=False) != before_keyframes
                    or json.dumps(plan, ensure_ascii=False) != before_plan):
                changes.append((description, json.dumps(keyframes, ensure_ascii=False),
                                json.dumps(plan, ensure_ascii=False), row["id"]))

        for (template_type, name), filename in TEMPLATES.items():
            rows = connection.execute(
                "SELECT id, template FROM prompt_templates WHERE type=? AND name=? AND is_system=1",
                (template_type, name),
            ).fetchall()
            if len(rows) != 1:
                raise RuntimeError(f"expected one system template for {template_type}/{name}, found {len(rows)}")
            content = (BACKEND / "prompt_templates" / filename).read_text(encoding="utf-8")
            if rows[0]["template"] != content:
                template_updates.append((content, rows[0]["id"]))

        print(json.dumps({
            "mode": "apply" if args.apply else "preview",
            "database": str(db_path),
            "shots_changed": len(changes),
            "description_fields_cleaned": dict(counts),
            "system_templates_to_sync": len(template_updates),
            "unmatched": unmatched,
        }, ensure_ascii=False, indent=2))
        if not args.apply:
            return

        backup_file = tempfile.NamedTemporaryFile(
            prefix="novelflow_visual_style_backup_", suffix=".db", delete=False,
        )
        backup_path = Path(backup_file.name)
        backup_file.close()
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        print(f"backup: {backup_path}")

        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "UPDATE shots SET description=?, keyframes=?, video_director_plan=? WHERE id=?", changes,
        )
        connection.executemany("UPDATE prompt_templates SET template=? WHERE id=?", template_updates)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
