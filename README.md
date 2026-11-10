# OSHVN demo web

Trang xem dữ liệu trong Neon, chỉ đọc. FastAPI một file, chạy trên Render miễn phí.

- `/` danh sách văn bản · `/doc/{id}` Điều › Khoản · `/search?q=` tìm từ khóa · `/obligations` rule engine · `/runs` nhật ký nạp
- Biến môi trường (đặt trong Render dashboard, không ghi vào code):
  - `DATABASE_URL`: chuỗi kết nối Neon của role chỉ đọc `oshvn_web`
  - `APP_PASSWORD`: mật khẩu xem trang (tên đăng nhập gõ gì cũng được)

Chạy thử trên máy: `pip install -r requirements.txt`, đặt hai biến trên, rồi `uvicorn app:app --reload`.

## Known issues

Các lỗi dưới đây được tìm thấy khi review toàn bộ `app.py` (ngày 2026-11-10) và chưa được sửa. Mức độ:

- **Cao**: người dùng thấy dữ liệu sai hoặc thiếu mà không có dấu hiệu nào.
- **Trung bình**: lỗ hổng bảo mật cần điều kiện để khai thác, lỗi 500, hoặc kết quả sai trong trường hợp hẹp.
- **Thấp**: ảnh hưởng nhỏ, hoặc tài liệu lệch với code.

### Lỗi về tính đúng và bảo mật

| Mức độ | File | Lỗi |
|---|---|---|
| Cao | `app.py` `Index.ensure` | Chỉ mục BM25 của `/ask` chỉ dựng lại khi `count(*)` hoặc `max(id)` của `chunks` đổi. `loader.py apply` cập nhật khoản đổi chữ tại chỗ, nên hai giá trị này giữ nguyên. `/ask` tiếp tục hiện và gửi cho model chữ cũ tới khi app khởi động lại. Bước kiểm số so trên cùng chữ cũ nên vẫn đạt. |
| Cao | `app.py` `obligations` | Cột `reviewed` được SELECT nhưng không dùng. Trang không phân biệt nghĩa vụ chuyên gia đã duyệt với bản nháp của model. Nghĩa vụ đã duyệt mà bước kiểm chứng của agent01 gắn cờ vẫn có `needs_review = true`, nên hiện "cần xem lại" giống hệt nghĩa vụ chưa ai xem. |
| Cao | `app.py` `ask` | Lọc theo văn bản (`doc`) chạy sau khi đã lấy 40 kết quả BM25 và 30 kết quả vector trên mọi văn bản. Văn bản không nằm trong nhóm đầu toàn cục cho kết quả "Không tìm thấy khoản nào", dù văn bản đó có khoản khớp. |
| Trung bình | `app.py` `obligation_proposal`, `document`, `search`, `ask`, `proposals` | Một số giá trị được chèn vào HTML mà không qua `E()`: `dieu` và `khoan` của mức phạt trong bản nháp agent01 (do model sinh, hiện cả với bản nháp bị loại), số Điều lấy từ `locator` trong thuộc tính `id` và `href`, và trạng thái không có trong `STATUS_VI`. Văn bản luật chứa lệnh chèn vào prompt có thể biến các chỗ này thành XSS trên trang duyệt. |
| Trung bình | `app.py` `page` | App không gửi `X-Frame-Options`, CSP `frame-ancestors` hay `X-Content-Type-Options`. Một trang khác có thể nhúng `/proposals/{id}` vào iframe và phủ lên nút **Duyệt** khi trình duyệt đã lưu mật khẩu Basic. |
| Trung bình | `app.py` `auth` | Cả team dùng chung một `APP_PASSWORD`, không giới hạn số lần thử sai. Tên đăng nhập do người dùng tự gõ và được ghi làm `reviewed_by`, tức là dấu "chuyên gia đã duyệt" trong bảng `obligations`. Ký tự vô hình như U+200B vẫn qua kiểm tra "phải có tên". |
| Trung bình | `app.py` `review` | Mã nghĩa vụ gửi từ ô **Loại** không khớp `[A-Za-z0-9.\-]{1,40}` bị bỏ qua mà không báo, nên nghĩa vụ đó vẫn được duyệt. Mã không có trong payload cũng được nhận. Mã agent01 hiện dùng (`ND44-16-A01`) khớp mẫu. |
| Trung bình | `app.py` `review` | Hàm SQL được gọi (`review_proposal` hay `review_proposal_items`) chọn theo trường `items` trong form, không theo `kind` lưu trong database. Một POST không có `items=1` duyệt đề xuất nghĩa vụ mà không loại mục nào. |
| Trung bình | `app.py` `obligations` | `?n=abc` gây lỗi 500. Mức phạt thiếu khóa `dieu` hoặc `khoan` (`p['dieu']`) làm cả trang lỗi 500. Trang cũng giả định `explain_rule` luôn trả object. |
| Trung bình | `app.py` `ask` | Câu trả lời của model sai dạng (`used` không phải danh sách, `answer` hay `not_found` không phải chuỗi, chữ số như `²`) gây lỗi 500 sau khi cuộc gọi đã tính phí và đã tính vào giới hạn. |
| Trung bình | `app.py` `ask`, `ask_claude` | `/ask` gọi Anthropic và Voyage qua GET. Thẻ `<img src="/ask?q=…">` ở trang khác dùng hết `ASK_LIMIT_PER_HOUR` (mặc định 60) bằng mật khẩu đã lưu của trình duyệt. `ASK_LOG` nằm trong bộ nhớ một process, mất khi khởi động lại, không chia sẻ giữa các worker, và kiểm rồi ghi không nguyên tử. |
| Trung bình | `app.py` `Index` | `ensure` có thể dựng lại hai lần cùng lúc khi nhiều request đến lúc khởi động. `search` không khóa, nên trong lúc dựng lại có thể đọc `rows` mới với `tf` cũ, gây `IndexError` hoặc trả nhầm khoản. |
| Trung bình | `app.py` `review`, `db` | `review` gọi `psycopg.connect` đồng bộ bên trong hàm `async`, nên chặn mọi request khi Neon đang khởi động. Kết nối này không bật read-only, nên giới hạn duy nhất là quyền của role `oshvn_web`. `SET default_transaction_read_only` theo session có thể không giữ được qua pooler của Neon. |
| Thấp | `app.py` `vector_search` | Lỗi database ở bước tìm vector (ví dụ sai số chiều) không được bắt và gây lỗi 500, dù lỗi HTTP của Voyage được xử lý. |
| Thấp | `app.py` `ask` | Kiểm số chỉ xem con số có xuất hiện đâu đó trong khoản được dẫn hay không. Số viết bằng chữ không được kiểm. Câu trả lời không dẫn khoản nào và không có chữ số thì không có cảnh báo. |
| Thấp | `app.py` `nice` | Thay `needs`, `true`, `false` ở mọi vị trí trong chuỗi lý do của `explain_rule`, kể cả bên trong từ khác. |
| Thấp | `app.py` `proposal` | `?err=` không giới hạn độ dài. Chữ tùy ý hiện trong khung thông báo của trang duyệt. |
| Thấp | `app.py` `document`, `proposal` | `doc_id` hoặc `pid` lớn hơn 2^31 gây lỗi 500. |
| Thấp | `app.py` `ask` | Một request `/ask` giữ một luồng tới 90 giây (Anthropic) cộng 30 giây (Voyage). `/healthz` dùng chung nhóm luồng đó. |

### Khả năng bảo trì

| Mức độ | File | Lỗi |
|---|---|---|
| Cao | `app.py` | Mỗi route tự khai `dependencies=[Depends(auth)]`. Route mới quên dòng này sẽ công khai. |
| Cao | `app.py` | HTML dựng bằng f-string, escape bằng tay với `E()` ở khoảng 150 chỗ. Các lỗi XSS ở bảng trên đến từ đây. |
| Cao | `app.py` | Một file chứa truy cập dữ liệu, dựng HTML, CSS, tìm kiếm BM25 và vector, client LLM, CSRF và giới hạn tần suất. Repo không có test hay CI. |
| Trung bình | `app.py` | Hợp đồng với `oshvn_loader` không được ghi ở đâu: khóa JSON của `payload` và `report` (`_verify`, `_amended_by`, `texts`, `checks`, `agent`…), tên trạng thái, cột `kind` và `excluded`, và chuỗi tiếng Việt `"mới"` mà app dùng để rẽ nhánh. Hàng được đọc theo chỉ số tuple (`r[0]`…`r[16]`). Truy cập `x['key']` trực tiếp làm cả trang danh sách lỗi 500 khi loader đổi một khóa. |
| Trung bình | `app.py` `proposals`, `proposal`, `review` | Các kiểm tra `to_jsonb(lp)->>'kind'` và `to_regclass('public.load_proposals')` lặp ở nhiều truy vấn để chạy được trên database chưa migrate. Rẽ nhánh theo `kind` nằm ở ba chỗ. |
| Trung bình | `app.py` `db` | Mỗi truy vấn mở một kết nối mới tới Neon, không có pool. `/ask` mở hai kết nối và giữ một kết nối suốt cuộc gọi Voyage. `review` không dùng `db()` nên bỏ qua kiểm tra thiếu `DATABASE_URL`. |
| Trung bình | `app.py` `ask_claude` | Một hàm đọc biến môi trường, giới hạn tần suất, dựng prompt, gọi HTTP và tách JSON. Prompt chứa một quy tắc pháp lý viết cứng (mức phạt tổ chức gấp 2 lần theo NĐ 283/2026). Kiểm số và kiểm khoản dẫn nằm trong route `ask`, không tách được ra để test. |
| Trung bình | `app.py` `search`, `ask` | `/search` dùng full-text của Postgres, `/ask` dùng BM25 viết bằng Python cộng pgvector. Chú thích ghi hai bên dùng cùng cách tìm, điều này sai. Kết quả "19/20 câu hỏi NĐ 39" không có bộ câu hỏi nào trong repo. |
| Trung bình | `app.py` `obligations`, `rule_text` | `FIELDS`, `SECTORS`, `OPS_VI` và cách dịch `applies_when` chép lại lược đồ hồ sơ doanh nghiệp do `oshvn_loader` và `explain_rule` định nghĩa. |
| Thấp | `app.py` | Khoảng 60 thuộc tính `style=` inline, chặn việc dùng CSP chặt. Chuỗi `CSS` được gửi lại trong mọi trang. |
| Thấp | `app.py` | Điều kiện `source_kind='legal_article' AND NOT coalesce(retired,false)` lặp ở khoảng 10 truy vấn. Truy vấn đoạn trích của `/search` chép hai lần. |
| Thấp | `app.py` `documents`, `proposals`, `runs` | `/` tính tổng trên cả bảng `chunks` mỗi lần mở trang. `/proposals` cắt ở 100 dòng và `/runs` ở 50 dòng mà không báo. Thời gian hiện không kèm múi giờ. |
| Thấp | `app.py` | `urllib.error` được dùng mà không import, chỉ chạy được vì `urllib.request` đã nạp nó. Câu `LIKE 'x%%'` không có tham số chạy đúng nhờ trùng hợp. |
| Thấp | `render.yaml`, `README.md` | `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `ASK_MODEL`, `ASK_LIMIT_PER_HOUR`, `ASK_API_BASE` và `VOYAGE_API_BASE` không có trong `render.yaml`, nên dựng lại service sẽ mất cấu hình. README vẫn ghi "chỉ đọc" và "tên đăng nhập gõ gì cũng được", không nhắc `/ask`, `/proposals` hay yêu cầu Python 3.12. |
