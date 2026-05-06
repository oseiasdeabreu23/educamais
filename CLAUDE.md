# CLAUDE.md — Guia para IA: EducaMais

Este arquivo dá contexto completo para qualquer IA que trabalhe neste projeto.
Leia antes de qualquer alteração.

---

## O que é este projeto

**EducaMais** é um sistema web de gestão escolar construído em Python/Flask para o
**Instituto Arvorecer**. Permite que admins, professores, responsáveis e alunos
acompanhem notas, frequência, atividades, alertas e cursos com videoaulas.
O nome e a logo da plataforma são configuráveis pelo admin sem mexer no código.

**Estado atual (2026-05-04):** funcional, testado localmente, com **redesign visual completo**
("Sistema Arvorecer") e **módulo financeiro** (mensalidades, boletos, fluxo de caixa,
inadimplentes) com integração ao Banco Cora em modo mock — ver seções *Design system*
e *Financeiro e integração Cora* abaixo. Em fase de aprimoramento para implantação no instituto.

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
app/services.py           → lógica de negócio pura (médias, alertas, frequência, embed_url)
app/services_backup.py    → criar/restaurar/listar/excluir backups (zip do .db + uploads)
app/services_financeiro.py→ regras do financeiro (mensalidades, boletos, KPIs, fluxo)
app/services_cora.py      → cliente Cora (CoraMockClient, CoraRealClient, factory)
app/static/css/style.css  → design system completo (tokens light + dark, components)
app/static/uploads/       → logos enviadas pelo admin + comprovantes/ (financeiro)
app/templates/base.html   → app-shell (sidebar flutuante + topbar + drawer mobile + tema)
instance/backups/         → onde os arquivos .zip de backup ficam (criado on-demand)
instance/cora_mock.json   → estado persistido do CoraMockClient (boletos + movs fake)
migrations/               → controle de versão do banco (Alembic via Flask-Migrate)
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
- `Responsavel`, `AlunoResponsavel` (N:N)
- `Professor` — disciplinas via N:N `professor_disciplina` (**sem campo `disciplina_id` direto**)
- `Nota` — unique por `(aluno_id, disciplina_id, mes, ano)`
- `Frequencia`, `Atividade`, `Observacao`

### Novos (adicionados em 2026-04-28)
- `Curso` — título, descrição, capa_url, ativo, **`duracao_meses`** (Integer, opcional — adicionado em 2026-05-04 junto do cadastro v2 do aluno)
- `Modulo` — pertence a Curso, tem ordem
- `Videoaula` — pertence a Modulo, tem video_url (YouTube/Vimeo), duracao_min, ordem
- `MatriculaCurso` — N:N entre Aluno e Curso, unique por `(aluno_id, curso_id)`
- `ProgressoVideoaula` — aluno + videoaula + assistido (bool), unique por `(aluno_id, videoaula_id)`
- `ConfigSistema` — singleton (sempre ID=1): `nome` (str) + `logo_path` (str nullable)

### Financeiro (adicionados em 2026-05-04)
- `PlanoPagamento` — `(aluno, n_parcelas, valor_parcela, dia_vencimento, data_primeira, status, observacao)`.
  Status: `ativo|cancelado|concluido`. Um aluno pode ter histórico, mas só **um plano ativo** por vez
  (validado em `services_financeiro.plano_ativo_do_aluno`).
- `Mensalidade.plano_id` — FK opcional pra `PlanoPagamento`. Mensalidades antigas (geradas por lote
  manual) ficam com `plano_id=None`.
- `Mensalidade.cancelada_em` — DateTime opcional, marcado quando o plano é cancelado e a mensalidade
  ainda não tinha boleto pago.
- `Aluno.mensalidade_padrao` — `Numeric(10,2)` opcional (valor sugerido na geração de lote)
- `Mensalidade` — `(aluno, responsavel, mes, ano, valor, vencimento)` — unique por `(aluno_id, mes, ano)`
- `Boleto` — `cora_boleto_id`, `status` (`aberto|pago|vencido|cancelado`), `valor`, `vencimento`,
  `pago_em`, `link_pdf`, `link_boleto`. FK opcional pra `Mensalidade` (cascade)
- `CategoriaDespesa` — `(nome unique, cor)` — categorias editáveis pelo admin
- `Movimentacao` — `tipo` (`entrada|saida`), `categoria_id`, `descricao`, `valor`, `data`,
  `boleto_id` (nullable, vincula entrada de boleto), `comprovante_path`, `criado_por_id`

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
- **Status do aluno** (ativo/evadido/formado):
  - **ativo** é o único que aparece em dashboards, médias, frequência geral, e nos selects de
    professor (lançar nota, frequência, observação). Filtros em `services.media_turma`,
    `services.frequencia_geral`, `services.alunos_baixo_desempenho` (todos têm parâmetro
    `incluir_inativos=False` por default).
  - **evadido**: ao mudar de ativo→evadido em `/admin/alunos`, `services_financeiro.cancelar_plano_aluno`
    é chamado automaticamente. Cancela mensalidades futuras + boletos abertos (no Cora).
    Não toca em mensalidades pagas. Histórico permanece visível em `/admin/financeiro/planos/<aluno_id>`.
  - **formado**: marcação manual. Não cancela nada (assume que tudo foi pago). Some dos dashboards
    de "ativos" mas plano permanece como histórico.
  - Filtro de status na listagem `/admin/alunos?status=ativo|evadido|formado`.
- **Responsável obrigatório só para menores:**
  - `Mensalidade.responsavel_id` é `nullable=True` (migration `08c5c41c858c`).
  - `criar_plano_pagamento` e `gerar_mensalidades_lote` exigem responsável apenas se
    `aluno.idade < 18`. Adultos podem ter plano sem responsável.
  - `emitir_boleto` usa o próprio aluno como pagador (`aluno.cpf`, `aluno.telefone`) quando
    `mensalidade.responsavel is None`.
  - Tela de inadimplentes mostra "Pagador: o próprio aluno" quando não há responsável.
- **Plano de pagamento (parcelamento):**
  - Criado em `/admin/financeiro/planos/<aluno_id>` (botão na linha do aluno).
  - **Estratégia híbrida**: registra todas as N mensalidades de uma vez, mas só **emite o boleto**
    da primeira (e apenas se vencer em ≤ 30 dias — `JANELA_EMISSAO_DIAS`). Próximos boletos são
    emitidos sob demanda (botão por mensalidade) ou via scheduler futuro.
  - **Vencimento empurrado pra próxima segunda** se cair sábado/domingo (`proximo_dia_util`).
    Sem feriados — decisão consciente pra evitar dependência de `python-holidays`.
  - **Início**: se hoje + 5 dias ≤ dia escolhido, começa este mês. Senão, próximo.
  - **Idempotência**: `criar_plano_pagamento` falha com `ValueError` se aluno já tem plano ativo
    (precisa cancelar antes pra criar novo).
  - **Mensalidade pré-existente** do mesmo (aluno, mês, ano) é pulada (constraint do banco), não
    duplica.
- **Financeiro:**
  - Mensalidade é única por `(aluno, mês, ano)` — constraint no banco.
  - Boletos só são gerados via Cora (`services_cora.get_cora_client()`) — nunca instanciar
    `CoraClient` diretamente.
  - `CORA_MODE=mock` (default) usa `CoraMockClient` com estado em `instance/cora_mock.json`.
    `CORA_MODE=real` ainda **não** está implementado — o `CoraRealClient` levanta `NotImplementedError`.
  - O webhook `/admin/financeiro/cora/webhook` é **público** (sem login). Em produção precisa
    validar assinatura HMAC do Cora antes de marcar pagamento.
  - Comprovantes de despesa salvam em `app/static/uploads/comprovantes/comp_<uuid>.<ext>`.
    Formatos: PDF, PNG, JPG, JPEG, WEBP. Máximo 5 MB.
  - Inadimplência só conta boletos com `status in (aberto, vencido)` E `vencimento < hoje`.

---

## O que já foi implementado

**Admin:** CRUD de alunos (ficha v2 completa: CPF com dígito verificador, sexo, cor/raça, telefone,
endereço com ViaCEP, PCD, status `ativo|evadido|formado`, autorização de imagem LGPD, cursos múltiplos),
turmas, professores (N:N disciplinas), disciplinas, responsáveis (N:N alunos), usuários (inclui tipo
`aluno`). Filtro de status na listagem. Dashboard com médias e alertas (só ativos).
Gestão de cursos: criar curso → módulos → videoaulas, matricular/desmatricular alunos, duração em meses.
Configurações do sistema: alterar nome da plataforma e upload de logo.
**Backup e restauração** em `/admin/backup` — gera zip com banco + uploads, baixa,
exclui ou restaura a partir de upload. Restauração cria pre-backup automático e força logout.
**Financeiro** em `/admin/financeiro` — KPIs (recebido, atrasado, a receber hoje, previsto),
mensalidades (gerar lote + emitir boleto), boletos (listar/cancelar/sincronizar), inadimplentes
(escopo mês ou todos, com link WhatsApp), fluxo de caixa (entradas/saídas + lançamento manual
com upload de comprovante), categorias de despesa editáveis. Integração com Banco Cora via
`services_cora` (mock por padrão, real implementado apenas quando o CoraPro for ativado).
**Plano de pagamento parcelado** em `/admin/financeiro/planos/<aluno_id>` (link na linha do aluno):
cria N mensalidades de uma vez, emite boleto da 1ª se vencer em ≤ 30 dias, vencimento empurrado pra
próximo dia útil, cancelamento em massa, histórico. Auto-cancelamento ao mudar status para `evadido`.

**Professor:** Grid mensal de notas (Jan–Dez) com edição inline, exportação CSV,
frequência por data/turma/disciplina, atividades com filtros, observações por aluno,
histórico completo do aluno.

**Responsável:** boletim do filho, histórico de frequência, alertas automáticos.

**Aluno:** dashboard com cards de resumo e gráfico Chart.js (evolução mensal por disciplina),
boletim Jan–Dez com situação por disciplina, frequência com barra de progresso e histórico,
lista de cursos matriculados com progresso, detalhe do curso em accordion, player de videoaula
(embed YouTube/Vimeo) com marcação de aula concluída e navegação anterior/próximo.

**Serviços (`services.py`):** `cpf_valido`, `cep_valido`, `uf_valida`, `so_digitos`, `UFS_BR`,
`media_aluno`, `media_turma(turma, incluir_inativos=False)`, `frequencia_geral(incluir_inativos=False)`,
`alunos_baixo_desempenho(limite=5.5, incluir_inativos=False)`, `queda_desempenho`, `stats_frequencia`,
`faltas_consecutivas`, `alertas_frequencia`, `aviso_whatsapp`, `embed_url`.

**Serviços (`services_financeiro.py`):** `seed_categorias_padrao`, `gerar_mensalidades_lote`,
`criar_mensalidade_avulsa`, `emitir_boleto`, `cancelar_boleto`, `registrar_pagamento_boleto`,
`sincronizar_status_boletos`, `kpis_mes`, `fluxo_caixa`, `inadimplentes`,
`registrar_movimentacao_manual`, **`criar_plano_pagamento`**, **`cancelar_plano_aluno`**,
**`plano_ativo_do_aluno`**, **`proximo_dia_util`**.

**Context processor:** `inject_config_sistema()` em `__init__.py` injeta `config_sistema`
em **todos** os templates automaticamente (incluindo `login.html` e `register.html` que
não herdam de `base.html`).

**Redesign visual (2026-05-03):** sistema repaginado a partir de handoff do Claude Design.
Tipografia Sora, paleta azul moderna, sidebar flutuante, KPIs com gradiente, dark mode com
toggle persistido em localStorage, drawer hamburger no mobile (<980px). Detalhes na seção
*Design system* abaixo.

---

## O que ainda NÃO foi feito (próximos passos)

1. Exportação de boletim em PDF
2. Envio automático de alertas via WhatsApp/e-mail
3. Deploy em servidor (hoje só roda local)
4. LGPD: termos de uso, logs de acesso
5. Backup **agendado/automático** (hoje é manual via `/admin/backup` — agendamento periódico
   precisaria de um scheduler tipo APScheduler)
6. **Geração mensal automática de mensalidades** (mesma necessidade do scheduler do backup).
7. **`CoraRealClient`** (em `services_cora.py`) — implementar quando o CoraPro for contratado.
   Hoje só existe `CoraMockClient`. Validação HMAC do webhook precisa entrar junto.
8. ⚠️ (resolvido) Página `/admin/cursos` crashava com `TypeError` ao tentar `sum(attribute='videoaulas')` em listas — variável `total_videos` removida do template.

---

## Bugs já corrigidos (não reverter)

- `seed_data.py`: usava `Professor(disciplina_id=...)` — modelo não tem esse campo.
  Corrigido para `prof.disciplinas.append(disciplina)`.
- `admin_configuracoes.html`: botão "Remover logo" estava dentro de um `<form>` aninhado
  no form principal — HTML inválido, o browser ignorava o form interno. Corrigido usando
  `<form id="formRemoverLogo">` externo ao form principal e atributo `form="formRemoverLogo"`
  no botão. **Nunca aninhar `<form>` dentro de outro `<form>`.**
- **Tabelas brancas no dark mode:** Bootstrap 5.3 usa `box-shadow: inset 0 0 0 9999px var(--bs-table-bg)`
  em cada `<td>` pra pintar o fundo, e `--bs-table-bg` herda de `--bs-body-bg` (branco).
  Definir só `background-color` na `.table` não basta — precisa neutralizar `--bs-table-bg: transparent`
  (e variantes hover/striped/active) na `.table` em CSS.
- **Utilities `.bg-light`, `.table-light`, `.text-dark` ignoravam o dark mode** porque o Bootstrap
  as marca com `!important` e cores hardcoded. Sobrescritas em `style.css` mapeiam pros tokens
  do design (ver "Sobrescritas obrigatórias do Bootstrap" no design system).
- **Login e register não herdam de `base.html`** — `base.html` exige `current_user.is_authenticated`
  e renderiza só o app-shell. Páginas de auth são standalone (carregam Bootstrap CSS + style.css
  diretamente).

---

## Convenções do projeto

- Blueprints com decorator próprio de autorização: `admin_required`, `professor_required`,
  `aluno_required` (em `routes_aluno.py`) — em vez de roles no Flask-Login.
- Flash messages usam classes Bootstrap: `success`, `danger`, `warning`, `info`.
- Templates herdam de `base.html` via `{% extends 'base.html' %}`.
  Exceções: `login.html` e `register.html` são standalone (carregam Bootstrap CSS + style.css
  diretamente) — mas recebem `config_sistema` via context processor.
- Senhas sempre com `bcrypt.hashpw` — nunca salvar em texto puro.
- Formulários de edição/exclusão usam POST com campo hidden `action`.
- O campo `PYTHONPATH=.` é necessário para rodar scripts fora da raiz do projeto.
- Migrações: sempre usar `flask db migrate` + `flask db upgrade`. Nunca confiar só em
  `db.create_all()` para alterar tabelas existentes.
- `render_as_batch=True` está ativo no Migrate — necessário para SQLite suportar
  `ALTER TABLE` via recriação de tabela.

---

## Backup e restauração

Implementação em [app/services_backup.py](app/services_backup.py) e rotas
`/admin/backup*` em [app/routes_admin.py](app/routes_admin.py).

### Formato do backup
Cada backup é um `.zip` em `instance/backups/` contendo:
- `educamais.db` — snapshot do SQLite via API `sqlite3.backup()` (atômica, funciona com
  conexões abertas — não usar `shutil.copy` direto no arquivo do banco em runtime).
- `uploads/<arquivos>` — todo o conteúdo de `app/static/uploads/`.
- `manifest.json` — `{version, created_at, app, db_size_bytes, uploads}`.

Nome do arquivo: `backup_YYYY-MM-DD_HH-MM-SS.zip`. Pré-restaurações usam prefixo
`pre-restore_` pra distinção fácil na listagem.

### Resolução do caminho do SQLite
`SQLALCHEMY_DATABASE_URI = sqlite:///educamais.db` é **relativo ao `app.instance_path`**
(não ao `root_path`). O helper `_db_path()` cuida disso — se mexer no service, lembrar:
`Path(app.instance_path) / raw`.

### Restauração — rede de segurança
O `restaurar_backup()` sempre cria um `pre-restore_*` antes de sobrescrever, pra dar pra
reverter caso o backup restaurado esteja corrompido ou antigo demais.

Sequência:
1. Valida zip + presença de `educamais.db`.
2. Cria pre-backup automático.
3. `db.session.close()` + `db.engine.dispose()` (libera handles do SQLAlchemy).
4. Sobrescreve `instance/educamais.db`.
5. Limpa `app/static/uploads/` e copia uploads do zip.
6. A rota força `logout_user()` e redireciona pra `/login` (sessão Flask-Login pode
   estar referenciando IDs que mudaram).

### Segurança
- `_extensao_valida` **não** se aplica aqui — quem valida é `caminho_backup()` /
  `excluir_backup()`: rejeitam `..`, `/`, `\` e qualquer nome que não termine em `.zip`.
- Restauração exige campo `confirmacao = "RESTAURAR"` no form (digitado a mão).
- Endpoints todos com `@admin_required`.

### Limitações conhecidas
- Só SQLite por enquanto. Se migrar pro Postgres em prod, trocar `_db_path()` por
  `pg_dump`/`pg_restore` em subprocess.
- Restauração não migra schema — se o backup é de uma versão mais antiga do app
  (com migrations diferentes), pode quebrar. Sempre rodar `flask db upgrade` depois
  de restaurar um backup antigo.

---

## Financeiro e integração Cora

Implementação em [app/services_cora.py](app/services_cora.py),
[app/services_financeiro.py](app/services_financeiro.py) e rotas
`/admin/financeiro*` em [app/routes_admin.py](app/routes_admin.py).
Templates: `admin_financeiro*.html`.

### Arquitetura em camadas

1. **`services_cora.py`** — só fala HTTP com o Cora. Zero conhecimento de models.
   Define a interface `CoraClient` com 4 métodos (`criar_boleto`, `consultar_boleto`,
   `cancelar_boleto`, `listar_movimentacoes`) e duas implementações:
   - `CoraMockClient` — guarda estado em `instance/cora_mock.json`. Tem `simular_pagamento()`
     extra (não existe no real) pra desenvolvimento local.
   - `CoraRealClient` — placeholder (`NotImplementedError`). Implementar quando o
     CoraPro estiver ativo: OAuth2 client_credentials + mTLS, header `Idempotency-Key`
     em criação de boleto, base URL `api.cora.com.br` (staging em `api.stage.cora.com.br`).

   Factory `get_cora_client()` lê `current_app.config['CORA_MODE']` (`mock` default ou `real`).

2. **`services_financeiro.py`** — regras de negócio puras com SQLAlchemy. Funções principais:
   - `seed_categorias_padrao()` — cria 5 categorias defaults (Salário, Aluguel, Material,
     Água/Luz, Outros). Idempotente. Chamada na primeira visita ao dashboard.
   - `gerar_mensalidades_lote(mes, ano, valor_default=None)` — itera alunos com `turma_id`,
     pula quem já tem mensalidade do mês, exige responsável e valor (de `aluno.mensalidade_padrao`
     ou do `valor_default`). Devolve dict com contadores e listas de pulados.
   - `emitir_boleto(mensalidade)` — chama `CoraClient.criar_boleto`, persiste `Boleto`.
   - `registrar_pagamento_boleto(boleto, pago_em=None)` — idempotente: se já está pago,
     não duplica `Movimentacao`. Cria entrada de fluxo com `boleto_id` ligado.
   - `sincronizar_status_boletos()` — fallback ao webhook: itera boletos abertos/vencidos
     e consulta o Cora. Devolve `{pagos, vencidos, erros}`.
   - `kpis_mes`, `fluxo_caixa`, `inadimplentes`, `registrar_movimentacao_manual`.

3. **`routes_admin.py`** — endpoints `/admin/financeiro*`. Todos `@admin_required`,
   exceto `/admin/financeiro/cora/webhook` que é **público** (Cora não autentica antes
   de chamar — em produção, validar HMAC).

### Modo mock vs real

- **Por padrão** o sistema roda em `CORA_MODE=mock`. Não precisa de credenciais.
  Boletos viram entradas no `cora_mock.json`. O botão "Simular pagamento" (ícone
  `bi-check2-square`) só aparece nas tabelas quando o client é o mock — usa
  `isinstance(cora, CoraMockClient)`.
- Pra **trocar pro real** (quando o CoraPro for contratado): `.env` com `CORA_MODE=real`,
  implementar `CoraRealClient.__init__` com `requests.Session(cert=(cert_path, key_path))`,
  e implementar os 4 métodos contra `https://api.cora.com.br/`.
- O `cora_mock.json` **é** incluído no backup automático (está em `instance/`, e o backup
  copia o `.db`, mas o JSON do mock fica de fora — é estado de desenvolvimento, não dado
  de produção). Em produção real, o estado vive no Cora, não no app.

### Webhook do Cora

Endpoint `POST /admin/financeiro/cora/webhook` aceita JSON `{cora_id, evento}`
onde `evento ∈ {pago, cancelado}`. Sem autenticação Flask-Login (Cora chama de fora).

**Em produção**: o Cora envia um header com assinatura HMAC — validar antes de chamar
`registrar_pagamento_boleto()`. Sem essa validação, qualquer um na internet pode marcar
boleto como pago. **Não esquecer disso ao implementar `CoraRealClient`.**

Pra desenvolvimento local sem URL pública, usar o botão "Simular pagamento" no admin
ou chamar diretamente o endpoint via curl.

### Comprovantes

Lançamentos manuais de despesa (`/admin/financeiro/movimentacao/nova`) aceitam upload
opcional de comprovante. Salvos em `app/static/uploads/comprovantes/comp_<uuid12>.<ext>`,
acessíveis via `url_for('static', filename='uploads/' + comprovante_path)`. O backup
automático cobre essa pasta (parte de `app/static/uploads/`).

Validação no `routes_admin.py`: extensões em `COMPROVANTE_EXTENSOES`, tamanho máximo
em `COMPROVANTE_MAX_BYTES` (5 MB). Movimentação vinda de boleto **não** aceita
exclusão pelo botão de lixeira (cancelar o boleto é o caminho).

### Limitações conhecidas

- Geração mensal automática não está implementada — admin precisa clicar "Gerar lote"
  todo mês. Implementar com APScheduler quando o sistema estiver em produção contínua.
- `CoraRealClient` não implementado. Tudo testado em mock.
- Mock não gera PDF real — endpoints `/admin/financeiro/cora/mock-pdf/<cora_id>` e
  `/admin/financeiro/cora/mock-boleto/<cora_id>` retornam texto placeholder. Em produção
  o Cora retorna a URL pública do PDF/boleto.
- Lembrete por WhatsApp na tela de inadimplentes é só um link `wa.me/` — não envia
  automaticamente. Disparo automático fica pra fase 2 (provavelmente via `services.aviso_whatsapp`).

---

## Design system

Tokens, componentes e padrões visuais. Tudo em [app/static/css/style.css](app/static/css/style.css).

### Tokens (CSS custom properties)

Light é o default; dark é ativado via `data-theme="dark"` no `<html>` (toggle no topbar
persiste em `localStorage` com a chave `arvorecer-theme`).

- **Brand:** azul `--brand-500: #3b82f6` (light usa `--primary: #2563eb`, dark usa `#3b82f6`).
- **Texto:** `--text` (principal), `--text-2` (secundário), `--text-3` (legendas/dim).
  No dark, `--text-3` é `#9ba5c4` (passa WCAG AA — não baixar).
- **Surface:** `--bg`, `--bg-2` (sidebar/topbar), `--surface` (card), `--surface-2`/`--surface-3`
  (hover/nested).
- **Score:** `--score-ok-bg/fg`, `--score-warn-bg/fg`, `--score-bad-bg/fg`. No dark os bg
  são `rgba(...,.22-.24)` + borda colorida (definida em regras `[data-theme="dark"]`)
  pra dar forma sobre o surface escuro.
- **Tipografia:** Sora (Google Fonts) em `--font-display` e `--font-body`.
- **Radius:** `--r-sm 8`, `--r-md 12`, `--r-lg 18` (cards), `--r-xl 24` (sidebar/topbar).
- **Aliases legados:** `--success`, `--danger`, `--warning`, `--text-primary`, `--text-muted`,
  `--card-bg`, etc. apontam pros tokens novos — preservados pra não quebrar templates antigos.

### Componentes principais

- **`.app-shell`** (no `<body class="app">`): grid de duas colunas — sidebar 248px + main.
- **`.sidebar`** flutuante com `border-radius` 24, fundo `--bg-2`, sticky. No mobile
  (<980px) vira drawer com `transform: translateX(-100%)` controlado por `.drawer-open` no body.
- **`.topbar`** com título + subtítulo, busca e botões de ícone (notificações + toggle de tema).
- **`.kpi`** com 6 variantes (`.kpi-blue`, `.kpi-cyan`, `.kpi-violet`, `.kpi-emerald`,
  `.kpi-amber`, `.kpi-rose`, `.kpi-soft`). Usadas em todos os dashboards.
- **`.score`** + `.score-ok/warn/bad` (notas e médias). Sempre com `font-variant-numeric: tabular-nums`.
- **`.badge`** pill (default + variantes `.badge-ok/warn/bad/info/primary`). Aliases pras
  classes do Bootstrap (`.bg-success`, `.bg-danger`, etc.) mapeiam pra `.badge-ok/bad`.
- **`.donut`** CSS-only via `conic-gradient` (usado no dashboard do responsável).
- **`.quick-action`** botão de ação rápida com ícone colorido + título + sub.
- **`.empty-state`** padrão pra "sem dados ainda".

### Sobrescritas obrigatórias do Bootstrap

Carregamos o Bootstrap 5.3 (modal, accordion, dropdown, grid, utilities) mas vários
utilities forçam cores claras com `!important`. As sobrescritas estão em `style.css`:

- `--bs-table-bg: transparent` e `--bs-table-hover-bg: var(--surface-2)` na `.table`
  (Bootstrap pinta cada `<td>` via box-shadow inset).
- `.bg-light` → `var(--surface-2)` / `.bg-white` → `var(--surface)`.
- `.table-light` (em `<thead>` ou `<tr>`) → mapeada pros tokens **e** com `box-shadow inset`
  pra vencer o truque do Bootstrap.
- `.text-dark`/`.text-light` em dark mode → `var(--text)` (senão badges com texto preto
  forçado ficam ilegíveis sobre fundo escuro).
- `.modal-content`, `.accordion-item`, `.accordion-button`, `.list-group-item`,
  `.breadcrumb-item`, `.alert.*` — todos restilizados pra usar tokens.

### Padrões de UI

- **Empty state**: ícone Bootstrap-Icons grande + opacidade 0.35 + mensagem dim centralizada.
- **Score colorido por faixa**: <5 = bad (vermelho), 5–6.9 = warn (amarelo), ≥7 = ok (verde).
- **CRUD admin**: form à esquerda (col-lg-4) + tabela à direita (col-lg-8) com modal de edição.
- **Breadcrumb**: usar Bootstrap markup (`<nav><ol class="breadcrumb">...`) — CSS já restilizado.
- **Forms**: usar `.input`, `.label`, `.select` (estilizados via tokens).
  `.form-control`/`.form-select`/`.form-label` do Bootstrap também funcionam (mesmo estilo).
- **Tema dark/light**: respeite os tokens — **nunca hardcode cores hex em templates novos**.
  Para cores semânticas use `var(--ok|warn|bad|primary)`. Para texto use `var(--text|text-2|text-3)`.

### Ícones

Usamos **Bootstrap Icons** (não os ícones Lucide do design original). Mapeamentos comuns:
`bi-tree-fill` (brand), `bi-grid-fill` (dashboard), `bi-people-fill` (turmas),
`bi-mortarboard-fill` (professores), `bi-play-btn-fill` (cursos), `bi-pencil-fill` (notas),
`bi-check-circle-fill` (frequência), `bi-clipboard-fill` (atividades), `bi-bell-fill`
(notificações), `bi-moon-stars-fill`/`bi-sun-fill` (toggle tema).
