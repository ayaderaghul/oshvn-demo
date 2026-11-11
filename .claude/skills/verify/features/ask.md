# Hỏi đáp

A reviewer asks a question in Vietnamese. The app finds the matching clauses by keyword and by meaning, Claude answers only from them with numbered citations, and the app warns about a citation or a number that the clauses do not support.

## Sub-features

- `ask-form` shows the form without calling any model.
- `ask-answer` answers with citations from the fused search.
- `ask-warning` warns about a number that no cited clause has.
- `ask-doc-filter` limits the search to one document.

## How to get to it (user POV)

- Open the **Hỏi đáp** tab (`/ask`), type a question, optionally choose a document, and choose **Hỏi**.

## Driving it with verify.py

Preconditions:

- `$V doctor` reports `doctor: OK`. `$V calls` shows how many model calls happened so far.

- **Form only.** Run `$V get "/ask?q=huấn luyện" --slug ask-form`. Status 200, and `$V calls` shows no new call.
- **Answer.** Run `$V ask "huấn luyện an toàn bao lâu một lần?" --slug ask-answer`. Status 200. The text has "Trả lời", "Theo [1]:", "Cách tìm: từ khóa (BM25) + theo nghĩa (verify-fake)", and the numbered clauses. `$V calls` shows one `/v1/embeddings` and one `/v1/messages` call.
- **Warning.** Run `$V ask "huấn luyện SAI SỐ" --slug ask-warning`. The text has "Con số không có trong các khoản được dẫn: 99".
- **Document filter.** Run `$V ask "huấn luyện" --doc "1/2026/NĐ-CP" --slug ask-doc`. Only clauses of that document are listed.

## Gotchas

- The answers come from the fake Claude, so they prove the app's handling, not real answer quality.
- `ASK_LIMIT_PER_HOUR` (default 60) applies per run. Many questions in one run can reach it.
