#!/usr/bin/env python3
"""Scrape NHK News Easy articles via nhkeasier.com, tokenize them, and output articles.json."""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import fugashi
import requests
from bs4 import BeautifulSoup

NHKEASIER_BASE = "https://nhkeasier.com"
NHKEASIER_FEED = "https://nhkeasier.com/feed/"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ARTICLES_FILE = DATA_DIR / "articles.json"
MAX_AGE_DAYS = 30

# MeCab POS tags to keep (content words)
KEEP_POS = {"名詞", "動詞", "形容詞", "副詞", "形状詞"}
# POS subtypes to exclude
EXCLUDE_POS_SUB = {"非自立可能", "数詞", "助数詞"}


def fetch_rss():
    """Fetch the NHK Easier RSS feed and return parsed items."""
    resp = requests.get(NHKEASIER_FEED, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        desc_html = item.findtext("description", "")
        pub_date = item.findtext("pubDate", "")
        items.append({
            "title": title,
            "link": link,
            "description_html": desc_html,
            "pub_date": pub_date,
        })
    return items


def fetch_story_page(url):
    """Fetch a story page from nhkeasier.com."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_text_from_html(html):
    """Extract article body text from nhkeasier.com story page, stripping ruby."""
    soup = BeautifulSoup(html, "html.parser")
    # Remove ruby text (furigana)
    for rt in soup.find_all("rt"):
        rt.decompose()
    for rp in soup.find_all("rp"):
        rp.decompose()
    # Find article element and extract only <p> tags from it (the actual content)
    article = soup.find("article")
    if not article:
        return ""
    paragraphs = article.find_all("p")
    text = " ".join(p.get_text(strip=True) for p in paragraphs)
    return text


def extract_text_from_description(desc_html):
    """Extract article text from RSS description HTML, stripping ruby."""
    soup = BeautifulSoup(desc_html, "html.parser")
    for rt in soup.find_all("rt"):
        rt.decompose()
    for rp in soup.find_all("rp"):
        rp.decompose()
    # Only extract text from <p> tags to avoid navigation/link text
    paragraphs = soup.find_all("p")
    if paragraphs:
        return " ".join(p.get_text(strip=True) for p in paragraphs)
    return soup.get_text(strip=True)


def extract_image_from_description(desc_html):
    """Extract image URL from RSS description HTML."""
    soup = BeautifulSoup(desc_html, "html.parser")
    img = soup.find("img")
    if img and img.get("src"):
        src = img["src"]
        if src.startswith("/"):
            return NHKEASIER_BASE + src
        return src
    return ""


def extract_nhk_url_from_page(html):
    """Extract the original NHK article URL from a story page."""
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        if "nhk.or.jp/news/easy/" in a["href"]:
            return a["href"]
    return ""


def tokenize(text, tagger):
    """Tokenize Japanese text, returning (unique_base_forms, total_token_count)."""
    words = []
    unique_words = set()
    for word in tagger(text):
        if word.feature.pos1 not in KEEP_POS:
            continue
        if word.feature.pos2 in EXCLUDE_POS_SUB:
            continue
        # Use lemma (dictionary form) if available, else surface form
        base = word.feature.lemma if word.feature.lemma else word.surface
        # Skip single hiragana particles that slip through
        if len(base) == 1 and re.match(r"[\u3040-\u309f]", base):
            continue
        words.append(base)
        unique_words.add(base)
    return list(unique_words), len(words)


def fetch_date_page_stories(date_str):
    """Fetch story links from a date page like /2026/03/14/."""
    url = f"{NHKEASIER_BASE}/{date_str.replace('-', '/')}/"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    story_links = set()
    for a in soup.find_all("a", href=True):
        match = re.match(r"/story/(\d+)/", a["href"])
        if match:
            story_links.add(int(match.group(1)))
    return sorted(story_links)


def load_existing_articles():
    """Load existing articles.json if present."""
    if ARTICLES_FILE.exists():
        with open(ARTICLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def main():
    # Initialize tokenizer
    tagger = fugashi.Tagger()

    # Load existing articles to avoid re-fetching
    existing = load_existing_articles()
    existing_by_id = {a["id"]: a for a in existing}

    cutoff = datetime.now() - timedelta(days=MAX_AGE_DAYS)
    articles = []

    # Step 1: Fetch RSS feed for recent articles
    print("Fetching NHK Easier RSS feed...")
    rss_items = fetch_rss()
    print(f"  Found {len(rss_items)} items in RSS feed")

    # Step 2: Also scrape date pages for the last MAX_AGE_DAYS
    all_story_ids = set()
    story_metadata = {}  # story_id -> {title, date, image, nhk_url}

    # Process RSS items first
    for item in rss_items:
        link = item["link"]
        match = re.search(r"/story/(\d+)/", link)
        if not match:
            continue
        story_id = int(match.group(1))
        all_story_ids.add(story_id)

        # Parse date
        date = ""
        if item["pub_date"]:
            try:
                dt = parsedate_to_datetime(item["pub_date"])
                date = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        image_url = extract_image_from_description(item["description_html"])
        text = extract_text_from_description(item["description_html"])

        story_metadata[story_id] = {
            "title": item["title"],
            "date": date,
            "image_url": image_url,
            "nhkeasier_url": link,
            "text": text,
        }

    # Scrape date pages to find more stories
    print("Scanning date pages for additional stories...")
    current = datetime.now()
    for day_offset in range(MAX_AGE_DAYS):
        date = current - timedelta(days=day_offset)
        date_str = date.strftime("%Y-%m-%d")
        story_ids = fetch_date_page_stories(date_str)
        for sid in story_ids:
            if sid not in all_story_ids:
                all_story_ids.add(sid)
                story_metadata[sid] = {
                    "title": "",
                    "date": date_str,
                    "image_url": "",
                    "nhkeasier_url": f"{NHKEASIER_BASE}/story/{sid}/",
                    "text": "",
                }
        if story_ids:
            print(f"  {date_str}: {len(story_ids)} stories")

    print(f"\nTotal unique stories found: {len(all_story_ids)}")

    # Step 3: Process each story
    for story_id in sorted(all_story_ids, reverse=True):
        str_id = str(story_id)

        # Reuse existing data if we already have it
        if str_id in existing_by_id:
            article = existing_by_id[str_id]
            # Check if still within date range
            try:
                article_date = datetime.strptime(article["date"], "%Y-%m-%d")
                if article_date >= cutoff:
                    articles.append(article)
            except (ValueError, KeyError):
                articles.append(article)
            continue

        meta = story_metadata.get(story_id, {})
        nhkeasier_url = meta.get("nhkeasier_url", f"{NHKEASIER_BASE}/story/{story_id}/")

        # If we don't have text from RSS, fetch the story page
        text = meta.get("text", "")
        title = meta.get("title", "")
        nhk_url = ""

        if not text or not title:
            print(f"  Fetching story page: {nhkeasier_url}")
            try:
                page_html = fetch_story_page(nhkeasier_url)
                if not text:
                    text = extract_text_from_html(page_html)
                if not title:
                    soup = BeautifulSoup(page_html, "html.parser")
                    title_tag = soup.find("title")
                    if title_tag:
                        title = title_tag.get_text().replace(" | NHK Easier", "").strip()
                nhk_url = extract_nhk_url_from_page(page_html)
                if not meta.get("image_url"):
                    soup = BeautifulSoup(page_html, "html.parser")
                    og_img = soup.find("meta", property="og:image")
                    if og_img and og_img.get("content"):
                        src = og_img["content"]
                        meta["image_url"] = NHKEASIER_BASE + src if src.startswith("/") else src
            except requests.RequestException as e:
                print(f"    Error fetching: {e}")
                continue

        if not text:
            print(f"    No text for story {story_id}, skipping")
            continue

        unique_words, word_count = tokenize(text, tagger)
        if word_count == 0:
            continue

        image_url = meta.get("image_url", "")

        articles.append({
            "id": str_id,
            "title": title,
            "date": meta.get("date", ""),
            "url": nhk_url or nhkeasier_url,
            "nhkeasier_url": nhkeasier_url,
            "image_url": image_url,
            "words": unique_words,
            "word_count": word_count,
        })

    # Sort by date descending
    articles.sort(key=lambda a: a.get("date", ""), reverse=True)

    # Write output
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ARTICLES_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Wrote {len(articles)} articles to {ARTICLES_FILE}")


if __name__ == "__main__":
    main()
