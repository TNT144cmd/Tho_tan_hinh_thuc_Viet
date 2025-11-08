# app.py
import re
import os
from pathlib import Path
from datetime import datetime, date

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, abort, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# ================== Cấu hình DB ==================
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///comments.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ================== Tiện ích chung ==================
def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s

def pretty_from_slug(slug: str) -> str:
    return slug.replace("-", " ").title() if slug else ""

def title_from_filename_base(base: str) -> str:
    """
    Tạo tiêu đề đẹp từ phần tên file (không xoá ký tự như @, ?, ! ...)
    Ví dụ:
      "@ ERA"        -> "@ Era"
      "can_tro_nho"  -> "Can Tro Nho"
    """
    # thay _ và - bằng khoảng trắng, giữ lại các ký tự khác
    s = re.sub(r"[_\-]+", " ", base).strip()
    if not s:
        return ""
    return s.title()


def to_iso(v):
    """Trả về chuỗi ISO 8601 hoặc None."""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            pass
    return str(v)

def normalize_poem_item(p):
    """
    Chuẩn hoá 1 bài thơ về dict có các key: title, slug, created_at (ISO hoặc None).
    - p có thể là ORM object (Poem) hoặc dict trả từ list_poems_in_folder().
    """
    if hasattr(p, "title") and hasattr(p, "slug"):
        return {
            "title": p.title,
            "slug": p.slug,
            "created_at": to_iso(getattr(p, "created_at", None)),
        }
    return {
        "title": p.get("title"),
        "slug": p.get("slug"),
        "created_at": to_iso(p.get("created_at")),
    }

# ================== Models ==================
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False, default='Ẩn danh')
    content = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class Author(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False)
    bio = db.Column(db.Text, default="")
    poems = db.relationship("Poem", backref="author", lazy=True, cascade="all, delete-orphan")

class Poem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), nullable=False)
    content = db.Column(db.Text, nullable=False)                    # thơ trong database (nếu dùng)
    file_path = db.Column(db.String(255), nullable=True)            # đường dẫn file cũ (không dùng)
    author_id = db.Column(db.Integer, db.ForeignKey("author.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# ================== File system: poem/<author>/<poem_slug>/* ==================
POEMS_DIR = os.path.join(os.path.dirname(__file__), "poem")
os.makedirs(POEMS_DIR, exist_ok=True)

PROFILE_DIR_NAMES = {"tiểu sử", "tieu su", "tieu_su", "tieu-su"}
LANG_SUFFIX_RE = re.compile(r"^(?P<base>.+)_(?P<lang>vi|en)\.txt$", re.IGNORECASE)

def read_text_file(path: str) -> str:
    # utf-8-sig để tự loại BOM, strip() để bỏ dòng trống đầu/cuối
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()

def is_profile_dir(name: str) -> bool:
    n = name.strip().lower()
    return n in PROFILE_DIR_NAMES

def find_poem_files(author_slug: str, poem_slug: str):
    """
    Nhận diện file trong folder poem/<author>/<poem_slug>/ theo mẫu:
      - <base>_vi.txt
      - <base>_en.txt
    Trả về:
      {
        "vi": path|None,
        "en": path|None,
        "title_vi": str|None,
        "title_en": str|None,
        "created_at": datetime|None
      }
    - Chấp nhận base khác nhau giữa VI và EN.
    - Nếu không có *_vi/_en thì fallback vi.txt/en.txt (không có title_lang).
    """
    folder = Path(POEMS_DIR) / author_slug / poem_slug
    out = {
        "vi": None, "en": None,
        "title_vi": None, "title_en": None,
        "created_at": None
    }
    if not folder.exists() or not folder.is_dir():
        return out

    mtimes = []
    # Quét các file *_vi.txt / *_en.txt
    for f in folder.iterdir():
        if not (f.is_file() and f.suffix.lower() == ".txt"):
            continue
        m = LANG_SUFFIX_RE.match(f.name)
        if m:
            lang = m.group("lang").lower()
            base = m.group("base").strip()
            out[lang] = str(f)
            out[f"title_{lang}"] = title_from_filename_base(base)
            try:
                mtimes.append(f.stat().st_mtime)
            except Exception:
                pass

    # Fallback vi.txt / en.txt nếu chưa nhận diện
    if not out["vi"]:
        f_vi = folder / "vi.txt"
        if f_vi.exists():
            out["vi"] = str(f_vi)
            try:
                mtimes.append(f_vi.stat().st_mtime)
            except Exception:
                pass
    if not out["en"]:
        f_en = folder / "en.txt"
        if f_en.exists():
            out["en"] = str(f_en)
            try:
                mtimes.append(f_en.stat().st_mtime)
            except Exception:
                pass

    if mtimes:
        out["created_at"] = datetime.fromtimestamp(max(mtimes))
    else:
        try:
            out["created_at"] = datetime.fromtimestamp(folder.stat().st_mtime)
        except Exception:
            out["created_at"] = None

    return out

def read_lang_file(path: str) -> str:
    """Đọc file ngôn ngữ; nếu không tồn tại hoặc rỗng → trả về chuỗi rỗng."""
    if not path:
        return ""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return ""
    text = read_text_file(str(p))
    return text if text else ""

def read_author_profile(author_slug: str):
    """
    Đọc tiểu sử (tieu_su.txt) và ảnh đầu tiên trong thư mục 'tiểu sử'
    tại poem/<author_slug>/tiểu sử/
    Trả về {"bio": str|None, "image_rel": str|None} (đường dẫn tương đối so với POEMS_DIR)
    """
    folder = Path(POEMS_DIR) / author_slug
    if not folder.exists():
        return {"bio": None, "image_rel": None}
    bio_text = None
    image_rel = None
    for sub in folder.iterdir():
        if sub.is_dir() and is_profile_dir(sub.name):
            bio_file = sub / "tieu_su.txt"
            if bio_file.exists():
                bio_text = read_text_file(str(bio_file)).strip()
            # Ảnh đầu tiên hợp lệ
            for img in sub.iterdir():
                if img.is_file() and img.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    image_rel = str(img.relative_to(POEMS_DIR)).replace("\\", "/")
                    break
            break
    return {"bio": bio_text, "image_rel": image_rel}

@app.route("/poem-files/<path:filename>")
def poem_files(filename):
    """Phục vụ file tĩnh từ thư mục 'poem' (ảnh tác giả, v.v.)."""
    return send_from_directory(POEMS_DIR, filename)

def list_poems_in_folder(author_slug: str):
    """
    Đọc danh sách BÀI THƠ: mỗi bài là 1 folder trong poem/<author_slug>/ (trừ 'tiểu sử').
    Trả về list dict {title, slug, path, created_at}
    """
    folder = Path(POEMS_DIR) / author_slug
    if not folder.exists() or not folder.is_dir():
        return []
    poems = []
    for sub in folder.iterdir():
        if not sub.is_dir() or is_profile_dir(sub.name):
            continue
        poem_slug = sub.name
        files = find_poem_files(author_slug, poem_slug)
        # ưu tiên title_vi, nếu không có thì title_en, nếu vẫn không có thì từ slug
        title = files.get("title_vi") or files.get("title_en") or pretty_from_slug(poem_slug)
        poems.append({
            "title": title,
            "slug": poem_slug,
            "path": str(sub),
            "created_at": files.get("created_at"),
        })
    poems.sort(key=lambda x: (x["created_at"] is None, x["created_at"]), reverse=True)
    return poems

def read_poem_content(author_slug, poem_slug, lang="vi") -> str:
    """
    Đọc nội dung bài thơ theo ngôn ngữ (vi|en).
    - Nếu file không tồn tại HOẶC rỗng → trả về "" (để template hiển thị thông báo).
    - Không abort(404) ở đây.
    """
    files = find_poem_files(author_slug, poem_slug)
    sel_path = files.get(lang)
    return read_lang_file(sel_path)

# ================== Khởi tạo DB ==================
with app.app_context():
    db.create_all()

# ================== Routes ==================
@app.route("/")
def index():
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    authors_db = Author.query.all()

    # Gộp tác giả từ database và folder
    folder_authors = [f.name for f in Path(POEMS_DIR).iterdir() if f.is_dir()]
    existing_slugs = {a.slug for a in authors_db}

    all_authors = [{"name": a.name, "slug": a.slug} for a in authors_db]
    for slug in folder_authors:
        if slug not in existing_slugs:
            all_authors.append({"name": pretty_from_slug(slug), "slug": slug})

    all_authors.sort(key=lambda x: x["name"])
    return render_template("index.html", comments=comments, authors=all_authors)

@app.route("/comment", methods=["POST"])
def comment():
    name = request.form.get("name", "Ẩn danh").strip()[:60]
    content = request.form.get("content", "").strip()[:2000]
    if content:
        db.session.add(Comment(name=name or "Ẩn danh", content=content))
        db.session.commit()
    return redirect(url_for("index") + "#binhluan")

# ===== API danh sách tác giả + thơ (top 3) =====
@app.route("/api/authors")
def api_authors():
    data = []
    # Lấy từ DB
    authors = Author.query.all()
    for a in authors:
        poems_sorted = sorted(
            a.poems,
            key=lambda x: (x.created_at is None, x.created_at),
            reverse=True
        )[:3]
        poems = [normalize_poem_item(p) for p in poems_sorted]
        prof = read_author_profile(a.slug)
        data.append({
            "name": a.name,
            "slug": a.slug,
            "poems": poems,
            "bio": prof["bio"],
            "image_url": url_for("poem_files", filename=prof["image_rel"]) if prof["image_rel"] else None
        })

    # Lấy từ folder (bổ sung những tác giả chưa có trong DB)
    folder_authors = [f.name for f in Path(POEMS_DIR).iterdir() if f.is_dir()]
    existing_slugs = {a["slug"] for a in data}

    for slug in folder_authors:
        if slug in existing_slugs:
            continue
        poems_raw = (list_poems_in_folder(slug) or [])[:3]
        poems = [normalize_poem_item(p) for p in poems_raw]
        prof = read_author_profile(slug)
        data.append({
            "name": pretty_from_slug(slug),
            "slug": slug,
            "poems": poems,
            "bio": prof["bio"],
            "image_url": url_for("poem_files", filename=prof["image_rel"]) if prof["image_rel"] else None
        })

    return jsonify(data)

# ===== Trang tác giả =====
@app.route("/tac-gia/<author_slug>/")
def author_page(author_slug):
    author = Author.query.filter_by(slug=author_slug).first()
    poems = []

    # DB
    if author:
        poems_db = [
            {
                "title": p.title,
                "slug": p.slug,
                "created_at": p.created_at,
                "source": "db",
            }
            for p in sorted(author.poems, key=lambda x: x.created_at, reverse=True)
        ]
        poems.extend(poems_db)

    # FS
    poems_fs = list_poems_in_folder(author_slug) or []
    for p in poems_fs:
        p["source"] = "file"
    poems.extend(poems_fs)

    if not poems:
        abort(404)

    poems.sort(key=lambda x: (x.get("created_at") is None, x.get("created_at")), reverse=True)

    profile = read_author_profile(author_slug)

    class SimpleAuthor: ...
    a = SimpleAuthor()
    a.name = author.name if author else pretty_from_slug(author_slug)
    a.slug = author_slug
    a.bio = profile["bio"]
    a.image_url = url_for("poem_files", filename=profile["image_rel"]) if profile["image_rel"] else None

    return render_template("author.html", author=a, poems=poems)

# ===== Trang bài thơ =====
@app.route("/tac-gia/<author_slug>/<poem_slug>/")
def poem_page(author_slug, poem_slug):
    # 1) Lấy ngôn ngữ (?lang=vi|en), mặc định vi
    lang = request.args.get("lang", "vi").lower()
    if lang not in ("vi", "en"):
        lang = "vi"

    # 2) DB (nếu có)
    author = Author.query.filter_by(slug=author_slug).first()
    poem_db = Poem.query.filter_by(author_id=author.id, slug=poem_slug).first() if author else None

    # 3) File system
    files = find_poem_files(author_slug, poem_slug)

    # 4) Tiêu đề theo ngôn ngữ (ưu tiên đúng lang)
    #    - Nếu không có title_lang → rơi về DB title → rơi về pretty_from_slug
    title = (
        files.get(f"title_{lang}")
        or (poem_db.title if poem_db else None)
        or pretty_from_slug(poem_slug)
    )

    # 5) created_at (DB ưu tiên, rồi tới FS)
    created_at = (poem_db.created_at if poem_db else None) or files.get("created_at")

    # 6) Nội dung theo lang (trả về "" nếu file không tồn tại / rỗng)
    content = read_poem_content(author_slug, poem_slug, lang=lang)

    # 7) Xác định ngôn ngữ nào THỰC SỰ có nội dung (để template biết hiển thị thông báo)
    vi_content = read_lang_file(files.get("vi"))
    en_content = read_lang_file(files.get("en"))
    available_langs = []
    if vi_content:
        available_langs.append("vi")
    if en_content:
        available_langs.append("en")

    # Nếu hoàn toàn không có nội dung ở cả DB lẫn FS → 404
    has_any_content = bool(content or vi_content or en_content or (poem_db and poem_db.content))
    if not has_any_content:
        abort(404)

    # 8) SimpleAuthor / SimplePoem cho template
    class SimpleAuthor: ...
    a = SimpleAuthor()
    a.name = author.name if author else pretty_from_slug(author_slug)
    a.slug = author_slug

    class SimplePoem: ...
    p = SimplePoem()
    p.slug = poem_slug
    p.title = title
    p.created_at = created_at
    p.lang = lang
    p.available_langs = available_langs  # dùng để quyết định thông báo "Have no English version"

    # 9) Sidebar: bài khác
    other_poems_list = list_poems_in_folder(author_slug) or []
    other_poems = []
    for it in other_poems_list:
        # if it.get("slug") == poem_slug:
        #     continue
        other_poems.append({
            "slug": it.get("slug"),
            "title": it.get("title") or pretty_from_slug(it.get("slug") or "")
        })
    other_poems.sort(key=lambda x: x["title"])

    return render_template(
        "poem.html",
        author=a,
        poem=p,
        content=content,
        other_poems=other_poems
    )

# Trang đánh giá
@app.route("/review")
def review():
    comments = Comment.query.order_by(Comment.created_at.desc()).all()
    return render_template("review.html", comments=comments)

@app.route("/review/comment", methods=["POST"])
def review_comment():
    name = request.form.get("name", "Ẩn danh").strip()[:60]
    content = request.form.get("content", "").strip()[:2000]
    if content:
        db.session.add(Comment(name=name or "Ẩn danh", content=content))
        db.session.commit()
    # Sau khi gửi xong quay lại trang review, kéo đến khu vực bình luận
    return redirect(url_for("review") + "#binhluan")



# ================== Main ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
