<div align="center">
  <h1>Bigbrain</h1>
  <p><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <strong>日本語</strong> · <a href="README.ko.md">한국어</a> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a> · <a href="README.pt-BR.md">Português (Brasil)</a></p>
  <p>
    <a href="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-64748b.svg"></a>
    <a href="https://www.python.org/"><img alt="Python standard library" src="https://img.shields.io/badge/Python-stdlib_only-3776ab.svg"></a>
  </p>
</div>

Codex のチャットに Claude を招き、計画や原因の診断を相談できます。コードの編集、検証、最初のレビューは Codex が担当します。別の視点が必要になったら、追加のレビューを依頼できます。

![実装は Codex。考えるときは Claude と。](docs/assets/hero.en.png)

**各チャットでは初期状態で無効です。明示的に有効にしてください。** 有効化後は難しいタスクで Claude に計画や診断を依頼できます。**Claude によるコードの追加レビューには、別途明示的な依頼が必要です。**

## Bigbrain が役立つ場面

| 困っていること | Bigbrain の役割 |
|---|---|
| 大きな変更の前に方針を固めたい | 曖昧な要件を、検証可能な完了条件を持つマイルストーンに分けます。 |
| 何度試しても同じ問題で止まる | 失敗した試みと証拠を Claude に渡し、次の方針を診断します。 |
| 文脈を引き継ぎ、利用状況も把握したい | タスクごとの Claude セッション、ローカルの知見、顧問モデルの推定費用を保持します。 |

## 使い始める

Codex、Python 3、ログイン済みで `--safe-mode` に対応する Claude Code CLI が必要です（検証済み：2.1.310）。Bigbrain 自体は Python 標準ライブラリのみを使います。以下のコマンドはクローンしたリポジトリ内で実行します。

```bash
git clone https://github.com/kangchainx/bigbrain-skill.git
cd bigbrain-skill
./install.sh --no-setup
python3 scripts/bigbrain_cli.py setup --claude-code
python3 scripts/check_config.py --no-call --json
```

未ログインなら、先に `claude auth login` を実行してください。セットアップはバックエンドを選択します。呼び出しなしのチェックはログイン状態のみを確認し、モデルへのアクセスは最初の実際の呼び出しで確認します。

その後、Codex のチャットで次のように伝えます：

> このチャットで Bigbrain を有効にしてください。実装の前に、この変更の計画を手伝ってください。

停止するには **「このチャットの Bigbrain を無効にして」** と伝えます。同じチャットの再開では状態を保持しますが、新規・分岐したチャットは無効から始まります。インストールだけでは有効になりません。

<details>
<summary>その他のインストール方法</summary>

skills CLI ではインストール先に Codex を選びます。その後、Codex に Claude Code 用の Bigbrain 設定を依頼してください。クローン先を仮定せず、実際にインストールされたスキルのパスを使います。

```bash
npx skills add kangchainx/bigbrain-skill
```

リポジトリ内で `./install.sh --copy` を使うと、シンボリックリンクの代わりにコピーします。`--claude` は Claude Code にもインストールし、`--dir PATH` は保存先を指定します。既定は `${CODEX_HOME:-$HOME/.codex}/skills/bigbrain` です。リンクでインストールした場合はリポジトリを移動・削除しないでください。

</details>

## 一つのタスク、明確な役割

![役割と流れを示す模式図](docs/assets/flow.en.png)

<p align="center"><a href="docs/assets/demo.en.mp4"><img src="docs/assets/demo.en.gif" alt="音楽付きの24秒の会話を見る（MP4）。台本によるデモ。" width="960"></a></p>

[音楽付きの24秒の会話を見る（MP4）。台本によるデモ。](docs/assets/demo.en.mp4)

*役割と流れを示す模式図*

1. **明示的に有効化。** 複雑なタスクだけでは、無効なチャットで Bigbrain は起動しません。
2. **必要なときに Claude。** 有効なチャットでは計画のスコアが `0.6` を超えると顧問に相談します。明示的な相談依頼でも起動でき、簡単な作業は Codex が担当します。
3. **実装と最初のレビューは Codex。** ファイル編集、検証、コードの初回レビューを担当します。Claude の追加レビューには明示的な依頼が必要です。
4. **証拠を引き継ぐ。** フィードバックによりタスクを再開し、診断後に新たな検証結果を提出できます。顧問の呼び出しにはトークン数と推定費用が記録されます。

## 顧問のバックエンドを選ぶ

|  | Claude Code · 推奨 | Messages API · 選択肢 |
|---|---|---|
| 認証 | Claude Code のログイン | プロバイダーの API キー |
| モデル | `BIGBRAIN_CLAUDE_MODEL`（既定：`opus`） | `BIGBRAIN_MODEL`（既定：`claude-opus-5-5`） |
| 文脈 | タスクごとの永続セッション。Read/Glob/Grep のみ | Codex が提供する文脈 |
| 費用 | Claude Code が返す推定値 | 返された使用量 × 設定した単価 |

既存タスクは開始時のバックエンドとモデルを保持します。バックエンド未指定の旧設定は互換性のため `api` を使います。**別のバックエンドへ自動で切り替えません。** モデルの利用可否はアカウントやエンドポイント次第です。

<details>
<summary>Messages API を設定する</summary>

リポジトリ内で下記を実行し、ローカルフォームを開きます。HTTPS エンドポイント、API キー、モデルはフォームに入力し、チャットにはキーを貼らないでください。モデル一覧を取得し、実際の生成が成功した場合のみ保存します。

```bash
python3 scripts/bigbrain_cli.py setup --web
```

ストリーミングと一時的なエラーの再試行は API バックエンドのみです。プロバイダーは指定モデルと thinking/effort パラメーターに対応する必要があります。Anthropic 形式の JSON 対応だけでは十分ではありません。`BIGBRAIN_BASE_URL` の末尾に `/v1` は付けません。環境変数が保存済み設定より優先されます。[設定資料](references/config.md)を参照してください。

</details>

## 自分で管理できるセッション

- **役割を分離。** Claude Code 顧問のツールは Read/Glob/Grep に限定されます。編集とテストは Codex が行います。
- **ローカルの状態。** 知見は `~/.bigbrain/experience/`、タスク記録はワークスペースの `.bigbrain/` に保存されます。関連する文脈や画像は選択した顧問に送信されます。ローカル保存はオフライン推論を意味しません。
- **グローバル指示を変更しません。** `AGENTS.md`、`CLAUDE.md`、Codex/Claude のグローバル設定は変更せず、Bigbrain 独自の設定を保存します。
- **使用量を表示。** 費用は推定値で、請求書やサブスクリプションへの実際の課金を証明するものではありません。使用量の欠落は明示します。節約率にも実行側トークンの推定が含まれ、ベンチマークではありません。

## 手動で使う

通常は Codex が操作します。以下はリポジトリ内でチャットの状態や既存タスクを確認するコマンドで、顧問は呼び出しません。

```bash
python3 scripts/bigbrain_cli.py mode status
python3 scripts/bigbrain_cli.py status --session .bigbrain/my-task
```

<details>
<summary>詳細：顧問のマイルストーンループ</summary>

明示的に有効化した後、一つのタスクに同じセッションディレクトリを使い続けます。以下は顧問を呼び出します。`m1.md` には実際の結果と検証の証拠を記載してください。

```bash
python3 scripts/bigbrain_cli.py mode on
python3 scripts/bigbrain_cli.py lessons list --limit 10
python3 scripts/bigbrain_cli.py start --task "..." --user-request --effort medium --session .bigbrain/my-task
python3 scripts/bigbrain_cli.py report --session .bigbrain/my-task --result-file m1.md
python3 scripts/bigbrain_cli.py feedback --session .bigbrain/my-task --reason "..."
```

顧問のループでは、すべての完了条件が満たされたと記録されて初めて `done` を受理します。Codex 単独のコードレビューに Claude の承認を義務付けるものではありません。既定は 8 ラウンド、推論強度は `medium`（`high`、`xhigh` も可）です。終了時は通常、振り返りの呼び出しも行います。終了コード：`0` 続行または `DONE`、`10` ブロック、`11` ラウンド上限、`12` 修復後も JSON が無効、`2`–`6` 設定・プロバイダーのエラー。

</details>

<details>
<summary>任意：Codex プラグインの hooks</summary>

リポジトリにはローカルのプラグインマーケットプレイスが含まれます。以下で登録後、Codex で hooks を確認して信頼してください。重複検出を避けるため単体スキルを無効化します。スキルのインストーラーは hooks を登録・信頼しません。

```bash
codex plugin marketplace add /absolute/path/to/bigbrain-skill
codex plugin add bigbrain@bigbrain-local
```

SessionStart と UserPromptSubmit は、有効なチャットでのみ協作ルールを通知します。Hooks はモデルを呼ばず、すべての対話ルールを強制できるわけではありません。[協作ルール](references/collaboration.md)と[セッション復旧](references/native-sessions.md)を参照してください。

</details>

## よくある質問

**毎回 Claude を呼びますか？**

いいえ。無効時は新しい顧問呼び出しを開始しません。有効時も簡単な作業は Codex だけで行えます。無効化しても実行中の呼び出しは中断しません。

**モデルなしで試せますか？**

リポジトリ内で `bash examples/minimal/run.sh` を実行します。事前に用意された応答による仕組みのデモで、実際のレビューではありません。

**コードを検証するには？**

`bash tests/run_tests.sh` を実行します。一時ディレクトリとローカルのモックを使い、実際のプロバイダーは呼びません。

**アンインストールするには？**

リポジトリ内で `./install.sh --uninstall` を実行します。知見は残ります。ユーザー単位の Bigbrain 保存領域も削除したい場合のみ `--purge` を追加します。

## 詳しく見る

[設定とバックエンド](references/config.md) · [相談の判定ルール](references/triggers.md) · [セッションと復旧](references/native-sessions.md) · [ローカルの知見](references/experience.md) · [オフライン費用監査](references/session-audit.md) · [貢献する](CONTRIBUTING.md)

---

作成者：**Chris Kang**（[@kangchainx](https://github.com/kangchainx)）。

[MIT](LICENSE) · © 2026 Chris Kang。Bigbrain を利用したプロジェクトでは、このリポジトリへのリンクを歓迎します。
