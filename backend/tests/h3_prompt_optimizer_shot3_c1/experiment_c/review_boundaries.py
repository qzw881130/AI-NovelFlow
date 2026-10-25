"""Confirm the two detected C discontinuities using adjacent native frames."""
import subprocess
from PIL import Image, ImageDraw
from run import C, ROOT, OUTPUT, read, save

review = C / "review"
candidates = read(review / "scene_detection.json")["C"]["candidate_times_seconds"]
after = [round(t * 24) for t in candidates]
indices = sorted({n for point in after for n in [point - 1, point]})
manifest = {"zero_based_native_frames": True, "fps": 24, "cuts": []}
for name, source in [("A", ROOT / "output/optimized_original_duration.mp4"), ("C", OUTPUT)]:
    destination = review / "native_boundaries" / name
    destination.mkdir(parents=True, exist_ok=True)
    assert not list(destination.glob("*.jpg"))
    select = "+".join(f"eq(n,{index})" for index in indices)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-vf", f"select='{select}'",
                    "-fps_mode", "vfr", "-q:v", "2", "-threads", "2", str(destination / "%03d.jpg")], check=True)
    assert len(list(destination.glob("*.jpg"))) == len(indices)
for point in after:
    sheet = Image.new("RGB", (1728, 1024), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    paths = {}
    for row, index in enumerate([point - 1, point]):
        for col, name in enumerate(["A", "C"]):
            path = review / "native_boundaries" / name / f"{indices.index(index) + 1:03d}.jpg"
            paths[f"{name}_{index}"] = str(path)
            sheet.paste(Image.open(path), (col * 864, row * 512 + 32))
            draw.text((col * 864 + 12, row * 512 + 9), f"{name} / frame {index} / PTS {index / 24:.6f}s", fill="black")
    destination = review / f"native_cut_{point - 1}_{point}_A_C.jpg"
    sheet.save(destination, quality=95)
    manifest["cuts"].append({"before_frame": point - 1, "after_frame": point,
                             "before_pts": (point - 1) / 24, "after_pts": point / 24,
                             "frames": paths, "comparison": str(destination),
                             "candidate_only_until_visual_review": True})
save("review/native_cut_manifest.json", manifest)
print(manifest)
