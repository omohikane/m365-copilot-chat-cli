# m365-copilot-chat-cli 設計書（v1）

## 1. 目的
ログイン済みChromeのセッションを再利用して、`https://m365.cloud.microsoft/chat/conversation` （M365 Copilot）をCLIから操作する。ターミナルで対話→回答・コードをローカル保存→明示実行→継続、という**REPLループ**を提供。機密情報を外部に漏らさない（ログイン済みの Chrome とローカル保存のみ）。

## 2. アーキテクチャ
```
[PowerShell/ターミナル]
      │ 入力 / 出力表示
      ▼
 app.py (REPLループ)
      │
      ▼
 copilot_agent.py ── Playwright ──▶ システムChrome (persistent profile)
      │                                    └ SSOログイン再利用
      │
      ├─▶ logger.py ──▶ log/YYYYMMDD-<title>.md  (逐次追記・非コミット)
      └─▶ code_exec.py ──▶ !run（対象確認→ローカル実行→結果を会話に）
```

## 3. ファイル構成
| ファイル | 責務 |
|---|---|
| `app.py` | REPLメイン。コマンド解釈（`!run` `!save` `!new` `!quit`）、対話ループ |
| `copilot_agent.py` | Playwright制御。起動(persistent profile, headed既定/headless切替)、送信、完了待ち、回答+コードブロック抽出 |
| `code_exec.py` | コードブロック抽出、`!run` 実行（対象確認ゲート付き） |
| `logger.py` | markdownログ逐次追記、`!save` での生成物保存 |
| `config.py` | 設定集約（URL, user-data-dir, 保存先, セレクタ, タイムアウト） |
| `pyproject.toml` | uv管理（playwright, click） |
| `README.md` | セットアップ・使い方・保守手順 |
| `.gitignore` | `log/`, `.venv/`, `__pycache__/`, `.env`, `config.ini` 除外 |

## 4. 動作フロー
1. `uv run python app.py` 起動 → Chrome起動（persistent profile、ログイン済み）→ Chatページ表示
2. ユーザ入力（`>` プロンプト）→ 送信ボックスに入力・送信
3. **完了待ち**（送信中→完了の状態変化をセレクタで検知、タイムアウト付き）
4. 回答全文＋コードブロックを抽出 → 表示 ＋ `log/*.md` 追記
5. 同一タブを保持して連続送信（長対話）。リロードしない
6. `!run` → 最後のコードブロックを対象確認後、ローカル実行 → 結果表示
7. `!quit` で終了（ブラウザも閉じる）

## 5. REPLコマンド
- `!run` — 直近のコードブロックを確認後実行
- `!save <名前>` — 直近の回答を別markdownとして保存
- `!new` — 新しい会話スレッド（新規タブ/新規会話）
- `!headless` / `!headed` — 表示モード切替
- `!quit` — 終了

## 6. 設定（config.py）
- `CHAT_URL` = `https://m365.cloud.microsoft/chat/conversation`
- `USER_DATA_DIR` = `~/.copilot-cli/chrome-profile`（persistent profile）
- `LOG_DIR` = `./log`（.gitignore対象）
- `HEADED` = True（既定）
- `TIMEOUT_SEC` = 回答待ち上限（例 120s）
- `SELECTORS` = 送信ボックス/送信ボタン/回答コンテナ/送信中インジケータ（DOM調査後に確定）

## 7. セキュリティ・秘匿
- ブラウザは**システムChrome**（`channel="chrome"`）を使用 → `playwright install` 不要、SSO再利用
- 会話ログ `log/` は **git非コミット・共有ドライブに載せない**（ローカル限定）
- 生成コードの実行は **`!run` 明示＋対象確認のみ**。自動実行しない
- 保存先はローカルディレクトリのみ
- ブラウザDL不可環境でも動作（システムChrome経由）

## 8. 環境前提
- 対象機: **Linux（GUI付き, Chrome導入済み）** または Windows
- Python 3.10+, **uv**（未導入なら導入する）
- 手元の開発機でもコードは動く（検証は安全な範囲で）
