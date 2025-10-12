from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import sqlite3
from datetime import datetime
import os
from pathlib import Path

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///comments.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db= SQLAlchemy(app)

#model for comments
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False, default='Ẩn danh')
    content = db.Column(db.String(2000), nullable=False)   
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

with app.app_context():
    db.create_all()
# Create the database tables if they don't exist

# DB_PATH = Path("comments.db")

# # Khởi tạo DB nếu chưa có
# def init_db():
#     with sqlite3.connect(DB_PATH) as conn:
#         c = conn.cursor()
#         c.execute(
#             """
#             CREATE TABLE IF NOT EXISTS comments (
#                 id INTEGER PRIMARY KEY AUTOINCREMENT,
#                 name TEXT NOT NULL,
#                 content TEXT NOT NULL,
#                 created_at TEXT NOT NULL
#             )
#             """
#         )
#         conn.commit()


# # Gọi hàm tạo DB
# init_db()

@app.route("/")
def index():
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    return render_template("index.html", comments=comments)

@app.route("/comment", methods=["POST"])
def comment():
    name = request.form.get("name", "Ẩn danh").strip()[:60]
    content = request.form.get("content", "").strip()[:2000]

    if content:
        db.session.add(Comment(name=name, content=content))
        db.session.commit()
    return redirect(url_for("index") + "#binhluan")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
