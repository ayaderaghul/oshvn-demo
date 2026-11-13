from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined
from markupsafe import Markup

from app import views
from app.rules import nice, penalty_label, rule_text, src_label
from app.security import csrf_token

HERE = Path(__file__).parent

templates = Jinja2Templates(directory=HERE / "templates", autoescape=True, undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
templates.env.globals |= {
    "css": Markup((HERE / "static" / "style.css").read_text(encoding="utf-8")),
    "status_vi": views.STATUS_VI, "verdict_vi": views.VERDICT_VI,
    "csrf_token": csrf_token, "word_diff": views.word_diff,
}
templates.env.filters |= {"mark": views.mark, "nice": nice, "penalty_label": penalty_label, "rule_text": rule_text, "src_label": src_label}
