# 🔧 Kintsugi-Helix — 自律型障害回復AIエージェント

> **金継ぎ (Kintsugi)** — 壊れた陶器を金で修復し、破損の歴史を美として昇華させる日本の伝統技法。
> Kintsugi-Helixは、この哲学をソフトウェアに適用します。**障害は「隠すべき傷」ではなく「改善と進化の機会」。**

[![Demo](https://img.shields.io/badge/Live_Demo-Cloud_Run-4285F4?logo=googlecloud)](https://kintsugi-helix-agent-541617236229.asia-northeast1.run.app/demo/)
[![YouTube](https://img.shields.io/badge/Demo_Video-YouTube-FF0000?logo=youtube)](https://youtu.be/e6lkxwWsad8)
[![Gemini](https://img.shields.io/badge/Powered_by-Gemini_2.5_Pro-8E75B2?logo=google)](https://cloud.google.com/vertex-ai)

## 🎬 Demo

https://github.com/user-attachments/assets/demo

[![Kintsugi-Helix Demo](https://img.youtube.com/vi/e6lkxwWsad8/maxresdefault.jpg)](https://youtu.be/e6lkxwWsad8)

**▶ [ライブデモを試す](https://kintsugi-helix-agent-541617236229.asia-northeast1.run.app/demo/)** — ブラウザからワンクリックで障害回復パイプライン全体をリアルタイムに体験できます。

## 💡 What Makes This Special?

| 特徴 | 説明 |
|------|------|
| **完全自律** | 障害検知 → 根本原因分析 → テスト生成 → 修正 → 検証 → デプロイまで人間の介入ゼロ |
| **Gemini 2.5 Pro** | 根本原因分析・テスト生成・コード修正の3箇所でVertex AIを活用 |
| **安全第一** | Blast Radius分析で影響範囲を定量化し、閾値超えはPRで人間に判断を委ねる |
| **知識の蓄積** | 修正パターンをナレッジベースに保存し、同種の障害に即座に対応 |
| **MCP対応** | Model Context Protocolで外部AI Agentからの呼び出しに対応 |

## 🏗️ Architecture — 5つの柱

```
  NullPointerException発生!
         │
         ▼
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │  👁️ Sensing  │────▶│ 🔬 Reflection│────▶│ 🧬 Evolution │
  │    感知      │     │     反射     │     │     進化     │
  │              │     │              │     │              │
  │ Cloud Logging│     │ テスト自動生成│     │ Geminiが修正 │
  │ + Gemini RCA │     │ Testcontainers│    │ OpenRewrite  │
  └──────────────┘     └──────────────┘     └──────┬───────┘
                                                    │
                              ┌──────────────┐      │
                              │ 📚 Learning  │◀─────┤
                              │    学習      │      │
                              │              │      ▼
                              │ パターン蓄積 │  ┌──────────────┐
                              │ Knowledge DB │  │ 🏛️ Governance│
                              └──────────────┘  │     統治     │
                                                │              │
                                                │ Blast Radius │
                                                │ Auto-Merge   │
                                                └──────────────┘
                                                       │
                                                       ▼
                                                 ✨ 金継ぎ完了
```

| Phase | 機能 | Google Cloud 連携 |
|-------|------|-------------------|
| **Sensing（感知）** | エラー検知 + 根本原因分析 | Cloud Logging → Gemini 2.5 Pro |
| **Reflection（反射）** | バグ再現テスト自動生成・実行 | Gemini 2.5 Pro + Testcontainers |
| **Evolution（進化）** | コード修正 + リファクタリング | Gemini 2.5 Pro + OpenRewrite |
| **Governance（統治）** | 影響範囲分析 + 自動マージ/PR | Gemini 2.5 Pro + GitHub API |
| **Learning（学習）** | 修正パターンのナレッジベース蓄積 | Cloud Storage |

## 🛠️ Tech Stack

| Category | Technology |
|----------|------------|
| **Agent Core** | Python 3.11+, FastAPI, Vertex AI SDK |
| **AI Model** | Gemini 2.5 Pro (RCA, Test Gen, Code Fix) / Flash (Learning) |
| **Target App** | Java 21, Spring Boot 3.2 |
| **Testing** | Testcontainers, JUnit 5, Maven |
| **Refactoring** | OpenRewrite (common-static-analysis) |
| **Infrastructure** | Cloud Run, Cloud Logging, Terraform |
| **Protocol** | MCP (Model Context Protocol) |
| **Demo** | SSE (Server-Sent Events) リアルタイムストリーミング |

## 📁 Project Structure

```
kintsugi-helix/
├── agent-core/                  # Python エージェント本体
│   ├── src/
│   │   ├── sensing/            # 障害検知 & 根本原因分析
│   │   ├── reflection/         # テスト自動生成 & 実行
│   │   ├── evolution/          # コード修正 & リファクタリング
│   │   ├── governance/         # Blast Radius & PR管理
│   │   ├── mcp/               # MCP Server + Demo UI
│   │   └── utils/             # Vertex AI Client, Git操作
│   ├── tests/                  # テストスイート
│   └── config/                 # 設定ファイル
├── target-app/                  # デモ用 Spring Boot アプリ (バグ入り)
├── infrastructure/              # Terraform + デプロイスクリプト
└── articles/                    # Zenn 技術記事
```

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/hatyibei/kintsugi-helix.git
cd kintsugi-helix

# Python環境セットアップ
cd agent-core
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Google Cloud認証
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id

# エージェント起動
python -m src.main --serve --port 8080
```

**デモUI**: http://localhost:8080/demo/ にアクセスして「実行開始」をクリック

## ⚙️ Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_CLOUD_PROJECT` | GCP Project ID | Required |
| `VERTEX_AI_LOCATION` | Vertex AI region | `asia-northeast1` |
| `LOG_FILTER` | Cloud Logging filter | `severity>=ERROR` |
| `AUTO_MERGE_THRESHOLD` | Blast Radius 自動マージ閾値 | `0.3` |
| `GITHUB_TOKEN` | GitHub API token | Required for PRs |

## 📝 License

MIT License

---

**🏆 Built for [第4回 Agentic AI Hackathon with Google Cloud](https://zenn.dev/hackathons/2026-02-google-cloud-japan-ai-hackathon-04) (2026)**
