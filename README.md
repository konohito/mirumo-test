# みるも 見守りダッシュボード

徘徊探知機「みるも」からエクスポートしたCSV（通知ログ・センサーデータ・睡眠データ）を集計し、
GitHub Pages で閲覧できるダッシュボードにします。

- 公開URL（Pages有効化後）: https://konohito.github.io/mirumo-test/

## 構成

```
data/raw/            みるもからエクスポートしたCSV（Shift-JISのままでOK）
scripts/build_data.py  CSV → docs/data/dashboard.json を生成
docs/                ダッシュボード本体（GitHub Pagesで配信）
.github/workflows/pages.yml  main への push で集計 → Pages へデプロイ
```

## データの更新方法

1. 新しいCSVを `data/raw/` に追加する（ファイル名は自由。種類はヘッダー行で自動判定）
   - 通知ログ（`発生日時,種別,内容,...`）
   - センサーデータ（`日時,温度,湿度,照度,...`）
   - 睡眠データ（`日時,就寝,起床,睡眠時間,夜間起床`）
2. main に push する → GitHub Actions が自動で集計・デプロイ

期間が重複するCSVを入れても、日時をキーに重複排除してマージされます。
ローカルで確認する場合:

```sh
python3 scripts/build_data.py
python3 -m http.server -d docs 8000   # http://localhost:8000
```

## ダッシュボードの内容

- KPI（離床・夜間離床・トイレ回数／平均滞在・ドア開・室温）とスパークライン
- 日別アクティビティ、注目ポイント（長時間トイレ滞在・夜間離床の多い夜・増減傾向・暑さ指数など）
- 生活リズムヒートマップ（日 × 時間帯）
- 1日のタイムライン（イベント＋室温・照度・運動指数）
- 夜間の離床、トイレ滞在時間、室温・湿度の推移、睡眠・起床レポート、通知ログ一覧
