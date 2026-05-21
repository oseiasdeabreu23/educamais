# CLAUDE.md — Guia para IA: EducaMais

Este arquivo dá contexto essencial para qualquer IA que trabalhe neste projeto.
Detalhes profundos de cada módulo estão em `docs/` — leia o arquivo correspondente
**quando for mexer naquele módulo** (índice no final).

---

## O que é este projeto

**EducaMais** é um sistema web de gestão escolar construído em Python/Flask para o
**Instituto Arvorecer**. Permite que admins, professores, responsáveis e alunos
acompanhem notas, frequência, atividades, alertas e cursos com videoaulas.
O nome e a logo da plataforma são configuráveis pelo admin sem mexer no código.

**Estado atual (2026-05-21):** funcional, testado localmente, com redesign visual
completo ("Sistema Arvorecer"), módulo financeiro (mensalidades, boletos, fluxo de
caixa, inadimplentes) com Banco Cora em modo mock, múltiplas matrículas de turma
por aluno com histórico, aniversariantes e relatórios com KPIs/gráficos/PDF,
perfil "Secretário(a)" + permissões customizáveis por usuário (admin pode
ajustar checkboxes individualmente em `/admin/usuarios/<id>/permissoes`),
**multi-plano de pagamento por matrícula** — aluno com N turmas ativas pode ter
N planos paralelos, cada um com responsável-pagador e valor próprios.
Em fase de aprimoramento para implantação no instituto.

---

## Como rodar para testar

```bash
# Na raiz do projeto (C:\...\Arvorecer\Sistema\EducaMais)
venv\Scripts\python.exe run.py
# Acesse: http://127.0.0.1:5555/login
```

A porta vem da variável `PORT` no `.env` (default 5555 — não usar 5000 porque conflita
com AirTunes no Windows/macOS). `iniciar.bat` na raiz é um atalho que ativa o venv e
sobe o servidor.

Migrar banco após pull/alteração de models:
```bash
venv\Scripts\python.exe -m flask db upgrade
```

Seed de dados de exemplo:
```bash
set PYTHONPATH=.
venv\Scripts\python.exe scripts\seed_data.py
```

Contas de teste:
- `admin@escola.com / admin123`
- `prof@escola.com / prof123`
- `resp@escola.com / resp123`
- `aluno@escola.com / aluno123`

---

## Arquitetura

```
app/__init__.py           → factory create_app(), blueprints, context processor (config_sistema)
app/models.py             → todos os modelos SQLAlchemy
app/auth.py               → blueprint sem prefixo: /login /logout /register
app/routes_admin.py       → blueprint prefixo /admin (inclui cursos e configurações)
app/routes_professor.py   → blueprint prefixo /professor
app/routes_responsavel.py → blueprint prefixo /responsavel
app/routes_aluno.py       → blueprint prefixo /aluno
app/services.py           → lógica de negócio pura (médias, alertas, frequência, embed_url,
                            aniversariantes, helpers de matrícula em turma)
app/services_backup.py    → criar/restaurar/listar/excluir backups (zip do .db + uploads)
app/services_financeiro.py→ regras do financeiro (mensalidades, boletos, KPIs, fluxo)
app/services_cora.py      → cliente Cora (CoraMockClient, CoraRealClient, factory)
app/services_relatorios.py→ snapshots de KPIs, distribuição por turma, histórico anual
app/services_export.py    → geração de PDF/Excel (reportlab + openpyxl)
app/static/css/style.css  → design system completo (tokens light + dark, components)
app/static/uploads/       → logos enviadas pelo admin + comprovantes/ (financeiro)
app/templates/base.html   → app-shell (sidebar flutuante + topbar + drawer mobile + tema)
instance/backups/         → onde os arquivos .zip de backup ficam (criado on-demand)
instance/cora_mock.json   → estado persistido do CoraMockClient (boletos + movs fake)
migrations/               → controle de versão do banco (Alembic via Flask-Migrate)
docs/                     → documentação detalhada por módulo (lida sob demanda)
```

Banco de dados: SQLite em `instance/educamais.db` (dev). PostgreSQL para produção
(schema em `scripts/init_db.sql`).

Flask-Migrate configurado com `render_as_batch=True` (obrigatório para SQLite).

---

## Modelos (models.py)

### Existentes
- `User` — tipo: `admin` | `professor` | `responsavel` | `aluno`
- `Turma`, `Disciplina`
- `Aluno` — tem `user_id` (FK → `usuarios.id`, nullable, unique) para vincular conta de acesso.
  **Cadastro v2 (2026-05-04):** `cpf` (str unique, só dígitos), `sexo`, `cor_raca` (padrão INEP),
  `telefone`, endereço desmembrado (`cep`, `logradouro`, `numero`, `complemento`, `bairro`,
  `cidade`, `uf`), `pcd` (bool) + `pcd_descricao`, `status` (`ativo|evadido|formado`),
  `autoriza_imagem` (bool LGPD) + `data_consentimento_imagem`. Properties calculadas: `idade`,
  `cpf_formatado`, `cep_formatado`.
  **Matrículas em turma (2026-05-19, fase 1):** properties derivadas das `MatriculaTurma`:
  `vinculos_ativos`, `vinculos_historico`, `turmas_ativas`, `turma_corrente`, `status_derivado`.
  Campos legacy `Aluno.turma_id` e `Aluno.status` permanecem por compat (fallback usado pelo
  status_derivado quando o aluno não tem nenhuma matrícula migrada).
- `Responsavel`, `AlunoResponsavel` (N:N)
- `Professor` — disciplinas via N:N `professor_disciplina` (**sem campo `disciplina_id` direto**)
- `Nota` — unique por `(aluno_id, disciplina_id, mes, ano)`
- `Frequencia`, `Atividade`, `Observacao`

### Cursos/videoaulas (2026-04-28)
- `Curso` — título, descrição, capa_url, ativo, `duracao_meses` (Integer, opcional)
- `Modulo` — pertence a Curso, tem ordem
- `Videoaula` — pertence a Modulo, tem video_url (YouTube/Vimeo), duracao_min, ordem
- `MatriculaCurso` — N:N entre Aluno e Curso, unique por `(aluno_id, curso_id)`
- `ProgressoVideoaula` — aluno + videoaula + assistido (bool), unique por `(aluno_id, videoaula_id)`
- `ConfigSistema` — singleton (sempre ID=1): `nome` (str) + `logo_path` (str nullable)

### Matrículas em turma (2026-05-19)
- `MatriculaTurma` — vínculo aluno↔turma com histórico. Status `ativo|formado|evadido|transferido`.
  Sem unique composto — permite reentrada. Campo `mensalidade_padrao Numeric(10,2)`
  (2026-05-21) — valor sugerido do plano para essa turma específica.
  **Detalhes em [docs/matriculas.md](docs/matriculas.md).**

### Financeiro (2026-05-04, multi-plano em 2026-05-21)
- `PlanoPagamento` — `(aluno_id, matricula_turma_id, responsavel_id, n_parcelas,
  valor_parcela, dia_vencimento, data_primeira, status, observacao)`.
  Status: `ativo|cancelado|concluido`. **Um plano ativo por matrícula** — aluno
  com N turmas ativas pode ter N planos. `aluno_id` mantido por compat;
  `matricula_turma_id` é a fonte da verdade.
- `Mensalidade` — `(aluno, responsavel, matricula_turma, plano, mes, ano, valor, vencimento)` —
  unique por `(matricula_turma_id, mes, ano)`. NULL em `matricula_turma_id`
  é distinto pelo SQLite (mensalidades legacy não migradas convivem).
  `plano_id` FK opcional. `cancelada_em` DateTime opcional.
- `Aluno.mensalidade_padrao` — `Numeric(10,2)` opcional. Fallback quando a
  matrícula não tem `mensalidade_padrao` próprio (que ganhou precedência).
- `Boleto` — `cora_boleto_id`, `status` (`aberto|pago|vencido|cancelado`), valor, vencimento,
  pago_em, link_pdf, link_boleto. FK opcional pra `Mensalidade` (cascade).
- `CategoriaDespesa` — `(nome unique, cor)` — categorias editáveis pelo admin.
- `Movimentacao` — `tipo` (`entrada|saida`), `categoria_id`, descricao, valor, data,
  `boleto_id` (nullable, vincula entrada de boleto), `comprovante_path`, `criado_por_id`.

**Detalhes do módulo financeiro em [docs/financeiro.md](docs/financeiro.md).**

---

## Regras de negócio críticas

- Nota é única por `(aluno, disciplina, mês, ano)` — constraint no banco.
- Frequência aceita apenas: `presente`, `falta`, `justificada`. Justificada conta
  como presença no cálculo de percentual.
- Alerta de frequência dispara quando < 75% ou 3+ faltas consecutivas.
- Alunos com média < 5.5 aparecem como "baixo desempenho" no dashboard admin.
- Professor é vinculado a disciplinas via tabela N:N `professor_disciplina` —
  **não existe campo `disciplina_id` direto no model Professor**.
- Admin não pode ser excluído pela interface de usuários.
- `ConfigSistema` é singleton — sempre usar `.query.first()`, nunca criar mais de um registro.
- Logo do sistema salva em `app/static/uploads/logo.<ext>` com nome fixo (sobrescreve ao trocar).
- Formatos aceitos para logo: PNG, JPG, JPEG, WEBP, SVG. Tamanho máximo: 2 MB.
- **Cadastro de aluno v2:**
  - `cpf` salvo só com dígitos (11 caracteres). Formatação na exibição via property `cpf_formatado`.
    Validação com algoritmo dos dois dígitos verificadores em `services.cpf_valido()`.
  - `cep` idem (8 dígitos). UF validada contra a lista das 27 siglas em `services.UFS_BR`.
  - Form usa ViaCEP no JS para auto-preencher logradouro/bairro/cidade/uf.
  - Cursos do aluno geridos via `MatriculaCurso` com checkbox múltiplo no próprio form.
- **Status do aluno** (ativo/evadido/formado/transferido) — derivado das matrículas:
  - A property `Aluno.status_derivado` é a fonte da verdade: `ativo` se há matrícula ativa;
    senão o status da matrícula mais recente; `sem_vinculo` se nunca teve matrícula.
    Fallback final: `Aluno.status` legacy quando o aluno não tem matrícula nenhuma.
  - **ativo** é o único que aparece em dashboards, médias, frequência geral, e nos selects de
    professor. Filtros aplicam o critério via `_aluno_ativo_clausula()` ou subqueries
    `EXISTS` sobre `MatriculaTurma`.
  - Mudar para **evadido** (form legacy ou via vínculos) chama `cancelar_plano_aluno`
    automaticamente — **idempotente**, safe de chamar mais de uma vez.
  - **formado** / **transferido**: marcação manual via página de vínculos. Não cancela nada.
  - Detalhes do fluxo em [docs/matriculas.md](docs/matriculas.md).
- **Responsável obrigatório só para menores:**
  - `Mensalidade.responsavel_id` é `nullable=True` (migration `08c5c41c858c`).
  - `criar_plano_pagamento` e `gerar_mensalidades_lote` exigem responsável apenas se
    `aluno.idade < 18`. Adultos podem ter plano sem responsável.
  - `emitir_boleto` usa o próprio aluno como pagador quando `mensalidade.responsavel is None`.
- **Plano de pagamento (parcelamento) — multi-plano por matrícula (2026-05-21):**
  - Página em `/admin/financeiro/planos/<aluno_id>` — lista **1 card por matrícula ativa**.
    Aluno com 2 turmas pode ter 2 planos paralelos, cada um com responsável-pagador e valor próprio.
  - Service: `criar_plano_pagamento(matricula, n_parcelas, valor_parcela, ..., responsavel_id=None)`.
    Recebe `MatriculaTurma`, não `Aluno`. Falha com `ValueError` se matrícula não está `ativo`,
    se já tem plano ativo nessa matrícula, ou se o `responsavel_id` não pertence ao aluno.
  - Rotas POST: `/admin/financeiro/planos/matricula/<matricula_id>/criar` e `.../cancelar`.
  - **Estratégia híbrida**: registra todas as N mensalidades de uma vez, mas só **emite o boleto**
    da primeira (e apenas se vencer em ≤ 30 dias — `JANELA_EMISSAO_DIAS`). Próximos boletos
    emitidos sob demanda.
  - **Vencimento empurrado pra próxima segunda** se cair sábado/domingo (`proximo_dia_util`).
    Sem feriados — decisão consciente.
  - **Cancelamento por matrícula** (`cancelar_plano_matricula(matricula)`) atinge só o plano
    daquela turma. `cancelar_plano_aluno(aluno)` é wrapper agregado que itera matrículas —
    usado quando o aluno todo é desligado (exclusão, status legacy `evadido`).
  - **Valor sugerido no form** segue a ordem: `matricula.mensalidade_padrao` →
    `aluno.mensalidade_padrao` → vazio. `gerar_mensalidades_lote` aplica a mesma ordem.
  - Lookup por matrícula: `plano_ativo_da_matricula(matricula)`. Lookup agregado:
    `planos_ativos_do_aluno(aluno)` (lista). `plano_ativo_do_aluno(aluno)` mantida por
    compat retornando o primeiro da lista.
- **Financeiro:**
  - Mensalidade é única por `(matricula_turma_id, mes, ano)` — constraint no banco.
    Aluno com N turmas tem N mensalidades possíveis no mesmo mês (uma por turma).
  - Boletos só são gerados via `services_cora.get_cora_client()` — nunca instanciar
    `CoraClient` diretamente.
  - `CORA_MODE=mock` (default) usa `CoraMockClient`. `CORA_MODE=real` ainda **não** está
    implementado.
  - O webhook `/admin/financeiro/cora/webhook` é **público** (sem login). Em produção
    precisa validar HMAC do Cora.
  - Comprovantes de despesa em `app/static/uploads/comprovantes/`. Máximo 5 MB.
  - Inadimplência só conta boletos com `status in (aberto, vencido)` E `vencimento < hoje`.

---

## O que já foi implementado

**Admin:** CRUD de alunos (ficha v2 completa), turmas, professores, disciplinas,
responsáveis, usuários. Dashboard com médias, alertas e widget de aniversariantes.
Gestão de cursos com módulos/videoaulas. Configurações do sistema. Aniversariantes
(diário/semanal/mensal). Vínculos de turma com histórico. Relatórios com KPIs/gráficos
e PDF. Backup e restauração. Financeiro completo com plano de pagamento parcelado.

**Professor:** Grid mensal de notas com edição inline, exportação CSV, frequência
por data/turma/disciplina, atividades, observações, histórico do aluno.

**Responsável:** boletim do filho, histórico de frequência, alertas automáticos.

**Aluno:** dashboard com gráfico Chart.js, boletim Jan–Dez, frequência, cursos
matriculados com progresso, player de videoaula com marcação de conclusão.

**Context processor:** `inject_config_sistema()` em `__init__.py` injeta `config_sistema`
em **todos** os templates automaticamente (incluindo `login.html` e `register.html` que
não herdam de `base.html`).

**Redesign visual (2026-05-03):** sistema repaginado — tipografia Sora, paleta azul,
sidebar flutuante, KPIs com gradiente, dark mode persistido em localStorage, drawer
hamburger no mobile. Detalhes em [docs/design-system.md](docs/design-system.md).

---

## O que ainda NÃO foi feito (próximos passos)

1. Exportação de boletim em PDF
2. Envio automático de alertas via WhatsApp/e-mail
3. Deploy em servidor (hoje só roda local)
4. LGPD: termos de uso, logs de acesso
5. Backup **agendado/automático** (hoje é manual — precisaria APScheduler)
6. **Geração mensal automática de mensalidades** (mesma necessidade do scheduler do backup)
7. **`CoraRealClient`** — implementar quando o CoraPro for contratado. Validação HMAC
   do webhook precisa entrar junto.
8. **Fase 5 do redesenho de matrículas** — remover `Aluno.turma_id` e `Aluno.status` (legacy)
   depois que todos os alunos antigos tiverem matrículas migradas.
9. **Gráficos no PDF de relatórios** — exigiria matplotlib (decisão consciente de não
   adicionar a dependência ainda).
10. **Limpeza do multi-plano** — remover `PlanoPagamento.aluno_id` redundante (info vem
    via `matricula.aluno`). Esperar uns ciclos antes de dropar pra ter certeza que
    nenhum código legacy ainda assume a coluna.

---

## Bugs já corrigidos (não reverter)

- `seed_data.py`: usava `Professor(disciplina_id=...)` — modelo não tem esse campo.
  Corrigido para `prof.disciplinas.append(disciplina)`.
- `admin_configuracoes.html`: botão "Remover logo" estava dentro de um `<form>` aninhado
  no form principal — HTML inválido. Corrigido usando `<form id="formRemoverLogo">`
  externo e atributo `form="formRemoverLogo"` no botão.
  **Nunca aninhar `<form>` dentro de outro `<form>`.**
- **Tabelas brancas no dark mode:** Bootstrap 5.3 usa `box-shadow: inset 0 0 0 9999px var(--bs-table-bg)`
  em cada `<td>` pra pintar o fundo. Definir só `background-color` na `.table` não basta —
  precisa neutralizar `--bs-table-bg: transparent` (e variantes hover/striped/active).
- **Utilities `.bg-light`, `.table-light`, `.text-dark` ignoravam o dark mode** porque o Bootstrap
  as marca com `!important` e cores hardcoded. Sobrescritas em `style.css` mapeiam pros tokens
  (ver [docs/design-system.md](docs/design-system.md)).
- **Login e register não herdam de `base.html`** — `base.html` exige `current_user.is_authenticated`.
  Páginas de auth são standalone (carregam Bootstrap CSS + style.css diretamente).
- **Multi-plano + constraint legacy = ERR_CONNECTION_RESET** (2026-05-21): a constraint
  `uq_mensalidade_aluno_mes_ano(aluno_id,mes,ano)` impedia criar mensalidades paralelas
  no mesmo mês quando aluno tinha >1 matrícula. O `IntegrityError` dentro do `flush()`
  com debug mode aberto crashava o socket (não saía 500 limpo). Migration `d7a8e2c3f1b9`
  trocou pra `(matricula_turma_id,mes,ano)`. **Nunca usar `aluno_id+mes+ano` como
  chave única novamente** — esse é o ponto que destrava multi-plano.

---

## Controle de acesso (RBAC)

Matriz padrão por papel + **snapshot customizado por usuário**.
Implementação em [app/permissoes.py](app/permissoes.py),
[app/services_permissoes.py](app/services_permissoes.py) e
[app/templates/admin_usuario_permissoes.html](app/templates/admin_usuario_permissoes.html).
**Detalhes completos em [docs/permissoes.md](docs/permissoes.md).**

### Papéis

| Papel | Resumo |
|---|---|
| `admin` | Wildcard `*`. **Imutável** (não pode ser customizado). |
| `coordenador` | Cadastra (sem editar/excluir), matrícula, financeiro básico, relatórios. |
| `gestor` | Só leitura. |
| `secretario` | Cadastra + edita alunos/responsáveis/profs/turmas, financeiro do dia-a-dia (sem cancelar). |
| `professor`, `responsavel`, `aluno` | UI própria, decorators próprios, não usam a matriz. |

### Permissões customizadas por usuário (2026-05-20)

Admin pode personalizar permissões individualmente em `/admin/usuarios/<id>/permissoes`:
- "Personalizar permissões" → faz snapshot do set padrão do papel em
  `UsuarioPermissao(user_id, chave)` e seta `User.permissoes_customizadas = True`.
- Marca/desmarca checkboxes agrupados por recurso (45 chaves em 13 grupos).
- "Restaurar padrão do papel" → apaga snapshot e volta a herdar do papel.
- **Admin é sempre wildcard** independentemente da flag (proteção "último admin").
- **Self-protection**: admin não edita as próprias permissões (rota redireciona).
- **Customização só vale pros 4 papéis admin-like** (admin/coordenador/gestor/secretário).

### Uso no código

- **Rota**: `@requires('aluno.criar')` → 403 se faltar permissão.
- **Template**: `{% if pode('aluno.editar') %}…{% endif %}` — `pode` é injetado em todo template.
- **Rotas estritamente admin** (raras — ferramentas mock do Cora): mantém `@admin_required` legacy.

### Adicionar papel novo / permissão nova

Ver [docs/permissoes.md](docs/permissoes.md) (checklist completo).

---

## Convenções do projeto

- Blueprints com decorator próprio de autorização: `admin_required`, `professor_required`,
  `aluno_required` (em `routes_aluno.py`) — em vez de roles no Flask-Login.
- Flash messages usam classes Bootstrap: `success`, `danger`, `warning`, `info`.
- Templates herdam de `base.html` via `{% extends 'base.html' %}`.
  Exceções: `login.html` e `register.html` são standalone — mas recebem
  `config_sistema` via context processor.
- Senhas sempre com `bcrypt.hashpw` — nunca salvar em texto puro.
- Formulários de edição/exclusão usam POST com campo hidden `action`.
- O campo `PYTHONPATH=.` é necessário para rodar scripts fora da raiz do projeto.
- Migrações: sempre usar `flask db migrate` + `flask db upgrade`. Nunca confiar só em
  `db.create_all()` para alterar tabelas existentes.
- `render_as_batch=True` está ativo no Migrate — necessário para SQLite suportar
  `ALTER TABLE` via recriação de tabela.
- **Tema dark/light**: nunca hardcode cores hex em templates novos — use sempre os
  tokens do design system. Detalhes em [docs/design-system.md](docs/design-system.md).

---

## Documentação detalhada por módulo

Cada arquivo abaixo é independente. Leia **apenas o que for relevante** pra tarefa atual:

- **[docs/financeiro.md](docs/financeiro.md)** — Cora (mock/real), webhook, comprovantes,
  arquitetura em camadas (services_cora ↔ services_financeiro ↔ routes_admin), limitações.
- **[docs/matriculas.md](docs/matriculas.md)** — multi-vínculo aluno↔turma, status derivado,
  backfill + compat legacy, rotas de vínculos, cascade financeiro.
- **[docs/licenca.md](docs/licenca.md)** — validação via Painel externo, cache + grace offline,
  machine_id (postgres vs sqlite), modos bloqueio/log, endpoints whitelistados, telas.
- **[docs/backup.md](docs/backup.md)** — formato do zip, resolução do path SQLite,
  sequência de restauração com pre-backup, validação de nome de arquivo.
- **[docs/relatorios.md](docs/relatorios.md)** — KPIs, gráficos Chart.js, exportação PDF
  via reportlab, portabilidade SQL (extract vs strftime).
- **[docs/aniversariantes.md](docs/aniversariantes.md)** — escopos dia/semana/mês,
  widget no dashboard, critérios de filtragem.
- **[docs/permissoes.md](docs/permissoes.md)** — RBAC com matriz por papel + snapshot
  customizado por usuário, catálogo, fluxo de personalização, proteções.
- **[docs/design-system.md](docs/design-system.md)** — tokens CSS, componentes,
  sobrescritas obrigatórias do Bootstrap, padrões de UI, ícones.
