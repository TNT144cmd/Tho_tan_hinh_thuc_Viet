import re
from flask import Flask, render_template, request, redirect, url_for, jsonify, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import os
from pathlib import Path

app = Flask(__name__)

# ================== Cấu hình DB ==================
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///comments.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ================== Tiện ích chung ==================
def slugify(s):
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE).strip().lower()
    s = re.sub(r"[-\s]+", "-", s)
    return s

def pretty_from_slug(slug: str) -> str:
    return slug.replace("-", " ").title()

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

def read_text_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def is_profile_dir(name: str) -> bool:
    n = name.strip().lower()
    return n in PROFILE_DIR_NAMES

def find_poem_files(author_slug: str, poem_slug: str):
    """
    Nhận diện file trong folder bài thơ poem/<author>/<poem_slug>/ theo mẫu:
      - <tengoc>_vi.txt
      - <tengoc>_en.txt
    Trả về:
      {
        "vi": path|None,
        "en": path|None,
        "base_slug": str|None,
        "base_title": str|None,
        "created_at": datetime|None
      }

    * Tương thích ngược: nếu không thấy *_vi.txt|*_en.txt thì fallback vi.txt|en.txt
      và dùng poem_slug làm base.
    """
    base_dir = Path(POEMS_DIR) / author_slug / poem_slug
    vi_path = en_path = None
    base_name = None
    mtimes = []

    if base_dir.exists() and base_dir.is_dir():
        # quét các file .txt để tìm pattern <base>_(vi|en).txt
        for f in base_dir.iterdir():
            if not (f.is_file() and f.suffix.lower() == ".txt"):
                continue
            m = LANG_SUFFIX_RE.match(f.name)
            if m:
                lang = m.group("lang").lower()
                base_name_found = m.group("base").strip()
                if lang == "vi":
                    vi_path = str(f)
                elif lang == "en":
                    en_path = str(f)
                if base_name is None:
                    base_name = base_name_found

        # fallback kiểu cũ vi.txt/en.txt
        if not vi_path:
            fallback_vi = base_dir / "vi.txt"
            if fallback_vi.exists():
                vi_path = str(fallback_vi)
        if not en_path:
            fallback_en = base_dir / "en.txt"
            if fallback_en.exists():
                en_path = str(fallback_en)

        if not base_name:
            base_name = poem_slug

        # mtime mới nhất
        for p in (vi_path, en_path):
            if p:
                try:
                    mtimes.append(Path(p).stat().st_mtime)
                except Exception:
                    pass
        if mtimes:
            created_at = datetime.fromtimestamp(max(mtimes))
        else:
            created_at = datetime.fromtimestamp(base_dir.stat().st_mtime) if base_dir.exists() else None
    else:
        vi_path = en_path = None
        base_name = poem_slug
        created_at = None

    base_slug = slugify(base_name) if base_name else None
    base_title = pretty_from_slug(base_slug) if base_slug else None

    return {
        "vi": vi_path,
        "en": en_path,
        "base_slug": base_slug,
        "base_title": base_title,
        "created_at": created_at,
    }

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

def list_poems_in_folder(author_slug):
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
        poems.append({
            "title": files["base_title"] or pretty_from_slug(poem_slug),
            "slug": poem_slug,
            "path": str(sub),
            "created_at": files["created_at"]
        })
    poems.sort(key=lambda x: (x["created_at"] is None, x["created_at"]), reverse=True)
    return poems

def read_poem_content(author_slug, poem_slug, lang="vi"):
    """
    Đọc nội dung bài thơ theo ngôn ngữ (vi|en).
    Ưu tiên DB nếu có nội dung; nếu cả DB và file cùng có -> gộp (DB trước, file sau).
    """
    # DB
    db_content = None
    author = Author.query.filter_by(slug=author_slug).first()
    if author:
        poem = Poem.query.filter_by(author_id=author.id, slug=poem_slug).first()
        if poem and poem.content:
            db_content = poem.content.strip()

    # File theo lang
    file_content = None
    files = find_poem_files(author_slug, poem_slug)
    sel_path = files.get(lang)
    if sel_path and Path(sel_path).exists():
        file_content = read_text_file(sel_path).strip()

    # Kết hợp ưu tiên
    if db_content and file_content:
        return f"{db_content}\n\n---\n\n{file_content}"
    elif db_content:
        return db_content
    elif file_content:
        return file_content
    else:
        return ""


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

    class SimpleAuthor: pass
    a = SimpleAuthor()
    a.name = author.name if author else pretty_from_slug(author_slug)
    a.slug = author_slug
    a.bio = profile["bio"]
    a.image_url = url_for("poem_files", filename=profile["image_rel"]) if profile["image_rel"] else None

    return render_template("author.html", author=a, poems=poems)

# ===== Trang bài thơ =====
@app.route("/tac-gia/<author_slug>/<poem_slug>/")
def poem_page(author_slug, poem_slug):
    # chọn ngôn ngữ qua query param (?lang=vi|en), mặc định vi
    lang = request.args.get("lang", "vi").lower()
    if lang not in ("vi", "en"):
        lang = "vi"

    # DB
    author = Author.query.filter_by(slug=author_slug).first()
    poem_db = None
    if author:
        poem_db = Poem.query.filter_by(author_id=author.id, slug=poem_slug).first()

    files = find_poem_files(author_slug, poem_slug)

    # Tiêu đề ưu tiên DB; nếu không có -> dùng base_title từ tên file *_vi/_en
    db_title = poem_db.title.strip() if (poem_db and poem_db.title) else None
    title = db_title or files["base_title"] or pretty_from_slug(poem_slug)

    # created_at ưu tiên DB; nếu không có -> từ files
    created_at = (poem_db.created_at if poem_db else None) or files["created_at"]

    # Nội dung
    content = read_poem_content(author_slug, poem_slug, lang=lang)

    # SimpleAuthor
    class SimpleAuthor: pass
    a = SimpleAuthor()
    a.name = author.name if author else pretty_from_slug(author_slug)
    a.slug = author_slug

    # SimplePoem
    class SimplePoem: pass
    p = SimplePoem()
    p.slug = poem_slug
    p.title = title
    p.created_at = created_at
    p.lang = lang
    p.available_langs = [l for l in ("vi", "en") if files.get(l) and Path(files[l]).exists()]

    # Sidebar: bài khác
    other_poems_list = list_poems_in_folder(author_slug) or []
    other_poems = []
    for it in other_poems_list:
        if it.get("slug") == poem_slug:
            continue
        other_poems.append({
            "slug": it.get("slug"),
            "title": it.get("title") or pretty_from_slug(it.get("slug") or "")
        })
    other_poems.sort(key=lambda x: x["title"])

    return render_template("poem.html",
                           author=a, poem=p, content=content, other_poems=other_poems)

# ================== Main ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
