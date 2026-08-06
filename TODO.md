# copilot-cli 実装TODO

## Phase 1: セットアップ（開発機）
- [x] `copilot-cli/` ディレクトリ作成、`git init`
- [x] `.gitignore`（`log/`, `.venv/`, `__pycache__/`, `.env`, `config.ini`）
- [x] `pyproject.toml`（uv, dependencies: playwright）
- [x] `uv sync` で検証環境構築

## Phase 2: コア実装
- [x] `config.py`（URL, パス, セレクタ定義, タイムアウト）
- [x] `copilot_agent.py`
  - [x] Chrome起動（`channel="chrome"`, `user_data_dir`, headed/headless）
  - [x] 送信（入力→送信ボタン）
  - [x] 完了待ち（インジケータの状態検知＋タイムアウト）
  - [x] 回答本文・コードブロック抽出
  - [x] 同一タブでの連続送信（会話継続）
- [x] `logger.py`（markdown追記・`!save`）
- [x] `code_exec.py`（`!run` 確認ゲート＋実行）
- [x] `app.py`（REPLループ、コマンド解釈、エラー処理）

## Phase 3: DOM調査・セレクタ確定（対象機で実施）
- [x] Chatページを実開き、送信ボックス/送信ボタン/回答コンテナ/送信中インジケータのセレクタを特定
- [x] `config.py` の `SELECTORS` に反映
      - 入力欄: `[contenteditable='true']` / 送信: `button[aria-label='Send']` / busy: `button[aria-label='Stop generating']` / 回答: `[data-testid='markdown-reply']`

## Phase 4: 検証
- [x] 起動→プロンプト送信→回答抽出→`log/*.md` 保存確認
- [x] 同一スレッド複数通送（長対話: 2往復連続）
- [x] `!run` で安全なコード（例 `echo`）の確認ゲート動作（承認/拒否/非実行言語）
- [x] `!headless`/`!headed` 切替動作
- [x] `!new` 新規会話タブ
- [x] コードエディタウィジェット（``` フェンスなし）の回答からコードを抽出 → `code_blocks`/`!run` へ統合
- [x] 回答内の表を markdown テーブルとして抽出（`last_tables`）: 実DOM `<table>` + コードウィジェットの markdown ソース両対応
- [x] ブラウザ起動の自己修復（残存プロセス/ロック掃除 + リトライ）
- [x] 過去スレッド一覧（`!threads`）・復元（`!resume`、best-effort）+ スレッド全文保存（`!save all`）
- [x] CLI entry-point化（`copilot-cli`、cwd非依存）+ `--once`/`--threads`/`--resume` 非対話 + stdin入力（`--once -`）
- [x] `--listen`（stdin駆動・同一スレッドで連続会話、`--json` NDJSON対応）
- [ ] Windows での動作確認（後日）

## Phase 5: ドキュメント・引継ぎ
- [ ] `README.md`（セットアップ手順・使い方・セレクタ保守手順）
- [ ] 共有ドライブ移送用のパッケージ化（zip等）手順
- [ ] 保守メモ（UI変更時のセレクタ更新手順）
