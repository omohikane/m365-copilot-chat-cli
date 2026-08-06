# AGENTS.md

このリポジトリは、M365 Copilot（社内 `https://m365.cloud.microsoft/chat/conversation`）をログイン済みシステムChromeのセッションを再利用して操作する CLI ツール **m365-copilot-chat-cli**（コマンド名 `copilot-cli`）です。

## エージェントからの利用方法

エージェントが Copilot に質問する手段は2つ。

### 1. MCP サーバー経由（推奨）

opencode など MCP 対応クライアントから、`copilot-cli` MCP サーバーのツールを直接呼べる。登録は opencode の設定（例: `~/.config/opencode/opencode.json`）。

```json
{
  "mcp": {
    "copilot-cli": {
      "type": "local",
      "command": ["<repo>/.venv/bin/copilot-cli", "mcp"]
    }
  },
  "experimental": { "mcp_timeout": 600000 }
}
```

利用可能ツール:

- `copilot_once(prompt)` — 1回だけ質問。単発の問い合わせ向け。戻り値は `{ok, answer, code_blocks}`。
- `copilot_chat(prompts: [str])` — 同一ブラウザ・同一スレッドで複数質問を順に送り、**文脈を引き継いで連続会話**する。前の回答を踏まえた多ターン向け。戻り値は `{ok, turns: [{prompt, answer, code_blocks, tables}]}`。
- `copilot_threads()` — サイドバーの過去スレッドタイトル一覧。戻り値は `{ok, threads}`。

注意:

- 各コールはブラウザを起動し完了後に閉じる（常駐しない）。1ターンで数十秒〜、多ターンで数分かかる。
- `copilot_chat` の複数ターンは1コール内で通すこと。**別コールは別スレッド**になる（文脈は引き継がれない）。
- MCP クライアント側のタイムアウトは十分大きく設定すること（10分推奨）。
- 未ログインの場合は SSO 認証画面が立ち上がり、ブラウザでの手動ログインを待つ（タイムアウト 300s）。

### 2. サブプロセス CLI 経由

`copilot-cli` は任意のディレクトリから呼べる console entry（`uv sync` で `.venv/bin/` にインストール済み）。

```bash
copilot-cli --once '質問'                # 1回だけ送信して回答をstdoutへ
echo 質問 | copilot-cli --once -          # プロンプトをstdinから受ける
copilot-cli --once '質問' --json --no-log # JSON出力（他エージェント向け）
printf '質問1\n質問2\n' | copilot-cli --listen --json  # 同一スレッドで連続会話
copilot-cli --threads --json             # 過去スレッド一覧
copilot-cli --resume 0 --json            # 過去スレッドを開く（ベストエフォート）
```

`--once` の JSON は `{prompt, answer, code_blocks, log_path}`。失敗時は `{ok: false, error}` を返し exit code 1。

## 開発メモ

- 実装: `app.py`（CLI/エントリ）、`copilot_agent.py`（Playwright 操作の中核）、`mcp_server.py`（MCP サーバー）、`config.py`、`logger.py`、`code_exec.py`
- ログイン状態の Chrome プロファイルは `~/.copilot-cli/chrome-profile`。起動時の自己修復（stale process の掃除 + リトライ）あり。
- ブラウザ常駐型の長時間セッションは不安定。呼び出しごとに起動/終了する使い方（`--once`/`copilot_chat`）が安定。
- 設計思想は [DESIGN.md](DESIGN.md)、進捗は [TODO.md](TODO.md) を参照。
