# RDS-MCP-Sample

工場で稼働する設備の情報(生産状況/不良数/生産実績/在庫/設計部品表/購買)を扱う社内システムを想定し、自然言語の問い合わせを LLM(Amazon Bedrock / Nova Lite)が解釈、**MCP 経由で複数の DB(エンジン違い・バージョン違いを含む)から横断的にデータを引いてくる**デモアプリ。

- すべて Docker で起動。ローカルにツールをインストール不要。
- 「複数 DB エンジン × 複数バージョン × 複数業務領域 × ロールベースのアクセス制御」を 1 台のホストで再現。

## アーキテクチャ

```
Streamlit (Strands Agents + Bedrock Nova Lite)
    │
    ├─ MCP (SSE) ─ mcp-mysql ──┬─ MySQL 8.0   (ebom_db        : E-BOM)
    │                          └─ MySQL 5.7   (procurement_db : 購買・調達)
    │
    └─ MCP (SSE) ─ mcp-postgres ┬─ PostgreSQL 16 (scada_db : SCADA + 生産実績)
                                ├─ PostgreSQL 13 (wms_db   : WMS / 在庫)
                                └─ PostgreSQL 14 (qms_db   : QMS / 品質)
```

詳細な ER 図・論理設計・物理設計は [docs/database.md](docs/database.md) を参照。

## セットアップ

### 必要なもの
- Docker Desktop(Windows / macOS / Linux)
- Amazon Bedrock の API キー(Nova Lite が利用可能なリージョン)

### 起動手順

```bash
# 1. env ファイルを準備
cp .env.example .env.local
# .env.local の BEDROCK_API_KEY などを書き換える

# 2. ビルドして起動(--env-file で .env.local の変数を compose に補間させる)
docker compose --env-file .env.local up -d --build

# 3. 起動確認(8 サービスが healthy / running になればOK)
docker compose --env-file .env.local ps

# 4. ブラウザで http://localhost:8501 を開く
```

初回起動時は SCADA の seed(約 17,000 行)の流し込みで 1〜2 分かかります。`docker compose logs -f postgres16` で進捗が見えます。

### 停止 / クリーンアップ

```bash
# 停止だけ(データは残る)
docker compose --env-file .env.local down

# 完全削除(DB ボリュームも消す)
docker compose --env-file .env.local down -v
```

## デモシナリオ

サイドバーでロールを切り替えて質問してください。ロールごとに見える DB と拠点が変わります。

| ロール | 拠点 | アクセス可能 DB | 想定質問 |
|---|---|---|---|
| Tokyo - 設計者 | Tokyo | E-BOM / SCADA / QMS | 「ベアリング系の部品の設計変更履歴を見せて」 |
| Tokyo - 購買担当 | Tokyo | 購買 / E-BOM / WMS | 「Tokyo Steel の発注で納期遅れリスクがあるものは?」 |
| Tokyo - 現場オペレーター | Tokyo | SCADA / WMS | 「Tokyo Line-2 の昨日の稼働率は?」 |
| Osaka - 設計者 / 購買 / オペレーター | Osaka | (同上) | (同上、Osaka に対して) |
| 品質マネージャー | 全社 | QMS / SCADA / E-BOM | 「不良率が悪化したラインと、原因部品の設計変更履歴」 |
| 管理者 | 全社 | 全 DB | 「全社の稼働率トップ 3 ラインと、サプライヤーの納期遵守率」 |

**境界テスト例**: ロールを `tokyo_operator` にして「Osaka の在庫を教えて」と聞くと、拠点スコープ違反として拒否されます。

## ロールベース・アクセス制御の仕組み

[app/auth.py](app/auth.py) で「ロール → 拠点 ID + アクセス可能 DB」を定義し、[app/system_prompt.py](app/system_prompt.py) でその情報をシステムプロンプトに固定埋め込みします。LLM はそのプロンプトに従って WHERE 句を組み立てるため、**アプリ層のフィルタとして機能**します。

> **注意**: これは LLM がプロンプトに従う前提のソフトな統制です。本番運用では DB ロール/VIEW での GRANT を併用することを推奨します。

## トラブルシュート

- **MySQL の seed が流れない**: `docker compose down -v` でボリュームごと削除して再度 up。`docker-entrypoint-initdb.d` は初回起動時しか走らないため。
- **Bedrock 認証エラー**: Strands Agents(Python)は `BEDROCK_API_KEY` を直接見ないので、[app/main.py](app/main.py) で `AWS_BEARER_TOKEN_BEDROCK` にコピーしています。boto3 のバージョンによっては Bearer 認証を受け付けないことがあります。その場合は `.env.local` に `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` を入れてください。
- **MySQL 5.7**: サポート終了済みのバージョンですが、「複数バージョン違いを再現するデモ用途」として採用しています。本番では使わないでください。

## ファイル構成

```
RDS-MCP-Sample/
├─ docker-compose.yml                 # 8 サービスの定義
├─ .env.example
├─ docs/
│  └─ database.md                     # ER 図 + 論理設計 + 物理設計(DDL)
├─ app/                               # Streamlit + Strands Agents
│  ├─ main.py / agent.py / auth.py / system_prompt.py
│  └─ Dockerfile / requirements.txt
├─ mcps/                              # MCP レイヤー(将来 MCP サーバーを追加するときもここに置く)
│  ├─ mysql/                          # MySQL 向け自作 MCP サーバー(SSE)
│  │  └─ server.py / Dockerfile / requirements.txt
│  └─ postgres/                       # PostgreSQL 向け自作 MCP サーバー(SSE)
│     └─ server.py / Dockerfile / requirements.txt
├─ db-init/
│  ├─ ebom/         (MySQL 8.0)
│  ├─ procurement/  (MySQL 5.7)
│  ├─ scada/        (Postgres 16)
│  ├─ wms/          (Postgres 13)
│  └─ qms/          (Postgres 14)
└─ scripts/
   └─ generate_seed.py                # seed SQL の再生成スクリプト
```
