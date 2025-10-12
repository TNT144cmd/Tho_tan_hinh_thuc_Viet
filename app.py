from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime
from pathlib import Path


app = Flask(__name__)
DB_PATH = Path("comments.db")


# Khởi tạo DB nếu chưa có
def init_db():
with sqlite3.connect(DB_PATH) as conn:
c = conn.cursor()
c.execute(
"""
CREATE TABLE IF NOT EXISTS comments (
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT NOT NULL,
content TEXT NOT NULL,
created_at TEXT NOT NULL
)
"""
)
conn.commit()


init_db()


@app.route("/")
def index():
with sqlite3.connect(DB_PATH) as conn:
c = conn.cursor()
c.execute("SELECT name, content, created_at FROM comments ORDER BY id DESC")
comments = [
{"name": row[0], "content": row[1], "created_at": row[2]} for row in c.fetchall()
]
return render_template("index.html", comments=comments)


@app.route("/comment", methods=["POST"])
def comment():
name = request.form.get("name", "Ẩn danh").strip()[:60]
content = request.form.get("content", "").strip()[:2000]
if content:
with sqlite3.connect(DB_PATH) as conn:
c = conn.cursor()
c.execute(
"INSERT INTO comments(name, content, created_at) VALUES (?, ?, ?)",
(name or "Ẩn danh", content, datetime.utcnow().isoformat(timespec="seconds"))
)
conn.commit()
return redirect(url_for("index") + "#binhluan")


if __name__ == "__main__":
app.run(host="0.0.0.0", port=5000, debug=True)