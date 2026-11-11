# Review a document proposal

A reviewer opens a law-text proposal from agent00 or `loader.py propose`, reads its checks, the word-by-word diff, the agent's comment, and the parsed text, then approves or rejects it. Approving writes no law text; `loader.py apply` does that later.

## Sub-features

- `dp-list` shows the proposal on the **Chờ duyệt** tab.
- `dp-page` shows checks, the diff, agent00 notes, parser notes, and the full text.
- `dp-approve` and `dp-reject` record the decision.
- `dp-decided` shows the decision and no form once the proposal is no longer pending.

## How to get to it (user POV)

- Open the **Chờ duyệt** tab (`/proposals`) and choose proposal 1.
- On the proposal page, type a note and choose **Duyệt — cho phép nạp** or **Từ chối**.

## Driving it with verify.py

Preconditions:

- A fresh seed: proposal 1 is pending.

- **List.** Run `$V get /proposals --slug dp-list`. Proposal 1 shows "Chờ duyệt", "0 mới / 1 đổi / 0 ngừng", and the agent00 verdict "cần xem kỹ".
- **Page.** Run `$V get /proposals/1 --slug dp-page`. The text has "Nhận xét của agent00", "1. Kiểm tra tự động", "2. Thay đổi so với database (1)", and the `.html` has `<del>hằng năm, mỗi lần ít nhất 16 giờ.</del>`-style markup around the changed words.
- **Reject.** Run `$V review 1 rejected --note "verify: từ chối" --slug dp-reject`. The status line is `POST /proposals/1/review -> 303 Location: /proposals/1`.
- **Proof.** Run `$V sql "SELECT status, reviewed_by, review_note FROM load_proposals WHERE id=1"`. It returns `rejected | verify | verify: từ chối`.
- **Decided.** Run `$V get /proposals/1 --slug dp-decided`. The page shows "Từ chối bởi verify" and has no form. `$V review 1 approved` stops with "no form token on /proposals/1".
- **Approve.** On a fresh run, `$V review 1 approved --slug dp-approve` and the same query returns `approved`.

## Gotchas

- Proposal 3 is applied in the seed, so it shows the read-only decision panel from the start.
- The reviewer name is the Basic-auth user name, `verify` for the helper. An empty or blank-looking name redirects with `?err=name`.
