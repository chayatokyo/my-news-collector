# my-news-collector

RSS フィードを自動収集し、Markdown ファイルとして出力するツール。
GitHub Actions により毎朝定時に実行され、PCの起動状況に依存しません。

## 仕組み

1. **GitHub Actions** が毎朝 JST 5:00 に `scripts/collect_rss.py` を実行
2. `config/` 内の YAML 定義に基づき、RSS フィードを並列取得
3. キーワードフィルタで関連記事を抽出
4. `output/コレクション名/YYYY-MM-DD.md` として自動コミット

## コレクション

| 名前      | 設定ファイル          | 用途                         |
| --------- | --------------------- | ---------------------------- |
| `ai-news` | `config/ai-news.yaml` | 生成AI関連ニュースの日次収集 |

新しいコレクションを追加するには `config/` に YAML ファイルを追加するだけ。

## ローカル実行

```bash
pip install -r requirements.txt
python scripts/collect_rss.py --config config/ai-news.yaml
```

## 出力先

```
output/
├── ai-news/
│   ├── 2026-02-17.md
│   ├── 2026-02-18.md
│   └── ...
└── (将来の別コレクション)/
```
