# OSHVN demo web

Trang xem dữ liệu trong Neon, chỉ đọc. FastAPI một file, chạy trên Render miễn phí.

- `/` danh sách văn bản · `/doc/{id}` Điều › Khoản · `/search?q=` tìm từ khóa · `/obligations` rule engine · `/runs` nhật ký nạp
- Biến môi trường (đặt trong Render dashboard, không ghi vào code):
  - `DATABASE_URL`: chuỗi kết nối Neon của role chỉ đọc `oshvn_web`
  - `APP_PASSWORD`: mật khẩu xem trang (tên đăng nhập gõ gì cũng được)

Chạy thử trên máy: `pip install -r requirements.txt`, đặt hai biến trên, rồi `uvicorn app:app --reload`.

## Known issues

Lượt review toàn bộ `app.py` ngày 2026-11-10 ghi ở [docs/review-2026-11.md](docs/review-2026-11.md). Các lỗi về tính đúng và bảo mật đã sửa ngày 2026-11-11 (nhánh `fix/review-2026-11`), trừ những phần còn mở dưới đây. Mức độ:

- **Cao**: người dùng thấy dữ liệu sai hoặc thiếu mà không có dấu hiệu nào, hoặc database ghi được ngoài ý muốn.
- **Trung bình**: lỗ hổng bảo mật cần điều kiện để khai thác, lỗi 500, hoặc kết quả sai trong trường hợp hẹp.
- **Thấp**: ảnh hưởng nhỏ, hoặc tài liệu lệch với code.

Chạy test: `pip install -r requirements.txt httpx`, rồi `python -m unittest discover -s tests`. Test trang cần Docker: chúng tự dựng một Postgres tạm từ `tests/fixtures/schema.sql` rồi xóa đi.

### Lỗi về tính đúng và bảo mật còn mở

| Mức độ | File | Lỗi |
|---|---|---|
| Cao | Neon, role `oshvn_web` | Role mà app dùng là thành viên của `neon_superuser`: có INSERT, UPDATE, DELETE trên mọi bảng, cùng CREATEROLE và BYPASSRLS (kiểm ngày 2026-11-11). App chỉ đọc nhờ mỗi transaction mở bằng `BEGIN READ ONLY`, và chỉ ghi qua `review_proposal()` và `review_proposal_items()`. Cần bỏ role khỏi `neon_superuser` và chỉ cấp SELECT cùng EXECUTE hai hàm đó. |
| Trung bình | `app.py` `auth` | Cả team vẫn dùng chung một `APP_PASSWORD`. Tên đăng nhập do người dùng tự gõ được ghi làm `reviewed_by`. Đã có giới hạn 10 lần sai trong 15 phút cho mỗi địa chỉ và bỏ ký tự vô hình khỏi tên, nhưng chưa chứng minh được ai đã duyệt. |
| Trung bình | `app.py` `ask_claude` | Bộ đếm `ASK_LIMIT_PER_HOUR` nằm trong bộ nhớ của một process. Nó mất khi khởi động lại và không chia sẻ giữa các worker. |
| Thấp | `app.py` `auth` | Khóa giới hạn đăng nhập là mục cuối của `X-Forwarded-For`, tức địa chỉ do proxy của Render thêm vào. Chạy app không có proxy phía trước thì client tự chọn được khóa này. |
| Thấp | `app.py` `check_answer` | Số viết bằng chữ ("hai mươi người") không được kiểm. |
| Thấp | `app.py` `ask` | Một câu hỏi giữ một luồng tới 60 giây (Claude) cộng 15 giây (Voyage). |
| Thấp | `app.py` `Index` | Khi loader chỉ đổi vị trí của khoản (tên chương, đường dẫn) mà không đổi chữ, `load_run_id` không đổi, nên `/ask` hiện vị trí cũ tới lần nạp sau. |

### Khả năng bảo trì

| Mức độ | File | Lỗi |
|---|---|---|
| Cao | `app.py` | HTML dựng bằng f-string, escape bằng tay với `E()` ở khoảng 150 chỗ. Các lỗi XSS của lượt review đến từ đây. |
| Cao | `app.py` | Một file chứa truy cập dữ liệu, dựng HTML, CSS, tìm kiếm BM25 và vector, client LLM, CSRF và giới hạn tần suất. Đã có test trong `tests/`, chưa có CI. |
| Trung bình | `app.py` | Hợp đồng với `oshvn_loader` không được ghi ở đâu: khóa JSON của `payload` và `report` (`_verify`, `_amended_by`, `texts`, `checks`, `agent`…), tên trạng thái, cột `kind` và `excluded`, và chuỗi tiếng Việt `"mới"` mà app dùng để rẽ nhánh. Hàng được đọc theo chỉ số tuple (`r[0]`…`r[16]`). Truy cập `x['key']` trực tiếp làm cả trang danh sách lỗi 500 khi loader đổi một khóa. |
| Trung bình | `app.py` `proposals`, `proposal`, `review` | Các kiểm tra `to_jsonb(lp)->>'kind'` và `to_regclass('public.load_proposals')` lặp ở nhiều truy vấn để chạy được trên database chưa migrate. Rẽ nhánh theo `kind` nằm ở ba chỗ. |
| Trung bình | `app.py` `db` | Mỗi truy vấn mở một kết nối mới tới Neon, không có pool. `/ask` mở hai hoặc ba kết nối. |
| Trung bình | `app.py` `ask_claude` | Một hàm đọc biến môi trường, giới hạn tần suất, dựng prompt, gọi HTTP và tách JSON. Prompt chứa một quy tắc pháp lý viết cứng (mức phạt tổ chức gấp 2 lần theo NĐ 283/2026). Kiểm số và kiểm khoản dẫn nằm trong route `ask`, không tách được ra để test. |
| Trung bình | `app.py` `search`, `ask` | `/search` dùng full-text của Postgres, `/ask` dùng BM25 viết bằng Python cộng pgvector. Chú thích ghi hai bên dùng cùng cách tìm, điều này sai. Kết quả "19/20 câu hỏi NĐ 39" không có bộ câu hỏi nào trong repo. |
| Trung bình | `app.py` `obligations`, `rule_text` | `FIELDS`, `SECTORS`, `OPS_VI` và cách dịch `applies_when` chép lại lược đồ hồ sơ doanh nghiệp do `oshvn_loader` và `explain_rule` định nghĩa. |
| Thấp | `app.py` | Khoảng 60 thuộc tính `style=` inline, chặn việc dùng CSP chặt. Chuỗi `CSS` được gửi lại trong mọi trang. |
| Thấp | `app.py` | Điều kiện `source_kind='legal_article' AND NOT coalesce(retired,false)` lặp ở khoảng 10 truy vấn. Truy vấn đoạn trích của `/search` chép hai lần. |
| Thấp | `app.py` `documents`, `proposals`, `runs` | `/` tính tổng trên cả bảng `chunks` mỗi lần mở trang. `/proposals` cắt ở 100 dòng và `/runs` ở 50 dòng mà không báo. Thời gian hiện không kèm múi giờ. |
| Thấp | `render.yaml`, `README.md` | `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `ASK_MODEL`, `ASK_LIMIT_PER_HOUR`, `ASK_API_BASE` và `VOYAGE_API_BASE` không có trong `render.yaml`, nên dựng lại service sẽ mất cấu hình. README vẫn ghi "chỉ đọc" và "tên đăng nhập gõ gì cũng được", không nhắc `/ask`, `/proposals` hay yêu cầu Python 3.12. |
