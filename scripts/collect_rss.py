"""
RSS News Collector

config/ 内のYAML定義に基づき、RSSフィードを取得し
Markdownファイルとして出力するスクリプト。

Usage:
    python scripts/collect_rss.py --config config/ai-news.yaml [--date 2026-02-17]
"""

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import feedparser
import yaml

# 日本標準時
JST = timezone(timedelta(hours=9))

# 曜日名（日本語）
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def load_config(config_path: str) -> dict[str, Any]:
    """YAML設定ファイルを読み込む"""
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_entry_date(entry: feedparser.FeedParserDict) -> datetime | None:
    """フィードエントリの公開日時をパースする"""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """テキストがキーワードのいずれかに合致するか判定"""
    lower_text = text.lower()
    return any(kw.lower() in lower_text for kw in keywords)


def matches_exclude_keywords(text: str, exclude_keywords: list[str]) -> bool:
    """テキストが除外キーワードのいずれかに合致するか判定"""
    if not exclude_keywords:
        return False
    lower_text = text.lower()
    return any(kw.lower() in lower_text for kw in exclude_keywords)


def fetch_single_feed(
    feed_config: dict[str, str],
) -> tuple[str, list[feedparser.FeedParserDict], str | None]:
    """単一のRSSフィードを取得する。(name, entries, error) を返す"""
    name = feed_config["name"]
    url = feed_config["url"]
    try:
        # User-Agent を設定（Reddit等がブロックするため）
        parsed = feedparser.parse(
            url,
            agent="my-news-collector/1.0 (https://github.com/chayatokyo/my-news-collector)",
        )
        if parsed.bozo and not parsed.entries:
            return (name, [], f"Parse error: {parsed.bozo_exception}")
        return (name, parsed.entries, None)
    except Exception as e:
        return (name, [], str(e))


def collect_articles(
    config: dict[str, Any], target_date: datetime
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """
    全フィードから記事を収集・フィルタリングする。
    Returns: (articles, errors)
    """
    feeds = config.get("feeds", [])
    keywords = config.get("keywords", [])
    exclude_keywords = config.get("exclude_keywords", [])
    fetch_hours = config.get("fetch_hours", 48)
    cutoff_time = target_date - timedelta(hours=fetch_hours)

    articles: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    print(f"Fetching {len(feeds)} feeds...")

    # 並列でフィードを取得
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_single_feed, feed): feed for feed in feeds
        }
        for future in as_completed(futures):
            feed_config = futures[future]
            name, entries, error = future.result()

            if error:
                errors.append({"name": name, "error": error})
                print(f"  ✗ {name}: {error}")
                continue

            feed_article_count = 0
            for entry in entries:
                # URL の重複チェック
                url = getattr(entry, "link", "")
                if not url or url in seen_urls:
                    continue

                # 日付フィルタ
                pub_date = parse_entry_date(entry)
                if pub_date and pub_date < cutoff_time:
                    continue

                # テキストを結合してキーワードフィルタ
                title = getattr(entry, "title", "")
                summary = getattr(entry, "summary", "")
                combined_text = f"{title} {summary}"

                # 除外キーワードチェック
                if matches_exclude_keywords(combined_text, exclude_keywords):
                    continue

                # キーワードマッチ
                if not matches_keywords(combined_text, keywords):
                    continue

                seen_urls.add(url)
                feed_article_count += 1
                articles.append(
                    {
                        "title": clean_text(title),
                        "url": url,
                        "source": name,
                        "category": feed_config.get("category", "other"),
                        "language": feed_config.get("language", "en"),
                        "published": (
                            pub_date.astimezone(JST).strftime("%Y-%m-%d %H:%M")
                            if pub_date
                            else "不明"
                        ),
                        "summary": clean_text(summary)[:200],
                    }
                )

            print(f"  ✓ {name}: {feed_article_count} articles")

    # カテゴリ優先度でソート（公式 → 国内 → 海外 → 技術 → Reddit → 業界）
    category_order = {
        "official": 0,
        "domestic": 1,
        "international": 2,
        "tech": 3,
        "reddit": 4,
        "industry": 5,
        "other": 6,
    }
    articles.sort(key=lambda a: category_order.get(a["category"], 99))

    return articles, errors


def clean_text(text: str) -> str:
    """HTMLタグ除去・空白整理"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def category_label(category: str) -> str:
    """カテゴリ名を日本語ラベルに変換"""
    labels = {
        "official": "🏢 AI企業公式",
        "domestic": "📰 国内メディア",
        "international": "🌐 海外メディア",
        "tech": "💻 技術コミュニティ",
        "reddit": "💬 Reddit",
        "industry": "🇯🇵 業界特化",
        "other": "📋 その他",
    }
    return labels.get(category, category)


def generate_markdown(
    config: dict[str, Any],
    articles: list[dict[str, str]],
    errors: list[dict[str, str]],
    target_date: datetime,
) -> str:
    """Markdownファイルのコンテンツを生成する"""
    date_str = target_date.strftime("%Y-%m-%d")
    weekday = WEEKDAY_JA[target_date.weekday()]
    date_jp = f"{target_date.year}年{target_date.month}月{target_date.day}日（{weekday}）"

    lines: list[str] = []
    lines.append(f"# AI News — {date_jp}")
    lines.append("")
    lines.append(
        f"> 自動収集: {len(articles)} 件 / エラー: {len(errors)} 件"
    )
    lines.append(f"> 収集時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}")
    lines.append("")

    if not articles:
        lines.append("本日の該当記事はありませんでした。")
        lines.append("")
    else:
        # カテゴリごとにグループ化
        current_category = ""
        for article in articles:
            if article["category"] != current_category:
                current_category = article["category"]
                lines.append(f"## {category_label(current_category)}")
                lines.append("")

            lines.append(f"- [ ] [{article['title']} | {article['source']}]({article['url']})")
            if article["summary"]:
                lines.append(f"      {article['summary'][:150]}")
            lines.append("")

    # エラー情報
    if errors:
        lines.append("---")
        lines.append("")
        lines.append("## ⚠ 取得エラー")
        lines.append("")
        for err in errors:
            lines.append(f"- **{err['name']}**: {err['error']}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="RSS News Collector")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to config YAML file (e.g., config/ai-news.yaml)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Target date (YYYY-MM-DD). Defaults to today (JST).",
    )
    args = parser.parse_args()

    # 設定読み込み
    config = load_config(args.config)
    collection_name = config.get("name", "default")

    # 日付の決定
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=JST)
    else:
        target_date = datetime.now(JST)

    date_str = target_date.strftime("%Y-%m-%d")
    print(f"Collection: {collection_name}")
    print(f"Date: {date_str}")
    print()

    # 記事収集
    start_time = time.time()
    articles, errors = collect_articles(config, target_date)
    elapsed = time.time() - start_time

    print()
    print(f"Results: {len(articles)} articles collected in {elapsed:.1f}s")
    print(f"Errors: {len(errors)} feeds failed")

    # Markdown 生成
    markdown = generate_markdown(config, articles, errors, target_date)

    # 出力ディレクトリの作成
    output_dir = Path(config.get("output", {}).get("directory", f"output/{collection_name}"))
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / f"{date_str}.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown)

    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
