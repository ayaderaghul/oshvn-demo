import json, re

FIELDS = [("sector", "Ngành", "select"), ("n", "Số lao động", "number"), ("role", "Vai trò trong dự án", "role"),
          ("strict", "Có thiết bị nghiêm ngặt", "bool"), ("hazardous", "Có việc nặng nhọc, độc hại", "bool"),
          ("kcn", "Công trình trong KCN", "bool"), ("main", "Nhà thầu chính có thầu phụ", "bool"),
          ("danger", "Vùng nguy hiểm vượt ngoài công trường", "bool"), ("lease_in", "Dùng lao động thuê lại", "bool"),
          ("lease_out", "Là DN cho thuê lại", "bool"), ("elderly", "Dùng người cao tuổi việc nặng", "bool"),
          ("state", "Tập đoàn / TCT nhà nước", "bool"), ("selftrain", "Tự huấn luyện ATVSLĐ", "bool")]


SECTORS = {"xd": ("Thi công công trình xây dựng", 1, 0), "kl": ("Sản xuất kim loại", 1, 1), "hc": ("Sản xuất hóa chất", 1, 1),
           "det": ("Dệt, may, da, giày", 0, 1), "vlxd": ("Sản xuất vật liệu xây dựng", 0, 1), "khac": ("Ngành khác", 0, 0)}


LABEL = {f: l for f, l, _ in FIELDS} | {"g36": "Ngành thuộc Điều 36 khoản 1 NĐ 39", "g37": "Ngành thuộc Điều 37 khoản 1 NĐ 39"}


def nice(reason):
    for k, v in sorted(LABEL.items(), key=lambda x: -len(x[0])):
        reason = re.sub(rf"^{k}\b", v, reason)
    reason = (reason.replace('"contractor"', "nhà thầu").replace('"owner"', "chủ đầu tư").replace('"none"', "không tham gia XD")
              .replace("applies to every employer", "áp dụng cho mọi người sử dụng lao động"))
    for en, vi in (("needs", "cần"), ("true", "có"), ("false", "không")):
        reason = re.sub(rf"\b{en}\b", vi, reason)
    return reason


def penalty_label(p):
    if not isinstance(p, dict): return str(p)
    return (f"Đ{p.get('dieu', '?')}" + (f" k{p['khoan']}" if p.get("khoan") is not None else "") + f": {p.get('text', '')}")


# ---------------------------------------------------------------- obligations proposals (agent01)
OPS_VI = {"=": "=", "!=": "≠", ">=": "≥", "<": "<", "<=": "≤", "in": "thuộc"}


def rule_text(r):
    """applies_when → plain Vietnamese, e.g. 'n ≥ 50 VÀ (Ngành thi công xây dựng HOẶC …)'."""
    if not isinstance(r, dict): return "?"
    if r.get("always"): return "mọi doanh nghiệp"
    if "all" in r: return " VÀ ".join(f"({rule_text(x)})" if ("any" in x) else rule_text(x) for x in r["all"])
    if "any" in r: return " HOẶC ".join(rule_text(x) for x in r["any"])
    if "not" in r: return f"KHÔNG ({rule_text(r['not'])})"
    f, op, v = r.get("field"), r.get("op"), r.get("value")
    name = LABEL.get(f, f)
    if v is True and op == "=": return name
    if v is False and op == "=": return f"không: {name}"
    return f"{name} {OPS_VI.get(op, op)} {json.dumps(v, ensure_ascii=False)}"


def src_label(s):
    return f"{s[0]} Điều {s[1]}" + (f" khoản {s[2]}" if s[2] is not None else "")
