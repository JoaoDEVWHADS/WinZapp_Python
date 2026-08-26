# Skills do WinZapp

Referência do ferramental de IA disponível para quem trabalha neste repositório.
São **três grupos com procedências diferentes**, e a distinção importa: só o
primeiro vem junto com o `git clone`.

---

## 1. Skills do projeto — versionadas, todo mundo tem

Vivem em `.claude/skills/<nome>/SKILL.md` e entram no repositório como qualquer
outro arquivo. Quem clona, tem. São carregadas automaticamente e acionadas pelo
próprio agente quando a tarefa se encaixa na descrição — não é preciso invocar
à mão.

| skill | quando ela vale |
| --- | --- |
| `i18n-ui-string` | Qualquer texto que o usuário lê ou o leitor de tela fala. `I18n.t()` é `translations.get(key, key)`, sem fallback por chave: uma chave faltando vira o nome cru dela na tela, lido em voz alta. Cobre os cinco locales, `&` como mnemônico do wx (um `&` literal se escreve `&&`) e placeholders `{}`. |
| `write-test` | Teste novo ou estendido. `MainWindow` é `wx.Frame` e `ConversationsPanel` é `wx.Panel`: nenhum dos dois instanciável sem `wx.App`, então ou a lógica sai para nível de módulo, ou o método real é ligado a um stub. Também as fixtures do `conftest.py` e o `asyncio_mode=auto` (teste async é só `async def`, sem decorator). |
| `wppconnect-patch` | Conserto do lado Node. São três mecanismos de patch diferentes, cada um com suas listas; escolher o errado é silencioso, e a mudança some no próximo `setup_api.py`. Nunca editar `client/api/` direto. |
| `accessible-ui` | Qualquer mexida em `client/ui/`, `status_panel.py` ou no wx do `main.py`. Controles padrão do wx, toda fala por `speak_output`, `Freeze`/`Thaw` com `try/finally` em volta de mutação de lista, e o limite de 511 caracteres do SysListView32. |

As quatro estão escritas em inglês, para casar com o `CLAUDE.md` e o `AGENTS.md`
— são documentos do mesmo tipo, dirigidos ao agente.

### Escrevendo uma skill nova

O critério que usamos para decidir o que vira skill: **procedimento repetível**
vira skill; **julgamento caso a caso** não. Normalização de JID, por exemplo, é
a maior fonte de bug do projeto e mesmo assim não é skill — não existe passo a
passo, existe um conjunto de invariantes a respeitar. Isso é material para
agente revisor, não para skill.

---

## 2. `mattpocock-skills` — declarado pelo repositório

Os arquivos não vêm no clone, mas a **declaração** vem: `.claude/settings.json`
registra o marketplace e marca o plugin como habilitado, então quem clona
recebe a instalação sem precisar rodar nada à mão.

```json
"enabledPlugins": { "mattpocock-skills@claude-plugins-official": true },
"extraKnownMarketplaces": { "claude-plugins-official": { ... } }
```

As duas chaves andam juntas de propósito: sem o `extraKnownMarketplaces`, um
clone que ainda não conheça o marketplace oficial encontraria uma referência a
um plugin que não sabe de onde vem.

Vem do marketplace oficial da Anthropic, pinado num commit de
`github.com/mattpocock/skills`. Traz 25 skills registradas e custa ~1,6k tokens *always-on* em toda
sessão. O cache do plugin carrega 35 arquivos; os 10 excedentes
(`setup-pre-commit`, `git-guardrails-claude-code`, `migrate-to-shoehorn`,
as de writing…) não são expostos por ele e não contam nesse custo.

Os arquivos em si ficam fora do repositório, em
`~/.claude/plugins/cache/claude-plugins-official/mattpocock-skills/<versão>/`,
e atualizam com `claude plugin update`. É de propósito que não sejam copiados
para `.claude/skills/`: essa pasta é das skills que o projeto escreve e
versiona, e uma cópia local das do plugin viraria um fork que envelhece calado
— o mesmo motivo pelo qual o `AGENTS.md` não duplica o `CLAUDE.md` e pelo qual
nunca se edita `client/api/` direto.

**Grelha** — bloqueiam a geração de código e entrevistam você primeiro:
`grill-me` (afia plano ou design), `grill-with-docs` (o mesmo, produzindo ADRs e
glossário no caminho), `grilling` (dispara por qualquer gatilho "grill"),
`wait-what` ("para, essa mensagem não colou: repitch").

**Spec-driven development** — o fluxo completo:
`to-spec` (vira a conversa em spec e publica no issue tracker),
`to-tickets` (quebra em tickets tracer-bullet com as dependências declaradas),
`to-questionnaire` (decisão que você não sabe responder vira questionário para
outra pessoa), `implement` (executa a partir da spec ou dos tickets),
`wayfinder` (trabalho grande demais para uma sessão, como mapa de tickets de
decisão), `triage` (máquina de estados para issues e PRs externos),
`handoff` (compacta a conversa para outro agente continuar).

**Engenharia:** `tdd`, `code-review`, `diagnosing-bugs`, `codebase-design`,
`improve-codebase-architecture`, `domain-modeling`, `prototype`, `research`,
`resolving-merge-conflicts`, `wizard`, `teach`, `ask-matt` (roteador entre as
outras) e `writing-for-agents` (escrever skill, `AGENTS.md` ou `CLAUDE.md`).

> **Atenção antes de rodar `setup-matt-pocock-skills`.** Ela configura issue
> tracker e vocabulário de labels *no repositório*, e vários dos fluxos de SDD
> acima publicam nesse tracker. É decisão de time, não de máquina individual.

---

## 3. Skills do Claude Code — por conta, não por repositório

O que cada um tem aqui varia com a conta e os plugins habilitados. Por categoria:

- **Arquivos:** `docx`, `pdf`, `pptx`, `xlsx`
- **Visual:** `design`, `dataviz`, `artifact-design`, `artifact-diagramming`, `artifact-capabilities`
- **Engenharia (`engineering:*`):** `architecture` (ADR), `code-review`, `debug`, `deploy-checklist`, `documentation`, `incident-response`, `standup`, `system-design`, `tech-debt`, `testing-strategy`
- **Revisão:** `/code-review`, `/simplify`, `/security-review`
- **Configuração:** `update-config`, `keybindings-help`, `fewer-permission-prompts`, `schedule`, `loop`, `init`, `run`, `claude-api`
- **Skills e memória:** `find-skills`, `skill-creator`, `consolidate-memory`, `import-memory`

---

## Três coisas chamadas `code-review`

Vale saber antes de alguém pedir "roda o code-review" e receber outra coisa:

| qual | o que faz |
| --- | --- |
| `/code-review` (Claude Code) | Revisa o diff atual ou um PR, com níveis de esforço. `ultra` dispara revisão multi-agente na nuvem. |
| `engineering:code-review` | Playbook genérico de revisão — segurança, performance, correção. |
| `code-review` (mattpocock) | Revisa as mudanças desde um ponto fixo contra a **documentação do próprio repositório**, além da correção. |

---

## O que ainda não temos

Sem CI em `pull_request`: os testes só rodam **depois** do merge, no build alpha.
Enquanto isso, a aprovação humana é o único portão antes do merge — e é por isso
que rodar `pytest` local antes de abrir PR não é opcional.
