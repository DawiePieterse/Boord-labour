"""update_labour_server.bat refuses to restart the server unless the venv can
import its dependencies. That list has to be this app's requirements, no more
and no fewer: v1.0 shipped with two of Boord Owner's libraries in it, so every
update on the farm stopped there with a healthy server."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_updater_import_check_matches_requirements():
    with open(os.path.join(ROOT, "backend", "requirements.txt"), encoding="utf-8") as fh:
        required = {re.split(r"[\[=<>]", line.strip())[0].lower()
                    for line in fh if line.strip() and not line.startswith("#")}
    with open(os.path.join(ROOT, "update_labour_server.bat"), encoding="utf-8") as fh:
        checked = re.search(r'-c "import ([a-z_, ]+)"', fh.read()).group(1)
    assert {m.strip() for m in checked.split(",")} == required
