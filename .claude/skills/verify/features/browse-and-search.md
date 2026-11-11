# Browse and search

A reviewer sees every loaded document with its clause, appendix, and vector counts, opens one document as Chương › Điều › Khoản with its check results and load history, and searches clause text by keyword without accents mattering.

## Sub-features

- `doc-list` lists documents with counts on the **Văn bản** tab.
- `doc-page` shows one document's clauses, checks, and proposal history.
- `search` finds clauses by keyword and highlights the match.

## How to get to it (user POV)

- Open the **Văn bản** tab (`/`) and choose a document number.
- Open the **Tìm kiếm** tab (`/search`), type words, and choose **Tìm**.

## Driving it with verify.py

Preconditions:

- `$V doctor` reports `doctor: OK` on a fresh seed.

- **List.** Run `$V get / --slug doc-list`. Status 200, and the text lists `1/2026/NĐ-CP` with 3 điều and 5 khoản.
- **Document.** Run `$V get /doc/1 --slug doc-page`. Status 200. The text has the Chương headings "QUY ĐỊNH CHUNG" and "HUẤN LUYỆN", the clause "mỗi lần ít nhất 16 giờ", the check pills "ĐẠT · Điều liên tục 1..N", and the history section with proposals 1 and 3.
- **Search.** Run `$V get "/search?q=huấn luyện" --slug search`. Status 200, the text starts the results with "kết quả", and the `.html` wraps the matching words in `<mark>`.
- **Search without accents.** Run `$V get "/search?q=huan luyen" --slug search-no-accents`. The same clauses come back.

## Gotchas

- In Git Bash, a path without `MSYS_NO_PATHCONV=1` reaches the helper as a Windows path and the helper stops with an error.
- A document links from the list only when it has at least one clause.
