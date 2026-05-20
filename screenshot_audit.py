"""Take screenshots of all pages for visual design review.

Runs a temporary Flask server without auth guard so we can capture
every page without needing BIT login credentials.
"""
import os, sys, time, tempfile, threading
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent / "app" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(str(BACKEND_ROOT))

TEST_TEMP_DIR = tempfile.TemporaryDirectory(prefix="screenshot-audit-")
os.environ["DB_PATH"] = str(Path(TEST_TEMP_DIR.name) / "feature3.db")
os.environ["FEATURE3_ENABLE_WORKER"] = "0"
os.environ["FEATURE3_AUTO_AI_ANSWER"] = "0"

from app import app
from modules.shared.db import init_db

init_db()

# Remove auth guard for screenshot access
app.before_request_funcs[None] = [
    f for f in app.before_request_funcs.get(None, [])
    if not getattr(f, "__name__", "").startswith("require_")
]

screenshot_dir = Path(__file__).resolve().parent / "screenshots"
screenshot_dir.mkdir(exist_ok=True)

PORT = 5099

def run_server():
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)

t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(2)

from playwright.sync_api import sync_playwright

BASE = f"http://127.0.0.1:{PORT}"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    pages = [
        ("01-login", "/login"),
        ("02-index", "/"),
        ("03-chat", "/chat"),
        ("04-place", "/place"),
        ("05-freshman", "/freshman"),
        ("06-senior", "/senior"),
    ]

    for idx, (name, path) in enumerate(pages, 1):
        print(f"[{idx}/{len(pages)}] Screenshot: {name} ({path})")
        try:
            page.goto(f"{BASE}{path}", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=10000)
            page.screenshot(path=str(screenshot_dir / f"{name}.png"), full_page=True)
        except Exception as exc:
            print(f"  WARN: {exc}")

    browser.close()

print(f"\nAll screenshots saved to {screenshot_dir}/")
for f in sorted(screenshot_dir.glob("*.png")):
    print(f"  {f.name} ({f.stat().st_size:,} bytes)")
