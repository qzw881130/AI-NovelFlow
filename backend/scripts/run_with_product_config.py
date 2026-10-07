"""Bootstrap an independent product/evidence script without FastAPI startup.

Usage (backend cwd): python scripts/run_with_product_config.py SCRIPT [ARGS...]
No task is created by this bootstrap; it only reads canonical ComfyUI config.
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from app.core.config import initialize_product_comfyui_config
    if len(sys.argv) < 2:
        raise SystemExit('Usage: run_with_product_config.py SCRIPT [ARGS...]')
    # Missing product config raises before running any evidence/task code.
    initialize_product_comfyui_config()
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    runpy.run_path(script, run_name='__main__')


if __name__ == '__main__':
    main()
