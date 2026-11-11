-- Verification scaffolding: a small, realistic data set for driving oshvn-demo. Loaded by verify.py up into a
-- fresh database built from tests/fixtures/schema.sql, so ids are predictable: document 1, proposals 1-3.
BEGIN;
INSERT INTO load_runs(kind, status, created_by, report) VALUES
  ('documents', 'applied', 'verify', '{"file": "nd1-2026.docx", "chunks": {"new": 5, "changed": 0, "unchanged": 0, "retired": 0}}');

INSERT INTO legal_documents(number, type, title_vi, status, source_file, parser_version, load_run_id, check_report) VALUES
  ('1/2026/NĐ-CP', 'decree', 'Quy định thử nghiệm về huấn luyện an toàn, vệ sinh lao động', 'to_verify', 'nd1-2026.docx',
   'parse_law@2026-11-05', 1,
   '[{"name": "Điều liên tục 1..N, không thiếu/trùng", "ok": true, "detail": "3 điều"},
     {"name": "Độ phủ: chữ từ Điều 1 đến hết Điều cuối được xếp vào điều khoản", "ok": true, "detail": "100.0%"}]');

-- five clauses; every one has a vector of the (fake) Voyage model the verify Voyage stand-in answers with
INSERT INTO chunks(source_kind, document_id, locator, text, text_sha256, load_run_id, embedding, embedding_model)
SELECT 'legal_article', 1, loc::jsonb, txt, 'seed', 1, array_fill(0.1::real, ARRAY[1024])::vector, 'voyage:verify-fake'
FROM (VALUES
  ('{"doc": "1/2026/NĐ-CP", "dieu": 1, "khoan": 1, "kind": "khoan", "seq": 0, "dieu_title": "Phạm vi điều chỉnh", "chuong": "I", "chuong_title": "QUY ĐỊNH CHUNG", "ref": "Điều 1, khoản 1"}',
   E'Điều 1. Phạm vi điều chỉnh — Khoản 1\n1. Nghị định này quy định về huấn luyện an toàn, vệ sinh lao động.'),
  ('{"doc": "1/2026/NĐ-CP", "dieu": 1, "khoan": 2, "kind": "khoan", "seq": 0, "dieu_title": "Phạm vi điều chỉnh", "chuong": "I", "chuong_title": "QUY ĐỊNH CHUNG", "ref": "Điều 1, khoản 2"}',
   E'Điều 1. Phạm vi điều chỉnh — Khoản 2\n2. Nghị định này áp dụng cho doanh nghiệp xây dựng có từ 50 lao động trở lên.'),
  ('{"doc": "1/2026/NĐ-CP", "dieu": 2, "khoan": 1, "kind": "khoan", "seq": 0, "dieu_title": "Huấn luyện", "chuong": "II", "chuong_title": "HUẤN LUYỆN", "ref": "Điều 2, khoản 1"}',
   E'Điều 2. Huấn luyện — Khoản 1\n1. Người sử dụng lao động phải tổ chức huấn luyện an toàn hằng năm, mỗi lần ít nhất 16 giờ.'),
  ('{"doc": "1/2026/NĐ-CP", "dieu": 2, "khoan": 2, "kind": "khoan", "seq": 0, "dieu_title": "Huấn luyện", "chuong": "II", "chuong_title": "HUẤN LUYỆN", "ref": "Điều 2, khoản 2"}',
   E'Điều 2. Huấn luyện — Khoản 2\n2. Người lao động phải tham gia đầy đủ các khóa huấn luyện.'),
  ('{"doc": "1/2026/NĐ-CP", "dieu": 3, "khoan": 1, "kind": "khoan", "seq": 0, "dieu_title": "Hiệu lực", "chuong": "II", "chuong_title": "HUẤN LUYỆN", "ref": "Điều 3, khoản 1"}',
   E'Điều 3. Hiệu lực — Khoản 1\n1. Nghị định này có hiệu lực từ ngày 01 tháng 01 năm 2026.')
) AS v(loc, txt);

INSERT INTO obligations(id, document_id, article_ref, category, topic, kind, duty_vi, action_vi, frequency, applies_when, sources,
                        penalties, verification_status, reviewed, reviewed_by, needs_review, review_reason) VALUES
  ('VERIFY-ND1-01', 1, '1/2026/NĐ-CP Điều 2 khoản 1', 'huấn luyện', 'huấn luyện', 'recurring',
   'Tổ chức huấn luyện an toàn cho người lao động hằng năm.', 'Lập kế hoạch và tổ chức huấn luyện.', 'hằng năm',
   '{"all": [{"field": "sector", "op": "=", "value": "xd"}, {"field": "n", "op": ">=", "value": 50}]}',
   '[["1/2026/NĐ-CP", 2, 1]]', '[{"dieu": 25, "khoan": 2, "text": "Phạt tiền từ 5.000.000 đồng đến 10.000.000 đồng"}]',
   'expert_reviewed', true, 'chi', true, 'Căn cứ đã thay đổi khi nạp lại 1/2026/NĐ-CP: Điều 2 khoản 1'),
  ('VERIFY-ND1-02', 1, '1/2026/NĐ-CP Điều 2 khoản 2', 'huấn luyện', 'huấn luyện', 'setup',
   'Người lao động tham gia đầy đủ các khóa huấn luyện.', 'Điểm danh tại mỗi khóa.', NULL,
   '{"always": true}', '[["1/2026/NĐ-CP", 2, 2]]', '[]', 'agent01_draft', false, NULL, false, NULL);

-- proposal 1: a pending document proposal from agent00, with one changed clause
INSERT INTO load_proposals(doc_code, file_name, source_sha256, parser_version, options, payload, report, status, kind, created_by) VALUES
  ('1/2026/NĐ-CP', 'nd1-2026-v2.docx', 'seed-sha-1', 'parse_law@2026-11-05', '{"by": "agent00"}',
   '{"title": "Quy định thử nghiệm về huấn luyện an toàn, vệ sinh lao động", "dtype": "decree",
     "result": {"chunks": [{"dieu": 2, "khoan": 1, "dieu_title": "Huấn luyện", "text": "1. Người sử dụng lao động phải tổ chức huấn luyện an toàn sáu tháng một lần."}]}}',
   '{"document": "đã có, cập nhật", "chunks": {"new": 0, "changed": 1, "unchanged": 4, "retired": 0},
     "checks": [{"name": "Điều liên tục 1..N, không thiếu/trùng", "ok": true, "detail": "3 điều"}],
     "issues": ["Điều 2 khoản 1: unnumbered paragraph kept in khoản — check"],
     "changes": [{"change": "changed", "key": ["2", "1"], "old": "1. Người sử dụng lao động phải tổ chức huấn luyện an toàn hằng năm, mỗi lần ít nhất 16 giờ.",
                  "new": "1. Người sử dụng lao động phải tổ chức huấn luyện an toàn sáu tháng một lần."}],
     "agent": {"verdict": "check", "comment": "Khoản 1 Điều 2 đổi tần suất huấn luyện; đối chiếu với bản gốc.", "route": "parse",
               "steps": ["model chọn: parse — file có chữ"], "agent": "agent00", "provider": "anthropic", "model": "claude-haiku-5-5",
               "calls": 2, "tokens": 1840}}',
   'pending', 'documents', 'verify');

-- proposal 2: a pending obligation proposal from agent01, two drafts, one flagged by the verifier
INSERT INTO load_proposals(doc_code, file_name, source_sha256, parser_version, options, payload, report, status, kind, created_by) VALUES
  ('nghĩa vụ · 1/2026/NĐ-CP', NULL, 'seed-sha-2', 'agent01', '{}',
   '{"obligations": [
      {"id": "ND1-26-A01", "topic": "huấn luyện", "kind": "recurring", "freq": "hằng năm",
       "content": "Tổ chức huấn luyện an toàn hằng năm, mỗi lần ít nhất 16 giờ.", "action": "Lập kế hoạch huấn luyện.",
       "evidence": ["kế hoạch huấn luyện"], "applies_when": {"field": "sector", "op": "=", "value": "xd"},
       "sources": [["1/2026/NĐ-CP", 2, 1]], "penalties": [],
       "_verify": {"unsupported": [], "inferred": []}, "_amended_by": []},
      {"id": "ND1-26-A02", "topic": "huấn luyện", "kind": "setup",
       "content": "Người lao động tham gia đầy đủ các khóa huấn luyện trong vòng 30 ngày.", "action": "Điểm danh.",
       "evidence": ["danh sách điểm danh"], "applies_when": {"always": true},
       "sources": [["1/2026/NĐ-CP", 2, 2]], "penalties": [],
       "_verify": {"unsupported": ["trong vòng 30 ngày"], "inferred": []}, "_amended_by": []}],
     "texts": {"1/2026/NĐ-CP|2|1": "Điều 2. Huấn luyện — Khoản 1\n1. Người sử dụng lao động phải tổ chức huấn luyện an toàn hằng năm, mỗi lần ít nhất 16 giờ.",
               "1/2026/NĐ-CP|2|2": "Điều 2. Huấn luyện — Khoản 2\n2. Người lao động phải tham gia đầy đủ các khóa huấn luyện."}}',
   '{"flagged": 1, "rejected": [], "new_fields": [], "log": ["Điều 2: 2 bản nháp, 2 đạt"],
     "agent": {"agent": "agent01", "draft_model": "claude-sonnet-5-5", "filter_model": "claude-haiku-5-5", "calls": 3, "tokens": 5200}}',
   'pending', 'obligations', 'verify');

-- proposal 3: an applied document proposal, so the history and the read-only decision panel have data
INSERT INTO load_proposals(doc_code, file_name, source_sha256, parser_version, options, payload, report, status, kind, created_by,
                           reviewed_by, reviewed_at, review_note, applied_at, applied_run_id, apply_report) VALUES
  ('1/2026/NĐ-CP', 'nd1-2026.docx', 'seed-sha-3', 'parse_law@2026-11-05', '{}', '{"result": {"chunks": []}}',
   '{"document": "mới", "chunks": {"new": 5, "changed": 0, "unchanged": 0, "retired": 0}, "checks": []}',
   'applied', 'documents', 'verify', 'chi', now(), 'đã đối chiếu', now(), 1, '{"chunks": {"new": 5}}');
COMMIT;
