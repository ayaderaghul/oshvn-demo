# OSHVN demo web

Trang xem dữ liệu trong Neon, chỉ đọc. FastAPI một file, chạy trên Render miễn phí.

- `/` danh sách văn bản · `/doc/{id}` Điều › Khoản · `/search?q=` tìm từ khóa · `/obligations` rule engine · `/runs` nhật ký nạp
- Biến môi trường (đặt trong Render dashboard, không ghi vào code):
  - `DATABASE_URL`: chuỗi kết nối Neon của role chỉ đọc `oshvn_web`
  - `APP_PASSWORD`: mật khẩu xem trang (tên đăng nhập gõ gì cũng được)

Chạy thử trên máy: `pip install -r requirements.txt`, đặt hai biến trên, rồi `uvicorn app:app --reload`.
