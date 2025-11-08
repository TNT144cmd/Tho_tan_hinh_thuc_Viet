// static/app.js
(function () {
  const dropdown = document.getElementById("authorDropdown");
  const authorListEl = dropdown?.querySelector(".author-list");
  const poemListEl = dropdown?.querySelector(".poem-list");
  let AUTHORS = [];

  function renderAuthors() {
    authorListEl.innerHTML = "";
    AUTHORS.sort((a, b) => a.name.localeCompare(b.name, "vi"));
    AUTHORS.forEach((a) => {
      const li = document.createElement("li");
      li.className = "author-item";
      li.textContent = a.name;
      li.tabIndex = 0;
      li.addEventListener("mouseenter", () => showNewestPoems(a));
      li.addEventListener("focus", () => showNewestPoems(a));
      li.addEventListener("click", () => {
        window.location.href = `/tac-gia/${a.slug}/`;
      });
      authorListEl.appendChild(li);
    });
  }

  // hiển thị 3 bài mới nhất 
  function showNewestPoems(author) {
    poemListEl.innerHTML = "";
    const poems = author.poems
      .slice()
      .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
      .slice(0, 3);
    if (poems.length === 0) {
      poemListEl.innerHTML = `<li class="muted">Chưa có tác phẩm.</li>`;
      return;
    }
    poems.forEach((p) => {
      const li = document.createElement("li");
      li.className = "poem-item";
      li.textContent = p.title;
      li.addEventListener("click", (e) => {
        e.stopPropagation();
        window.location.href = `/tac-gia/${author.slug}/${p.slug}/`;
      });
      poemListEl.appendChild(li);
    });
  }

  const wrapper = document.querySelector(".nav-author");
  if (wrapper && dropdown) {
    wrapper.addEventListener("mouseenter", () =>
      dropdown.classList.add("open")
    );
    wrapper.addEventListener("mouseleave", () =>
      dropdown.classList.remove("open")
    );
  }

  // Lấy dữ liệu tác giả
  fetch("/api/authors")
    .then((r) => r.json())
    .then((data) => {
      AUTHORS = data || [];
      renderAuthors();
    })
    .catch(() => {});
  
  document.addEventListener("DOMContentLoaded", function () {
  const nameInput = document.querySelector(".comment-form #name");
  const contentArea = document.querySelector(".comment-form #content");

  if (nameInput && contentArea) {
    nameInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();          // không submit form
        contentArea.focus();         // chuyển focus xuống textarea

        // Đưa con trỏ xuống cuối nội dung (nếu có sẵn)
        const len = contentArea.value.length;
        contentArea.setSelectionRange(len, len);
      }
    });
  }
});
})();
