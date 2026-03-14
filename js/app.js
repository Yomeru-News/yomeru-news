(() => {
  "use strict";

  const STORAGE_KEY = "ezjp_vocab";
  const ARTICLES_URL = "data/articles.json";

  // DOM elements
  const vocabInput = document.getElementById("vocab-input");
  const vocabFile = document.getElementById("vocab-file");
  const saveBtn = document.getElementById("save-vocab");
  const clearBtn = document.getElementById("clear-vocab");
  const vocabStatus = document.getElementById("vocab-status");
  const articlesLoading = document.getElementById("articles-loading");
  const articlesList = document.getElementById("articles-list");
  const noVocabMessage = document.getElementById("no-vocab-message");
  const sortSelect = document.getElementById("sort-select");

  let articles = [];
  let userVocab = new Set();

  // --- Vocab Management ---

  function parseVocabText(text) {
    // Handle one word per line, comma-separated, or tab-separated
    return text
      .split(/[\n,\t]+/)
      .map((w) => w.trim())
      .filter((w) => w.length > 0);
  }

  function parseCSVFirstColumn(text) {
    // For CSV files, take the first column of each row
    const lines = text.split(/\n/);
    const words = [];
    for (const line of lines) {
      const cols = line.split(",");
      const word = cols[0].trim().replace(/^["']|["']$/g, "");
      if (word.length > 0) {
        words.push(word);
      }
    }
    return words;
  }

  function loadVocab() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        const words = JSON.parse(stored);
        userVocab = new Set(words);
        vocabInput.value = words.join("\n");
      } catch {
        userVocab = new Set();
      }
    }
    updateVocabStatus();
  }

  function saveVocab() {
    const words = parseVocabText(vocabInput.value);
    userVocab = new Set(words);
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...userVocab]));
    updateVocabStatus();
    renderArticles();
  }

  function clearVocab() {
    userVocab = new Set();
    vocabInput.value = "";
    localStorage.removeItem(STORAGE_KEY);
    updateVocabStatus();
    renderArticles();
  }

  function updateVocabStatus() {
    const count = userVocab.size;
    if (count > 0) {
      vocabStatus.textContent = `${count} words loaded`;
      vocabStatus.className = "status-badge has-vocab";
    } else {
      vocabStatus.textContent = "No vocabulary loaded";
      vocabStatus.className = "status-badge";
    }
  }

  function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target.result;
      let words;
      if (file.name.endsWith(".csv")) {
        words = parseCSVFirstColumn(text);
      } else {
        words = parseVocabText(text);
      }

      // Merge with existing vocab
      for (const w of words) {
        userVocab.add(w);
      }
      vocabInput.value = [...userVocab].join("\n");
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...userVocab]));
      updateVocabStatus();
      renderArticles();
    };
    reader.readAsText(file);
    // Reset input so same file can be re-uploaded
    e.target.value = "";
  }

  // --- Article Scoring ---

  function scoreArticle(article) {
    if (userVocab.size === 0) return 0;
    const knownCount = article.words.filter((w) => userVocab.has(w)).length;
    return (knownCount / article.word_count) * 100;
  }

  function getDifficultyClass(percent) {
    if (percent >= 80) return "easy";
    if (percent >= 50) return "medium";
    return "hard";
  }

  // --- Rendering ---

  function renderArticles() {
    articlesList.innerHTML = "";
    articlesLoading.hidden = true;

    if (userVocab.size === 0) {
      noVocabMessage.hidden = false;
      // Still show articles without scores
      for (const article of articles.slice(0, 20)) {
        articlesList.appendChild(createArticleCard(article, null));
      }
      return;
    }

    noVocabMessage.hidden = true;

    // Score and sort
    const scored = articles.map((a) => ({
      ...a,
      score: scoreArticle(a),
    }));

    const sortMode = sortSelect.value;
    if (sortMode === "easiest") {
      scored.sort((a, b) => b.score - a.score);
    } else if (sortMode === "hardest") {
      scored.sort((a, b) => a.score - b.score);
    } else {
      scored.sort((a, b) => b.date.localeCompare(a.date));
    }

    for (const article of scored) {
      articlesList.appendChild(createArticleCard(article, article.score));
    }
  }

  function createArticleCard(article, score) {
    const card = document.createElement("a");
    card.className = "article-card";
    card.href = article.nhkeasier_url || article.url;
    card.target = "_blank";
    card.rel = "noopener noreferrer";

    const thumbHtml = article.image_url
      ? `<img class="article-thumb" src="${escapeHtml(article.image_url)}" alt="" loading="lazy">`
      : "";

    let difficultyHtml = "";
    if (score !== null) {
      const level = getDifficultyClass(score);
      difficultyHtml = `
        <div class="difficulty-bar-container">
          <div class="difficulty-bar">
            <div class="difficulty-bar-fill ${level}" style="width: ${Math.min(score, 100)}%"></div>
          </div>
          <span class="difficulty-label ${level}">${Math.round(score)}% readable</span>
        </div>
      `;
    }

    card.innerHTML = `
      ${thumbHtml}
      <div class="article-info">
        <div class="article-title">${escapeHtml(article.title)}</div>
        <div class="article-date">${escapeHtml(article.date)}</div>
        ${difficultyHtml}
      </div>
    `;

    return card;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // --- Initialization ---

  async function loadArticles() {
    try {
      const resp = await fetch(ARTICLES_URL);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      articles = await resp.json();
      renderArticles();
    } catch (err) {
      articlesLoading.textContent =
        "Could not load articles. Make sure the scraper has run at least once.";
      console.error("Failed to load articles:", err);
    }
  }

  // --- Theme ---

  const themeToggle = document.getElementById("theme-toggle");
  const THEME_KEY = "ezjp_theme";

  function updateToggleLabel() {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    themeToggle.textContent = isDark ? "Light mode" : "Dark mode";
  }

  function initTheme() {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "dark" || (!stored && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
      document.documentElement.setAttribute("data-theme", "dark");
    }
    updateToggleLabel();
  }

  function toggleTheme() {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    if (isDark) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem(THEME_KEY, "light");
    } else {
      document.documentElement.setAttribute("data-theme", "dark");
      localStorage.setItem(THEME_KEY, "dark");
    }
    updateToggleLabel();
  }

  // --- Sponsor Heart Animation ---

  const sponsorLink = document.querySelector(".sponsor-link");
  let heartInterval = null;

  function spawnHeart() {
    const rect = sponsorLink.getBoundingClientRect();
    const heart = document.createElement("span");
    heart.className = "heart-particle";
    heart.textContent = "♥";
    const dx = (Math.random() - 0.5) * 30;
    const dy = -(Math.random() * 40 + 20);
    heart.style.setProperty("--dx", dx + "px");
    heart.style.setProperty("--dy", dy + "px");
    // Spawn from center of the ♥ character (~2px from left edge)
    heart.style.left = (rect.left + 2) + "px";
    heart.style.top = (rect.top - 5) + "px";
    document.body.appendChild(heart);
    heart.addEventListener("animationend", () => heart.remove());
  }

  if (sponsorLink) {
    let heartTimeout = null;
    sponsorLink.addEventListener("mouseover", () => {
      if (heartInterval || heartTimeout) return;
      spawnHeart();
      heartInterval = setInterval(() => spawnHeart(), 250);
      heartTimeout = setTimeout(() => {
        clearInterval(heartInterval);
        heartInterval = null;
      }, 600);
    });
    sponsorLink.addEventListener("mouseout", () => {
      clearInterval(heartInterval);
      clearTimeout(heartTimeout);
      heartInterval = null;
      heartTimeout = null;
    });
  }

  // Event listeners
  saveBtn.addEventListener("click", saveVocab);
  clearBtn.addEventListener("click", clearVocab);
  vocabFile.addEventListener("change", handleFileUpload);
  sortSelect.addEventListener("change", renderArticles);
  themeToggle.addEventListener("click", toggleTheme);

  // Boot
  initTheme();
  loadVocab();
  loadArticles();
})();
