<div align="center">
  <h1>Bigbrain</h1>
  <p><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · <a href="README.es.md">Español</a> · <strong>Français</strong> · <a href="README.de.md">Deutsch</a> · <a href="README.pt-BR.md">Português (Brasil)</a></p>
  <p>
    <a href="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/kangchainx/bigbrain-skill/actions/workflows/tests.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-64748b.svg"></a>
    <a href="https://www.python.org/"><img alt="Python standard library" src="https://img.shields.io/badge/Python-stdlib_only-3776ab.svg"></a>
  </p>
</div>

Invitez Claude dans votre conversation Codex pour planifier et diagnostiquer les problèmes. Codex écrit le code, lance les vérifications et effectue la première revue. Vous choisissez quand demander un deuxième avis.

![Codex réalise. Claude vous aide à réfléchir.](docs/assets/hero.en.png)

**Désactivé par défaut, à activer par conversation.** Une fois activé, les tâches difficiles peuvent solliciter Claude pour la planification ou le diagnostic. **La seconde revue de code par Claude est facultative et exige une demande explicite.**

## Quand utiliser Bigbrain

| Votre besoin | Ce que Bigbrain apporte |
|---|---|
| Un plan avant un changement coûteux | Des exigences clarifiées en étapes avec des critères de validation vérifiables. |
| Sortir des tentatives qui échouent en boucle | Les échecs et les preuves transmis à Claude pour déterminer la prochaine approche. |
| Garder le contexte et le contrôle | Une session Claude par tâche, des enseignements locaux et une estimation visible du coût du conseiller. |

## Bien démarrer

Il vous faut Codex, Python 3 et un CLI Claude Code connecté, prenant en charge `--safe-mode` (testé avec 2.1.310). Bigbrain utilise uniquement la bibliothèque standard de Python. Exécutez les commandes suivantes depuis le dépôt cloné.

```bash
git clone https://github.com/kangchainx/bigbrain-skill.git
cd bigbrain-skill
./install.sh --no-setup
python3 scripts/bigbrain_cli.py setup --claude-code
python3 scripts/check_config.py --no-call --json
```

Si nécessaire, connectez-vous d’abord avec `claude auth login`. La configuration choisit le backend. Le contrôle sans appel vérifie la connexion, pas l’accès au modèle ; le premier véritable appel vérifie la génération.

Puis, dans votre conversation Codex, dites :

> Active Bigbrain pour cette conversation. Aide-moi à planifier ce changement avant de le réaliser.

Pour arrêter, dites **« Désactive Bigbrain pour cette conversation. »** Une reprise conserve l’état ; une nouvelle conversation ou une bifurcation commence désactivée. Installer le skill ne l’active pas.

<details>
<summary>Autres méthodes d’installation</summary>

Avec le CLI skills, choisissez Codex comme cible. Demandez ensuite à Codex de configurer Bigbrain avec Claude Code, en utilisant le chemin du skill installé plutôt qu’un dépôt supposé présent.

```bash
npx skills add kangchainx/bigbrain-skill
```

Depuis le dépôt, `./install.sh --copy` copie au lieu de créer un lien symbolique ; `--claude` installe aussi pour Claude Code et `--dir PATH` choisit la destination. Par défaut : `${CODEX_HOME:-$HOME/.codex}/skills/bigbrain`. Conservez le dépôt si vous utilisez un lien symbolique.

</details>

## Une tâche, des rôles clairs

![Schéma explicatif des rôles et du déroulement](docs/assets/flow.en.png)

<p align="center"><a href="docs/assets/demo.en.mp4"><img src="docs/assets/demo.en.gif" alt="Voir la conversation de 24 secondes avec musique (MP4). Démonstration scénarisée." width="960"></a></p>

[Voir la conversation de 24 secondes avec musique (MP4). Démonstration scénarisée.](docs/assets/demo.en.mp4)

*Schéma explicatif des rôles et du déroulement*

1. **Vous activez la collaboration.** La complexité seule n’active jamais Bigbrain dans une conversation désactivée.
2. **Claude intervient au besoin.** Dans une conversation activée, un score de planification supérieur à `0.6` déclenche une consultation ; une demande explicite peut aussi la déclencher. Les tâches simples restent à Codex.
3. **Codex réalise et relit en premier.** Il modifie les fichiers, vérifie et effectue la première revue de code. Une seconde revue par Claude exige une demande explicite.
4. **Les preuves sont conservées.** Un retour peut rouvrir une tâche pour un diagnostic et de nouvelles vérifications. Les appels du conseiller enregistrent les tokens et un coût estimé.

## Choisir le backend du conseiller

|  | Claude Code · recommandé | Messages API · alternative |
|---|---|---|
| Authentification | Connexion propre à Claude Code | Clé API du fournisseur |
| Modèle | `BIGBRAIN_CLAUDE_MODEL` (défaut : `opus`) | `BIGBRAIN_MODEL` (défaut : `claude-opus-5-5`) |
| Contexte | Session persistante par tâche ; Read/Glob/Grep uniquement | Contexte fourni par Codex |
| Coût | Estimation renvoyée par Claude Code | Usage renvoyé × tarifs configurés |

Les tâches existantes gardent leur backend et leur modèle. Les anciennes configurations sans backend restent sur `api`. **Aucun basculement silencieux** vers un autre backend. L’accès au modèle dépend du compte ou de l’endpoint.

<details>
<summary>Configurer un fournisseur Messages API</summary>

Depuis le dépôt, ouvrez le formulaire local ci-dessous. Saisissez-y l’endpoint HTTPS, la clé API et le modèle ; ne collez jamais la clé dans la conversation. Le formulaire consulte les modèles disponibles et n’enregistre qu’après une génération réelle réussie.

```bash
python3 scripts/bigbrain_cli.py setup --web
```

Le streaming et les nouvelles tentatives après une erreur temporaire sont propres au backend API. Le fournisseur doit accepter le modèle et les paramètres thinking/effort demandés ; un JSON au format Anthropic ne suffit pas. `BIGBRAIN_BASE_URL` ne se termine pas par `/v1`. Les variables d’environnement sont prioritaires. Voir la [configuration](references/config.md).

</details>

## Votre session, vos réglages

- **Rôles distincts.** Le conseiller Claude Code est limité à Read/Glob/Grep, avec `--safe-mode`, une configuration MCP stricte et vide, et les commandes slash désactivées. Codex réalise les modifications et les tests.
- **État local.** Les enseignements sont dans `~/.bigbrain/experience/` et les tâches dans `.bigbrain/` dans l’espace de travail. Le contexte pertinent et les images sont envoyés au conseiller choisi. Un stockage local ne signifie pas une inférence hors ligne.
- **Instructions globales préservées.** Bigbrain ne modifie ni `AGENTS.md`, ni `CLAUDE.md`, ni la configuration globale de Codex/Claude. Il écrit sa propre configuration.
- **Usage visible.** Le coût reste une estimation, pas une facture ni une preuve de débit sur l’abonnement. Les données manquantes sont signalées. Les économies estimées incluent une estimation des tokens de l’exécuteur et ne constituent pas un benchmark.

## Utilisation manuelle

Codex pilote normalement le flux. Depuis le dépôt, ces commandes consultent l’état de la conversation ou d’une tâche existante sans appeler le conseiller :

```bash
python3 scripts/bigbrain_cli.py mode status
python3 scripts/bigbrain_cli.py status --session .bigbrain/my-task
```

<details>
<summary>Avancé : boucle des étapes du conseiller</summary>

Après activation explicite, conservez le même répertoire de session pour une tâche. Ces commandes appellent le conseiller ; `m1.md` doit contenir les vrais résultats et les preuves de vérification.

```bash
python3 scripts/bigbrain_cli.py mode on
python3 scripts/bigbrain_cli.py lessons list --limit 10
python3 scripts/bigbrain_cli.py start --task "..." --user-request --effort medium --session .bigbrain/my-task
python3 scripts/bigbrain_cli.py report --session .bigbrain/my-task --result-file m1.md
python3 scripts/bigbrain_cli.py feedback --session .bigbrain/my-task --reason "..."
```

La boucle du conseiller n’accepte `done` que lorsque tous les critères sont marqués comme satisfaits. Cela n’impose pas l’approbation de Claude pour une revue effectuée uniquement par Codex. Par défaut : 8 tours, effort `medium` ; `high` et `xhigh` sont aussi disponibles. La fin de la boucle inclut généralement un appel de rétrospective. Codes : `0` continuer ou `DONE` ; `10` bloqué ; `11` tours épuisés ; `12` JSON invalide après réparation ; `2`–`6` erreurs de configuration ou de fournisseur.

</details>

<details>
<summary>Facultatif : hooks du plugin Codex</summary>

Le dépôt contient un marketplace local. Enregistrez-le avec ces commandes, puis vérifiez et autorisez ses hooks dans Codex. Désactivez l’entrée du skill autonome pour éviter les doublons. L’installateur du skill n’enregistre ni n’autorise les hooks.

```bash
codex plugin marketplace add /absolute/path/to/bigbrain-skill
codex plugin add bigbrain@bigbrain-local
```

SessionStart et UserPromptSubmit rappellent les règles seulement dans les conversations activées. Les hooks n’appellent aucun modèle et ne garantissent pas toutes les règles de dialogue. Voir [collaboration](references/collaboration.md) et [récupération des sessions](references/native-sessions.md).

</details>

## Questions pratiques

**Claude est-il appelé pour chaque tâche ?**

Non. Désactivé, Bigbrain ne lance aucun nouvel appel du flux. Activé, il peut laisser les tâches simples à Codex. Le désactiver n’interrompt pas une requête déjà en cours.

**Peut-on essayer sans modèle ?**

Lancez `bash examples/minimal/run.sh` depuis le dépôt. Les réponses sont préétablies : c’est une démonstration du mécanisme, pas une vraie revue.

**Comment vérifier le code ?**

Lancez `bash tests/run_tests.sh`. Les tests utilisent des répertoires temporaires et des mocks locaux, sans appel réel à un fournisseur.

**Comment désinstaller ?**

Lancez `./install.sh --uninstall` depuis le dépôt. Les enseignements sont conservés. Ajoutez `--purge` uniquement pour supprimer aussi le stockage Bigbrain de l’utilisateur.

## Pour aller plus loin

[Configuration et backends](references/config.md) · [Règles de consultation](references/triggers.md) · [Sessions et récupération](references/native-sessions.md) · [Enseignements locaux](references/experience.md) · [Audit des coûts hors ligne](references/session-audit.md) · [Contribuer](CONTRIBUTING.md)

---

Créé par **Chris Kang** ([@kangchainx](https://github.com/kangchainx)).

[MIT](LICENSE) · © 2026 Chris Kang. Un lien vers ce dépôt est apprécié si vous construisez un projet avec Bigbrain.
