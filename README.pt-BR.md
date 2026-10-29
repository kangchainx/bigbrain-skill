<div align="center">
  <h1>Bigbrain</h1>
  <p><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · <a href="README.es.md">Español</a> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a> · <strong>Português (Brasil)</strong></p>
  <p>
    <a href="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-64748b.svg"></a>
    <a href="https://www.python.org/"><img alt="Python standard library" src="https://img.shields.io/badge/Python-stdlib_only-3776ab.svg"></a>
  </p>
</div>

Traga o Claude para seu chat do Codex para planejar e diagnosticar problemas. O Codex escreve o código, executa as verificações e faz a primeira revisão. Você decide quando pedir uma segunda opinião.

![Codex implementa. Claude ajuda a pensar.](docs/assets/hero.en.png)

**Desativado por padrão; a ativação é por chat.** Depois de ativado, tarefas difíceis podem chamar o Claude para planejamento ou diagnóstico. **A segunda revisão de código pelo Claude é opcional e exige um pedido explícito.**

## Quando usar o Bigbrain

| Você precisa de… | O Bigbrain ajuda com… |
|---|---|
| Um plano antes de uma mudança de alto impacto | Requisitos claros, divididos em etapas com critérios de aceitação verificáveis. |
| Uma saída após várias tentativas frustradas | Diagnóstico do Claude a partir das tentativas anteriores e das evidências. |
| Continuidade sem perder o controle | Uma sessão do Claude por tarefa, aprendizados locais e estimativas visíveis do custo do consultor. |

## Comece aqui

Você precisa do Codex, Python 3 e Claude Code CLI autenticado, com suporte a `--safe-mode` (testado com 2.1.310). O Bigbrain usa apenas a biblioteca padrão do Python. Execute os comandos abaixo no repositório clonado.

```bash
git clone https://github.com/kangchainx/bigbrain-skill.git
cd bigbrain-skill
./install.sh --no-setup
python3 scripts/bigbrain_cli.py setup --claude-code
python3 scripts/check_config.py --no-call --json
```

Se ainda não estiver autenticado, execute primeiro `claude auth login`. A configuração seleciona o backend. A verificação sem chamada confirma o login, não o acesso ao modelo; a primeira chamada real valida a geração.

Em seguida, diga no chat do Codex:

> Ative o Bigbrain para este chat. Ajude a planejar esta mudança antes de implementá-la.

Para parar, diga **“Desative o Bigbrain para este chat.”** Retomar o mesmo chat preserva a configuração; chats novos ou bifurcados começam desativados. Instalar o skill não o ativa.

<details>
<summary>Outras formas de instalação</summary>

No CLI skills, escolha Codex como destino. Depois peça ao Codex para configurar o Bigbrain com Claude Code, usando o caminho real do skill instalado, sem presumir que existe um clone do repositório.

```bash
npx skills add kangchainx/bigbrain-skill
```

No repositório, `./install.sh --copy` instala uma cópia em vez de um link simbólico; `--claude` também instala para Claude Code e `--dir PATH` define o destino. O padrão é `${CODEX_HOME:-$HOME/.codex}/skills/bigbrain`. Preserve o repositório se usar um link simbólico.

</details>

## Uma tarefa, papéis claros

![Diagrama ilustrativo dos papéis e do fluxo](docs/assets/flow.en.png)

<p align="center"><a href="docs/assets/demo.en.mp4"><img src="docs/assets/demo.en.gif" alt="Ver a conversa de 24 segundos com música (MP4). Demonstração com roteiro." width="960"></a></p>

[Ver a conversa de 24 segundos com música (MP4). Demonstração com roteiro.](docs/assets/demo.en.mp4)

*Diagrama ilustrativo dos papéis e do fluxo*

1. **Você ativa.** A complexidade não ativa o Bigbrain em um chat desativado.
2. **Claude orienta quando necessário.** Em um chat ativo, uma pontuação de planejamento acima de `0.6` aciona o consultor; um pedido explícito também pode acioná-lo. O trabalho simples fica com o Codex.
3. **Codex implementa e revisa primeiro.** Ele edita arquivos, executa verificações e faz a primeira revisão de código. A segunda revisão pelo Claude exige pedido explícito.
4. **As evidências continuam disponíveis.** Feedback pode reabrir uma tarefa para diagnóstico e novas verificações. As chamadas do consultor registram tokens e custo estimado.

## Escolha o backend do consultor

|  | Claude Code · recomendado | Messages API · alternativa |
|---|---|---|
| Autenticação | Login do próprio Claude Code | Chave API do provedor |
| Modelo | `BIGBRAIN_CLAUDE_MODEL` (padrão: `opus`) | `BIGBRAIN_MODEL` (padrão: `claude-opus-5-5`) |
| Contexto | Sessão persistente por tarefa; apenas Read/Glob/Grep | Contexto fornecido pelo Codex |
| Custo | Estimativa informada pelo Claude Code | Uso retornado × preços configurados |

Tarefas existentes mantêm seu backend e modelo. Configurações antigas sem backend continuam usando `api` por compatibilidade. **Não há troca silenciosa de backend.** O acesso ao modelo depende da conta ou do endpoint.

<details>
<summary>Configurar um provedor Messages API</summary>

No repositório, abra o formulário local com o comando abaixo. Informe nele o endpoint HTTPS, a chave API e o modelo, nunca a chave no chat. O formulário consulta a lista de modelos e só salva após uma geração real bem-sucedida.

```bash
python3 scripts/bigbrain_cli.py setup --web
```

Streaming e novas tentativas após erros temporários são exclusivos do backend API. O provedor precisa aceitar o modelo e os parâmetros thinking/effort; JSON no formato Anthropic não basta para garantir compatibilidade. `BIGBRAIN_BASE_URL` não termina com `/v1`. Variáveis de ambiente têm prioridade sobre a configuração salva. Veja a [configuração](references/config.md).

</details>

## Sua sessão, seus controles

- **Responsabilidades separadas.** O consultor Claude Code usa apenas Read/Glob/Grep, com `--safe-mode`, configuração MCP estrita e vazia e comandos de barra desativados. O Codex edita arquivos e executa testes.
- **Estado local.** Aprendizados ficam em `~/.bigbrain/experience/`; registros de tarefas ficam em `.bigbrain/` no espaço de trabalho. Contexto relevante e imagens são enviados ao consultor escolhido. Armazenamento local não significa inferência offline.
- **Sem alterar instruções globais.** O Bigbrain não modifica `AGENTS.md`, `CLAUDE.md` nem a configuração global do Codex/Claude; grava sua própria configuração.
- **Uso visível.** O custo é uma estimativa, não uma fatura ou prova de cobrança na assinatura. Dados ausentes são sinalizados. Comparações de economia também estimam os tokens do executor, portanto não são benchmarks.

## Uso manual

Normalmente o Codex conduz o fluxo. No repositório, estes comandos consultam o estado do chat ou de uma tarefa existente sem chamar o consultor:

```bash
python3 scripts/bigbrain_cli.py mode status
python3 scripts/bigbrain_cli.py status --session .bigbrain/my-task
```

<details>
<summary>Avançado: ciclo de etapas do consultor</summary>

Após ativar explicitamente, use o mesmo diretório de sessão para cada tarefa. Estes comandos chamam o consultor; `m1.md` deve conter resultados reais e evidências de verificação.

```bash
python3 scripts/bigbrain_cli.py mode on
python3 scripts/bigbrain_cli.py lessons list --limit 10
python3 scripts/bigbrain_cli.py start --task "..." --user-request --effort medium --session .bigbrain/my-task
python3 scripts/bigbrain_cli.py report --session .bigbrain/my-task --result-file m1.md
python3 scripts/bigbrain_cli.py feedback --session .bigbrain/my-task --reason "..."
```

O ciclo do consultor só aceita `done` quando todos os critérios estão marcados como atendidos. Isso não torna obrigatória a aprovação do Claude em uma revisão feita apenas pelo Codex. Padrões: 8 rodadas, esforço `medium`; `high` e `xhigh` também estão disponíveis. Ao encerrar, normalmente há uma chamada de retrospectiva. Códigos: `0` continuar ou `DONE`; `10` bloqueado; `11` rodadas esgotadas; `12` JSON inválido após reparo; `2`–`6` erros de configuração ou provedor.

</details>

<details>
<summary>Opcional: hooks do plugin Codex</summary>

O repositório inclui um marketplace local. Registre-o com os comandos abaixo, depois revise e autorize seus hooks no Codex. Desative a entrada do skill independente para evitar duplicação. O instalador do skill não registra nem autoriza hooks.

```bash
codex plugin marketplace add /absolute/path/to/bigbrain-skill
codex plugin add bigbrain@bigbrain-local
```

SessionStart e UserPromptSubmit lembram as regras apenas em chats ativos. Hooks não chamam modelos nem garantem o cumprimento de todas as regras de conversa. Veja [colaboração](references/collaboration.md) e [recuperação de sessões](references/native-sessions.md).

</details>

## Perguntas práticas

**Claude é chamado em toda tarefa?**

Não. Desativado, o Bigbrain não inicia novas chamadas do fluxo. Mesmo ativado, tarefas simples podem ficar apenas com o Codex. Desativá-lo não interrompe uma solicitação em andamento.

**Posso experimentar sem chamar um modelo?**

Execute `bash examples/minimal/run.sh` no repositório. São respostas preparadas: uma demonstração do mecanismo, não uma revisão real.

**Como verificar o código?**

Execute `bash tests/run_tests.sh`. Os testes usam diretórios temporários e mocks locais, sem chamadas reais aos provedores.

**Como desinstalar?**

Execute `./install.sh --uninstall` no repositório. Os aprendizados são preservados. Adicione `--purge` apenas se também quiser apagar o armazenamento do Bigbrain no nível do usuário.

## Saiba mais

[Configuração e backends](references/config.md) · [Regras de escalonamento](references/triggers.md) · [Sessões e recuperação](references/native-sessions.md) · [Aprendizados locais](references/experience.md) · [Auditoria offline de custos](references/session-audit.md) · [Contribuir](CONTRIBUTING.md)

---

Criado por **Chris Kang** ([@kangchainx](https://github.com/kangchainx)).

[MIT](LICENSE) · © 2026 Chris Kang. Se você criar algo com Bigbrain, agradecemos um link para este repositório.
