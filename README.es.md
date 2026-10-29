<div align="center">
  <h1>Bigbrain</h1>
  <p><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · <strong>Español</strong> · <a href="README.fr.md">Français</a> · <a href="README.de.md">Deutsch</a> · <a href="README.pt-BR.md">Português (Brasil)</a></p>
  <p>
    <a href="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-64748b.svg"></a>
    <a href="https://www.python.org/"><img alt="Python standard library" src="https://img.shields.io/badge/Python-stdlib_only-3776ab.svg"></a>
  </p>
</div>

Invita a Claude a tu chat de Codex para planificar y diagnosticar problemas. Codex escribe el código, ejecuta las comprobaciones y hace la primera revisión. Tú decides cuándo pedir una segunda opinión.

![Codex construye. Claude te ayuda a pensarlo.](docs/assets/hero.en.png)

**Desactivado por defecto; se activa por chat.** Tras activarlo, las tareas difíciles pueden recurrir a Claude para planificación o diagnóstico. **La segunda revisión de código por Claude es opcional y requiere una petición explícita.**

## Cuándo usar Bigbrain

| Si necesitas… | Bigbrain te ayuda a… |
|---|---|
| Un plan antes de un cambio costoso | Dividir requisitos ambiguos en hitos con criterios de aceptación verificables. |
| Salir de un ciclo de intentos fallidos | Entregar a Claude los intentos y las pruebas para diagnosticar el siguiente paso. |
| Continuidad sin perder el control | Mantener una sesión de Claude por tarea, aprendizajes locales y estimaciones visibles del coste del asesor. |

## Primeros pasos

Necesitas Codex, Python 3 y Claude Code CLI con sesión iniciada y soporte para `--safe-mode` (probado con 2.1.310). Bigbrain solo utiliza la biblioteca estándar de Python. Ejecuta los comandos siguientes desde el repositorio clonado.

```bash
git clone https://github.com/kangchainx/bigbrain-skill.git
cd bigbrain-skill
./install.sh --no-setup
python3 scripts/bigbrain_cli.py setup --claude-code
python3 scripts/check_config.py --no-call --json
```

Si aún no has iniciado sesión, ejecuta primero `claude auth login`. La configuración selecciona el backend; la comprobación sin llamadas valida la sesión, no el acceso al modelo. La primera llamada real verifica la generación.

Después, escribe en tu chat de Codex:

> Activa Bigbrain para este chat. Ayúdame a planificar este cambio antes de implementarlo.

Para detenerlo, di **«Desactiva Bigbrain para este chat»**. Reanudar el mismo chat conserva el estado; los chats nuevos o bifurcados empiezan desactivados. Instalar el skill no lo activa.

<details>
<summary>Otras opciones de instalación</summary>

Con skills CLI, elige Codex como destino. Luego pide a Codex que configure Bigbrain con Claude Code usando la ruta real del skill instalado, sin dar por hecho que existe un clon del repositorio.

```bash
npx skills add kangchainx/bigbrain-skill
```

Desde el repositorio, `./install.sh --copy` copia en lugar de crear un enlace simbólico; `--claude` también instala para Claude Code y `--dir PATH` elige el destino. La ruta predeterminada es `${CODEX_HOME:-$HOME/.codex}/skills/bigbrain`. Conserva el repositorio si lo instalaste mediante un enlace.

</details>

## Una tarea, funciones claras

![Diagrama ilustrativo de las funciones y el flujo](docs/assets/flow.en.png)

<p align="center"><a href="docs/assets/demo.en.mp4"><img src="docs/assets/demo.en.gif" alt="Ver la conversación de 24 segundos con música (MP4). Demostración con guion." width="960"></a></p>

[Ver la conversación de 24 segundos con música (MP4). Demostración con guion.](docs/assets/demo.en.mp4)

*Diagrama ilustrativo de las funciones y el flujo*

1. **Tú lo activas.** La complejidad no activa Bigbrain en un chat desactivado.
2. **Claude asesora cuando hace falta.** En un chat activo, una puntuación de planificación superior a `0.6` solicita asesoría; una petición explícita también puede hacerlo. Codex resuelve el trabajo sencillo.
3. **Codex implementa y revisa primero.** Edita archivos, ejecuta comprobaciones y hace la primera revisión. La segunda revisión de Claude requiere una petición explícita.
4. **Las pruebas se conservan.** El feedback puede reabrir una tarea para diagnosticarla y aportar nuevas verificaciones. Las llamadas del asesor registran tokens y coste estimado.

## Elige el backend del asesor

|  | Claude Code · recomendado | Messages API · alternativa |
|---|---|---|
| Autenticación | La propia sesión de Claude Code | Clave API de tu proveedor |
| Modelo | `BIGBRAIN_CLAUDE_MODEL` (por defecto: `opus`) | `BIGBRAIN_MODEL` (por defecto: `claude-opus-5-5`) |
| Contexto | Sesión persistente por tarea; solo Read/Glob/Grep | Contexto aportado por Codex |
| Coste | Estimación de Claude Code | Uso devuelto × precios configurados |

Las tareas existentes conservan su backend y modelo. Las configuraciones sin backend mantienen `api` por compatibilidad. **No hay cambio silencioso de backend.** El acceso al modelo depende de la cuenta o del endpoint.

<details>
<summary>Configurar un proveedor de Messages API</summary>

Abre el formulario local desde el repositorio. Introduce allí el endpoint HTTPS, la clave API y el modelo, nunca la clave en el chat. El formulario consulta los modelos del endpoint y solo guarda tras una prueba real de generación satisfactoria.

```bash
python3 scripts/bigbrain_cli.py setup --web
```

El streaming y los reintentos ante errores transitorios solo se aplican al backend API. El proveedor debe admitir el modelo y los parámetros thinking/effort solicitados; el formato JSON de Anthropic no basta para garantizar compatibilidad. `BIGBRAIN_BASE_URL` no lleva `/v1` al final. Las variables de entorno tienen prioridad. Consulta la [configuración](references/config.md).

</details>

## Tu sesión, tus controles

- **Responsabilidades separadas.** El asesor Claude Code solo usa Read/Glob/Grep; se inicia con `--safe-mode`, una configuración MCP estricta y vacía, y comandos de barra desactivados. Codex edita y ejecuta los tests.
- **Estado local.** Los aprendizajes se guardan en `~/.bigbrain/experience/` y los registros en `.bigbrain/` dentro del espacio de trabajo. El contexto relevante y las imágenes se envían al asesor elegido. Guardar localmente no implica inferencia sin conexión.
- **Sin cambios en instrucciones globales.** Bigbrain no modifica `AGENTS.md`, `CLAUDE.md` ni la configuración global de Codex/Claude; guarda su propia configuración.
- **Uso visible.** El coste es una estimación, no una factura ni prueba de un cargo en la suscripción. Se indica el uso desconocido. Las comparaciones de ahorro también estiman los tokens del ejecutor y no son un benchmark.

## Uso manual

Normalmente Codex ejecuta el flujo. Estos comandos consultan el estado del chat o de una tarea existente desde el repositorio sin llamar al asesor:

```bash
python3 scripts/bigbrain_cli.py mode status
python3 scripts/bigbrain_cli.py status --session .bigbrain/my-task
```

<details>
<summary>Avanzado: ciclo de hitos del asesor</summary>

Tras activarlo explícitamente, utiliza un mismo directorio de sesión por tarea. Estos comandos hacen llamadas al asesor; `m1.md` debe contener resultados reales y pruebas de verificación.

```bash
python3 scripts/bigbrain_cli.py mode on
python3 scripts/bigbrain_cli.py lessons list --limit 10
python3 scripts/bigbrain_cli.py start --task "..." --user-request --effort medium --session .bigbrain/my-task
python3 scripts/bigbrain_cli.py report --session .bigbrain/my-task --result-file m1.md
python3 scripts/bigbrain_cli.py feedback --session .bigbrain/my-task --reason "..."
```

En el ciclo del asesor, `done` solo se acepta cuando todos los criterios figuran como cumplidos. Esto no obliga a obtener aprobación de Claude en una revisión realizada solo por Codex. Valores predeterminados: 8 rondas y esfuerzo `medium`; también se admiten `high` y `xhigh`. Al terminar suele añadirse una llamada de retrospectiva. Códigos: `0` continuar o `DONE`; `10` bloqueado; `11` rondas agotadas; `12` JSON inválido tras reparación; `2`–`6` errores de configuración o proveedor.

</details>

<details>
<summary>Opcional: hooks del plugin de Codex</summary>

El repositorio incluye un marketplace local. Regístralo con estos comandos y revisa y autoriza sus hooks en Codex. Desactiva la entrada del skill independiente para evitar duplicados. El instalador del skill no registra ni autoriza hooks.

```bash
codex plugin marketplace add /absolute/path/to/bigbrain-skill
codex plugin add bigbrain@bigbrain-local
```

SessionStart y UserPromptSubmit recuerdan las reglas solo en chats activos. Los hooks no llaman a modelos ni garantizan el cumplimiento de todas las reglas de conversación. Consulta [colaboración](references/collaboration.md) y [recuperación de sesiones](references/native-sessions.md).

</details>

## Preguntas prácticas

**¿Llama a Claude en cada tarea?**

No. Desactivado no inicia nuevas llamadas del flujo. Incluso activado, Codex puede resolver tareas sencillas solo. Desactivarlo no interrumpe una petición en curso.

**¿Puedo probarlo sin llamar a un modelo?**

Ejecuta `bash examples/minimal/run.sh` desde el repositorio. Usa respuestas preparadas: demuestra el mecanismo, no una revisión real.

**¿Cómo verifico el código?**

Ejecuta `bash tests/run_tests.sh`. Utiliza directorios temporales y mocks locales, sin llamadas reales a proveedores.

**¿Cómo lo desinstalo?**

Ejecuta `./install.sh --uninstall` desde el repositorio. Los aprendizajes se conservan. Añade `--purge` solo si también quieres borrar el almacenamiento de Bigbrain del usuario.

## Más información

[Configuración y backends](references/config.md) · [Reglas de escalado](references/triggers.md) · [Sesiones y recuperación](references/native-sessions.md) · [Aprendizajes locales](references/experience.md) · [Auditoría de costes sin conexión](references/session-audit.md) · [Contribuir](CONTRIBUTING.md)

---

Creado por **Chris Kang** ([@kangchainx](https://github.com/kangchainx)).

[MIT](LICENSE) · © 2026 Chris Kang. Si creas algo con Bigbrain, se agradece un enlace a este repositorio.
