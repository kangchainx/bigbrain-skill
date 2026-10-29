<div align="center">
  <h1>Bigbrain</h1>
  <p><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <strong>한국어</strong> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a> · <a href="README.pt-BR.md">Português (Brasil)</a></p>
  <p>
    <a href="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-64748b.svg"></a>
    <a href="https://www.python.org/"><img alt="Python standard library" src="https://img.shields.io/badge/Python-stdlib_only-3776ab.svg"></a>
  </p>
</div>

Codex 채팅에서 Claude와 계획을 세우고 원인을 진단하세요. 코드 작성, 검사 실행, 첫 리뷰는 Codex가 담당합니다. 다른 관점이 필요할 때 추가 리뷰를 요청할 수 있습니다.

![구현은 Codex, 함께 고민할 때는 Claude.](docs/assets/hero.en.png)

**각 채팅에서는 기본적으로 꺼져 있으며 직접 활성화해야 합니다.** 활성화 후 어려운 작업은 Claude의 계획이나 진단을 호출할 수 있습니다. **Claude의 코드 2차 리뷰는 명시적으로 요청해야 합니다.**

## Bigbrain이 필요한 순간

| 상황 | Bigbrain의 역할 |
|---|---|
| 영향이 큰 변경 전에 계획이 필요할 때 | 모호한 요구사항을 검증 가능한 완료 기준이 있는 단계로 나눕니다. |
| 같은 문제에서 반복해서 막힐 때 | 실패한 시도와 증거를 Claude에게 전달해 다음 접근법을 진단합니다. |
| 맥락을 유지하고 사용량도 확인하고 싶을 때 | 작업별 Claude 세션, 로컬 경험, 자문 모델의 예상 비용을 유지합니다. |

## 시작하기

Codex, Python 3, 로그인되어 있고 `--safe-mode`를 지원하는 Claude Code CLI가 필요합니다(테스트 버전: 2.1.310). Bigbrain 자체는 Python 표준 라이브러리만 사용합니다. 다음 명령은 복제한 저장소에서 실행합니다.

```bash
git clone https://github.com/kangchainx/bigbrain-skill.git
cd bigbrain-skill
./install.sh --no-setup
python3 scripts/bigbrain_cli.py setup --claude-code
python3 scripts/check_config.py --no-call --json
```

로그인하지 않았다면 먼저 `claude auth login`을 실행하세요. 설정은 백엔드를 선택합니다. 무호출 검사는 로그인만 확인하며 모델 접근과 생성 가능 여부는 첫 실제 자문 호출에서 확인합니다.

그다음 Codex 채팅에 다음과 같이 입력하세요:

> 이 채팅에서 Bigbrain을 활성화해 줘. 구현하기 전에 이번 변경의 계획을 세워 줘.

중지하려면 **“이 채팅에서 Bigbrain을 꺼 줘”**라고 말하세요. 같은 채팅을 재개하면 상태가 유지되지만 새 채팅이나 분기한 채팅은 꺼진 상태로 시작합니다. 설치만으로 활성화되지는 않습니다.

<details>
<summary>다른 설치 방법</summary>

skills CLI에서는 Codex를 대상으로 선택하세요. 이후 Codex에 Claude Code용 Bigbrain 설정을 요청하세요. 저장소가 있다고 가정하지 않고 실제 설치된 스킬 경로를 사용해야 합니다.

```bash
npx skills add kangchainx/bigbrain-skill
```

저장소에서 `./install.sh --copy`를 실행하면 심볼릭 링크 대신 복사합니다. `--claude`는 Claude Code에도 설치하고 `--dir PATH`는 경로를 지정합니다. 기본값은 `${CODEX_HOME:-$HOME/.codex}/skills/bigbrain`입니다. 심볼릭 링크로 설치했다면 저장소를 유지하세요.

</details>

## 하나의 작업, 명확한 역할

![역할과 진행 과정을 보여 주는 개념도](docs/assets/flow.en.png)

<p align="center"><a href="docs/assets/demo.en.mp4"><img src="docs/assets/demo.en.gif" alt="음악이 포함된 24초 대화 보기(MP4). 각본으로 만든 데모입니다." width="960"></a></p>

[음악이 포함된 24초 대화 보기(MP4). 각본으로 만든 데모입니다.](docs/assets/demo.en.mp4)

*역할과 진행 과정을 보여 주는 개념도*

1. **직접 활성화합니다.** 복잡한 작업이라는 이유만으로 꺼진 채팅에서 Bigbrain이 켜지지 않습니다.
2. **필요할 때 Claude에게 자문합니다.** 활성화된 채팅에서 계획 점수가 `0.6`을 넘으면 자문을 요청하며, 명시적 자문 요청으로도 호출할 수 있습니다. 단순 작업은 Codex가 처리합니다.
3. **Codex가 구현하고 먼저 리뷰합니다.** 파일 편집, 검사, 첫 코드 리뷰를 담당합니다. Claude의 2차 리뷰에는 명시적 요청이 필요합니다.
4. **증거를 이어 갑니다.** 피드백으로 작업을 다시 열어 진단하고 새 검증 결과를 제출할 수 있습니다. 자문 호출의 토큰과 예상 비용을 기록합니다.

## 자문 백엔드 선택

|  | Claude Code · 권장 | Messages API · 대안 |
|---|---|---|
| 인증 | Claude Code 자체 로그인 | 제공업체의 API 키 |
| 모델 | `BIGBRAIN_CLAUDE_MODEL` (기본: `opus`) | `BIGBRAIN_MODEL` (기본: `claude-opus-5-5`) |
| 맥락 | 작업별 영구 세션, Read/Glob/Grep만 사용 | Codex가 제공하는 맥락 |
| 비용 | Claude Code가 반환한 추정치 | 반환 사용량 × 설정한 토큰 단가 |

기존 작업은 시작 당시의 백엔드와 모델을 유지합니다. 백엔드가 없는 기존 설정은 호환성을 위해 `api`를 사용합니다. **백엔드가 조용히 전환되지는 않습니다.** 모델 사용 가능 여부는 계정이나 엔드포인트에 달려 있습니다.

<details>
<summary>Messages API 설정</summary>

저장소에서 아래 명령으로 로컬 설정 폼을 여세요. HTTPS 엔드포인트, API 키, 모델은 폼에 입력하고 키를 채팅에 붙여 넣지 마세요. 모델 목록을 조회하고 실제 생성 검사를 통과한 뒤에만 저장합니다.

```bash
python3 scripts/bigbrain_cli.py setup --web
```

스트리밍과 일시적 오류 재시도는 API 백엔드에만 적용됩니다. 제공업체가 모델과 thinking/effort 매개변수를 지원해야 합니다. Anthropic 형식의 JSON만 지원한다고 호환성이 보장되지는 않습니다. `BIGBRAIN_BASE_URL` 끝에 `/v1`을 붙이지 마세요. 환경 변수가 저장된 설정보다 우선합니다. [설정 문서](references/config.md)를 참고하세요.

</details>

## 직접 관리하는 세션

- **역할 분리.** Claude Code 자문 도구는 Read/Glob/Grep로 제한됩니다. 편집과 테스트는 Codex가 실행합니다.
- **로컬 상태.** 경험은 `~/.bigbrain/experience/`, 작업 기록은 작업 공간의 `.bigbrain/`에 저장됩니다. 관련 맥락과 이미지 첨부는 선택한 자문 모델로 전송됩니다. 로컬 저장이 오프라인 추론을 뜻하지는 않습니다.
- **전역 지침 유지.** Bigbrain은 `AGENTS.md`, `CLAUDE.md`, Codex/Claude 전역 설정을 수정하지 않습니다. 자체 설정만 저장합니다.
- **사용량 표시.** 비용은 추정치이며 청구서나 실제 구독 과금의 증거가 아닙니다. 누락된 사용량은 표시합니다. 절감률에도 실행 모델 토큰 추정이 포함되므로 벤치마크가 아닙니다.

## 직접 명령 실행하기

보통 Codex가 절차를 실행합니다. 다음 명령은 저장소에서 채팅 상태나 기존 작업을 조회하며 자문 모델을 호출하지 않습니다.

```bash
python3 scripts/bigbrain_cli.py mode status
python3 scripts/bigbrain_cli.py status --session .bigbrain/my-task
```

<details>
<summary>고급: 자문 단계 반복</summary>

명시적으로 활성화한 뒤 작업마다 같은 세션 디렉터리를 사용하세요. 아래 명령은 자문 모델을 호출합니다. `m1.md`에는 실제 결과와 검증 증거가 있어야 합니다.

```bash
python3 scripts/bigbrain_cli.py mode on
python3 scripts/bigbrain_cli.py lessons list --limit 10
python3 scripts/bigbrain_cli.py start --task "..." --user-request --effort medium --session .bigbrain/my-task
python3 scripts/bigbrain_cli.py report --session .bigbrain/my-task --result-file m1.md
python3 scripts/bigbrain_cli.py feedback --session .bigbrain/my-task --reason "..."
```

자문 반복에서는 모든 완료 기준이 충족된 것으로 표시되어야 `done`을 수락합니다. Codex 단독 코드 리뷰에 Claude의 승인이 필수라는 뜻은 아닙니다. 기본 최대 8라운드, 추론 강도는 `medium`이며 `high`, `xhigh`도 지원합니다. 종료 시 보통 회고 호출이 추가됩니다. 종료 코드: `0` 계속 또는 `DONE`, `10` 차단, `11` 라운드 소진, `12` 수정 후에도 잘못된 JSON, `2`–`6` 설정 또는 제공업체 오류.

</details>

<details>
<summary>선택 사항: Codex 플러그인 hooks</summary>

저장소에 로컬 플러그인 마켓플레이스가 포함되어 있습니다. 아래 명령으로 등록한 뒤 Codex에서 hooks를 검토하고 신뢰하세요. 중복 검색을 피하려면 독립 스킬 항목을 비활성화하세요. 스킬 설치기는 hooks를 등록하거나 신뢰하지 않습니다.

```bash
codex plugin marketplace add /absolute/path/to/bigbrain-skill
codex plugin add bigbrain@bigbrain-local
```

SessionStart와 UserPromptSubmit은 활성화된 채팅에서만 협업 규칙을 알립니다. Hooks는 모델을 호출하지 않으며 모든 대화 규칙을 강제하지는 못합니다. [협업 규칙](references/collaboration.md)과 [세션 복구](references/native-sessions.md)를 참고하세요.

</details>

## 자주 묻는 질문

**매번 Claude를 호출하나요?**

아니요. 꺼져 있으면 새 자문 호출을 시작하지 않습니다. 활성화 후에도 단순한 작업은 Codex만으로 처리할 수 있습니다. 꺼도 이미 실행 중인 요청은 중단되지 않습니다.

**모델 없이 체험할 수 있나요?**

저장소에서 `bash examples/minimal/run.sh`를 실행하세요. 미리 준비된 응답으로 동작을 보여 주며 실제 리뷰가 아닙니다.

**코드는 어떻게 검사하나요?**

`bash tests/run_tests.sh`를 실행하세요. 임시 디렉터리와 로컬 모의 서비스를 사용하며 실제 제공업체는 호출하지 않습니다.

**제거하려면 어떻게 하나요?**

저장소에서 `./install.sh --uninstall`을 실행하세요. 경험은 유지됩니다. 사용자 수준 Bigbrain 저장소도 삭제할 때만 `--purge`를 추가하세요.

## 더 알아보기

[설정과 백엔드](references/config.md) · [자문 판단 규칙](references/triggers.md) · [세션과 복구](references/native-sessions.md) · [로컬 경험](references/experience.md) · [오프라인 비용 감사](references/session-audit.md) · [기여하기](CONTRIBUTING.md)

---

**Chris Kang**([@kangchainx](https://github.com/kangchainx))이 만들었습니다.

[MIT](LICENSE) · © 2026 Chris Kang. Bigbrain을 기반으로 프로젝트를 만들었다면 이 저장소로 링크해 주세요.
