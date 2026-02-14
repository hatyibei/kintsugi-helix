# Kintsugi-Helix デモ動画スクリプト

**目標尺: 2分30秒**  
**録画方法**: ブラウザでデモUIを操作 + ナレーション（テロップ）  
**ツール**: OBS Studio / 画面録画

---

## 構成

### 00:00 - 00:15 | タイトル & コンセプト
**画面**: タイトルカード（背景ダーク、金箔テクスチャ）

```
🔧 Kintsugi-Helix
自律型障害回復AIエージェント
Powered by Vertex AI Gemini 2.5 Pro
```

**テロップ**: 「壊れた部分を金で修復し、より美しく仕上げる — 金継ぎの哲学をソフトウェアに適用」

---

### 00:15 - 00:30 | Cloud Run デプロイ確認
**画面**: ブラウザで以下にアクセス
1. `https://kintsugi-helix-agent-541617236229.asia-northeast1.run.app/health` → JSON表示
2. `https://kintsugi-helix-agent-541617236229.asia-northeast1.run.app/demo/` → ダッシュボード表示

**テロップ**: 「Cloud Run上にデプロイ済み。MCPサーバーとして稼働中。」

---

### 00:30 - 00:50 | Phase 1: Sensing（感知）
**画面**: デモダッシュボードで「▶ デモを実行」をクリック

**見せるポイント**:
- Cloud Loggingからエラーログを検出する流れ
- NullPointerExceptionの詳細表示
- Root Cause Analysisの結果 (Gemini 2.5 Pro)

**テロップ**: 
- 「Cloud Loggingからエラーを自動検出」
- 「Gemini 2.5 Proが根本原因を分析：信頼度95%」

---

### 00:50 - 01:10 | Phase 2: Reflection（反射）
**画面**: SSEストリーミングが進行

**見せるポイント**:
- JUnitテスト自動生成
- 「バグ再現成功！」表示

**テロップ**: 
- 「AIがバグ再現テストを自動生成」
- 「Testcontainersで実行：NullPointerException再現成功 ✅」

---

### 01:10 - 01:30 | Phase 3: Evolution（進化）
**画面**: コード修正のdiff表示

**見せるポイント**:
- `Optional.orElse(null)` → `Optional.orElseThrow()` の修正diff
- 修正後のテスト結果：全12テストパス
- OpenRewriteによる追加改善

**テロップ**: 
- 「Geminiがコード修正を生成・適用」
- 「全テストパス ✅ リグレッションなし」

---

### 01:30 - 01:50 | Phase 4: Governance（統治）
**画面**: Blast Radius分析結果

**見せるポイント**:
- リスクスコア: 0.25 (LOW)
- 自動マージ判定
- git commitメッセージ

**テロップ**: 
- 「影響範囲分析：リスクスコア0.25 → 自動マージ承認」
- 「低リスク修正は即座に適用、高リスクは人間レビューへ」

---

### 01:50 - 02:10 | Phase 5: Learning（免疫記憶）
**画面**: Learning Memory更新表示

**見せるポイント**:
- バグパターンの学習記録
- 類似リスクの自動検出
- KNOWLEDGE_BASE.json更新

**テロップ**: 
- 「修正経験を学習メモリに記録」
- 「同種のバグを次回以降、より早く修正」

---

### 02:10 - 02:30 | サマリー & まとめ
**画面**: 完了バナー + サマリー統計

**見せるポイント**:
- 「✨ 金継ぎ完了」バナー
- Stats: 1 incident → 1 bug confirmed → 1 fix → auto-merged → 1 learning

**テロップ**: 
```
Kintsugi-Helix — 障害を「金」に変えるAIエージェント

✅ 障害検知 → 原因分析 → テスト生成 → コード修正 → 影響分析 → 自動マージ → 学習
すべて人間の介入なし。

Powered by Google Cloud
Vertex AI Gemini 2.5 Pro | Cloud Logging | Cloud Run
```

---

## 録画手順

1. OBS Studioを起動（1920x1080、30fps）
2. ブラウザでデモURL(`/demo/`)を開く
3. 録画開始
4. 「▶ デモを実行」ボタンをクリック
5. SSEストリーミングが完了するまで待機（約45秒）
6. 完了バナー表示後、3秒待って録画停止
7. テロップを動画編集ソフトで追加（ClipChamp等）
8. YouTubeにアップロード
9. 記事の`PLACEHOLDER_VIDEO_ID`をYouTube動画IDに置換

## 注意事項
- SSEストリーミングは実際のサーバーから配信される
- Gemini APIの呼び出しはデモシナリオ（事前計算結果）を使用
- デモは何度でも再実行可能
