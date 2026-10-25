"""Generate reproducible visual comparison evidence from both actual videos."""
import json
import re
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
results = {}
for name in ['baseline', 'optimized_original_duration']:
    source = ROOT / 'output' / f'{name}.mp4'
    proc = subprocess.run([
        'ffmpeg', '-hide_banner', '-i', str(source), '-vf', "select='gt(scene,0.2)',showinfo",
        '-an', '-f', 'null', '-'
    ], capture_output=True, text=True)
    (ROOT / 'review' / f'{name}_scene_detection.log').write_text(proc.stderr)
    candidates = [float(t) for t in re.findall(r'\bn:\s*\d+\s+pts:\s*\d+\s+pts_time:([\d.]+)', proc.stderr)]
    results[name] = {'exit_code': proc.returncode, 'threshold': 0.2, 'candidate_times_seconds': candidates,
                     'limitation': 'Scene-score candidates indicate abrupt visual changes; not independent proof of a camera cut.'}
(ROOT / 'review/scene_detection.json').write_text(json.dumps(results, indent=2))
times = [0, 1.625, 3.7, 4.95, 6.65, 7.5, 8.35, 8.85, 9.55, 10.175, 11.5, 12, 13, 13.4]
contact = Image.new('RGB', (1728, len(times) * 520), '#eeeeee')
draw = ImageDraw.Draw(contact)
for row, t in enumerate(times):
    for col, name in enumerate(['baseline', 'optimized_original_duration']):
        dest = ROOT / 'review' / 'side_by_side_frames' / f'{name}_{t:.3f}.jpg'
        dest.parent.mkdir(exist_ok=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(t), '-i', str(ROOT / 'output' / f'{name}.mp4'),
                        '-frames:v', '1', '-q:v', '2', '-y', str(dest)], check=True)
        im = Image.open(dest)
        contact.paste(im, (col * 864, row * 520 + 32))
        draw.text((col * 864 + 10, row * 520 + 8), f'{name} / {t:.3f}s', fill='black')
contact.save(ROOT / 'review/side_by_side_contact_sheet.jpg', quality=90)
# Silent review derivative; original audio remains intact in both original outputs.
target = ROOT / 'review/comparison_silent.mp4'
assert not target.exists(), 'Preserve an existing comparison artifact'
subprocess.run([
    'ffmpeg', '-v', 'error', '-i', str(ROOT / 'output/baseline.mp4'),
    '-i', str(ROOT / 'output/optimized_original_duration.mp4'),
    '-filter_complex', '[0:v][1:v]hstack=inputs=2[v]', '-map', '[v]', '-an',
    '-c:v', 'libx264', '-threads', '4', '-crf', '20', '-pix_fmt', 'yuv420p', str(target)
], check=True)
print(json.dumps(results, indent=2))
