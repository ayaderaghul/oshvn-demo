"""Source checks ruff cannot express: where HTML may be written and where escaping may be turned off."""
import ast
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SAFE_ALLOWED = {("base.html", "label|safe")}
TAG = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9]*(\s[^<>]*)?/?>")


def strings(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


class Structure(unittest.TestCase):
    def test_templates_do_not_turn_off_escaping(self):
        found = []
        for path in sorted((APP / "templates").glob("*.html")):
            for m in re.finditer(r"([\w.]+)\s*\|\s*safe\b", path.read_text(encoding="utf-8")):
                if (path.name, re.sub(r"\s", "", m.group(0))) not in SAFE_ALLOWED:
                    found.append(f"{path.name}: {m.group(0)}")
        self.assertEqual(found, [], "|safe renders the value unescaped. Return markupsafe.Markup from a helper in "
                                   "app/views.py that escapes the text itself, or let autoescape handle it.")

    def test_routers_hold_no_html(self):
        found = []
        for path in sorted((APP / "routers").glob("*.py")):
            for line, s in strings(ast.parse(path.read_text(encoding="utf-8"))):
                # ts_headline's StartSel/StopSel, which views.mark turns back into tags after escaping
                if TAG.search(s.replace("<mark>", "").replace("</mark>", "")):
                    found.append(f"{path.name}:{line}: {s[:60]!r}")
        self.assertEqual(found, [], "Routers fetch data and pick a template. Put the markup in app/templates/.")


if __name__ == "__main__":
    unittest.main()
