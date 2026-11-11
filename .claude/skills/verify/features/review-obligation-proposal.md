# Review an obligation proposal

A reviewer opens obligations drafted by agent01, reads each one next to the text of its cited clauses, ticks **Loại** on the ones to leave out, and approves the rest. A statement the verifier could not find in the source shows in red.

## Sub-features

- `op-page` shows each draft beside its sources, with verifier flags.
- `op-exclude` approves while leaving out ticked obligations.
- `op-unknown-id` refuses an excluded id that is not in the proposal.

## How to get to it (user POV)

- Open the **Chờ duyệt** tab (`/proposals`) and choose proposal 2.
- Tick **Loại** on an obligation, type a note, and choose **Duyệt — nạp các nghĩa vụ không bị tick Loại**.

## Driving it with verify.py

Preconditions:

- A fresh seed: proposal 2 is pending.

- **Page.** Run `$V get /proposals/2 --slug op-page`. The text shows `ND1-26-A01` and `ND1-26-A02`, the source text "mỗi lần ít nhất 16 giờ", and for A02 "Không có trong căn cứ: trong vòng 30 ngày".
- **Unknown id.** Run `$V review 2 approved --exclude ND1-26-A99 --slug op-unknown-id`. The status line is `-> 400` and the page text names `ND1-26-A99`. `$V sql "SELECT status FROM load_proposals WHERE id=2"` still returns `pending`.
- **Exclude and approve.** Run `$V review 2 approved --exclude ND1-26-A02 --note "verify: loại A02" --slug op-exclude`. The status line is `-> 303 Location: /proposals/2`.
- **Proof.** Run `$V sql "SELECT status, reviewed_by, excluded, review_note FROM load_proposals WHERE id=2"`. It returns `approved | verify | ["ND1-26-A02"] | verify: loại A02`.
- **Decided.** Run `$V get /proposals/2 --slug op-decided`. The text shows "Đã duyệt — chờ nạp bởi verify … · loại 1 nghĩa vụ" and "đã loại" on A02.

## Gotchas

- Run the unknown-id step before the approval. After the approval the form is gone and the helper stops with "no form token".
- The app decides how to record exclusions from the proposal's stored kind. A form field cannot change it.
