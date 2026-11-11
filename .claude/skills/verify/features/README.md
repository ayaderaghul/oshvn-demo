# oshvn-demo verification map

This directory is the maintained source for verifying what a reviewer can do in oshvn-demo. Read this index before driving, then use the matching feature file as the recipe.

## Baseline preconditions

- A live run from `$V up` with `$V doctor` reporting `doctor: OK`. `V` and `MSYS_NO_PATHCONV=1` are set as in `../SKILL.md`.
- The database holds only the seed: document 1, obligations `VERIFY-ND1-01` and `VERIFY-ND1-02`, proposals 1 (pending documents), 2 (pending obligations), and 3 (applied).
- A review changes the seed. Start a fresh run (`$V down`, `$V up`) when a recipe needs a pending proposal that an earlier recipe decided.
- Never drive an app or database that `verify.py up` did not start.

## Driving conventions

- Open pages with `$V get`, submit forms with `$V review` and `$V ask`, and send negative cases with `$V raw`.
- Read state with `$V sql` and model calls with `$V calls`.
- Give every step a `--slug` that names the feature and the step.

## Proof and skip reporting

- A page proof is the saved `.txt` (status line and text) and `.html`.
- A form proof is the `303` or error status, then a `$V sql` view of the row it changed, then the page opened again.
- Record the feature ID and the entry point with every artifact.
- Report a step that could not run with the command and the unmet precondition. Do not report it as passed through another path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph on what the reviewer sees. Then exactly four H2 sections, in this order: `Sub-features`, `How to get to it (user POV)`, `Driving it with verify.py`, and `Gotchas`.

## Features

- [Browse and search](./browse-and-search.md) covers the document list, one document, and keyword search.
- [Obligations](./obligations.md) covers the rule engine page, the profile form, and the review labels.
- [Review a document proposal](./review-document-proposal.md) covers the review page, approve, reject, and a decided proposal.
- [Review an obligation proposal](./review-obligation-proposal.md) covers excluding single obligations and the checks on excluded ids.
- [Hỏi đáp](./ask.md) covers asking a question, the answer checks, and the document filter.
- [Login and request checks](./login-and-request-checks.md) covers the password, the login throttle, and cross-site posts.
