# Obligations

A reviewer fills in a company profile and sees which obligations apply, why, and which an expert reviewed or flagged. `explain_rule()` in Postgres decides, not a model.

## Sub-features

- `obl-default` shows the default profile (construction, 350 workers).
- `obl-profile` changes the profile and the obligations that apply.
- `obl-labels` shows "đã duyệt bởi …" and "cần xem lại" with its reason.
- `obl-bad-input` keeps working when `n` is not a number.

## How to get to it (user POV)

- Open the **Nghĩa vụ & rule engine** tab (`/obligations`), change the form, and choose **Áp dụng**.

## Driving it with verify.py

Preconditions:

- `$V doctor` reports `doctor: OK` on a fresh seed.

- **Default profile.** Run `$V get /obligations --slug obl-default`. Status 200. Both `VERIFY-ND1-01` and `VERIFY-ND1-02` show "Áp dụng". `VERIFY-ND1-01` shows "đã duyệt bởi chi" and "cần xem lại".
- **Small company.** Run `$V get "/obligations?sector=xd&n=20&role=contractor" --slug obl-small`. `VERIFY-ND1-01` (needs 50 or more workers) shows "N/A". `VERIFY-ND1-02` still shows "Áp dụng".
- **Other sector.** Run `$V get "/obligations?sector=det&n=350" --slug obl-sector`. `VERIFY-ND1-01` shows "N/A".
- **Bad input.** Run `$V get "/obligations?n=abc" --slug obl-bad-input`. Status 200, and the form shows 350.

## Gotchas

- The checkbox defaults apply only when `n` is absent from the URL. Once `n` is present, an unchecked box is off.
- Only obligations with `sources` show. The page counts the old sample rows without sources but hides them.
