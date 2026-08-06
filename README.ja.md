# m365-copilot-chat-cli

M365 Copilot（社内 `https://m365.cloud.microsoft/chat/conversation`）を、ログイン済みシステムChromeのセッションを再利用してCLIから操作するREPLツール。

詳細な設計は [DESIGN.md](DESIGN.md)、進捗は [TODO.md](TODO.md) を参照。

## セットアップ

```bash
uv sync
uv run python app.py
```

## CLI からの利用（非対話・agent 向け）

`copilot-cli` は任意のディレクトリから呼べる console entry（`uv sync` で `.venv/bin/` にインストール）。

```bash
copilot-cli --once '質問'                # 1回だけ送信して回答をstdoutへ
echo 質問 | copilot-cli --once -          # プロンプトをstdinから受ける
copilot-cli --once '質問' --json --no-log # JSON出力（他エージェント向け）
printf '質問1\n質問2\n' | copilot-cli --listen --json  # 同一スレッドで連続会話
copilot-cli --threads --json             # 過去スレッド一覧
copilot-cli --resume 0 --json            # 過去スレッドを開く（ベストエフォート）
```

`--once` の JSON は `{prompt, answer, code_blocks, log_path}`。失敗時は `{ok: false, error}` を返し exit code 1。

## 使い方（設計・実装中）

- `!run` — 直近のコードブロックを確認後実行（フェンス形式・コードエディタウィジェットの両方を抽出）
- `!save <名前>` — 直近の回答を別markdownとして保存
- `!new` — 新しい会話スレッド
- `!threads` — 過去スレッド一覧
- `!resume <番号|名前>` — 過去スレッドを開く（サイドバー依存のため動作はベストエフォート）
- `!save all [名前]` — 現在スレッドの全文を `log/` に保存
- `!model <名前>` — モデル選択（例 `!model GPT` / `!model Claude`）
- `!models` — 利用可能モデルの一覧・現在の表示モード
- `!headless` / `!headed` — 表示モード切替
- `!quit` — 終了
