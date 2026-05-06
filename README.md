# EducaMais — Sistema de Gestão Escolar

Plataforma web de gestão escolar desenvolvida para o **Instituto Arvorecer**.
Permite que administradores, professores, responsáveis e alunos acompanhem
notas, frequência, atividades, alertas, cursos com videoaulas e o financeiro
da instituição (mensalidades, boletos, fluxo de caixa, inadimplentes).

> **Status (2026-05-04):** funcional, redesign visual completo ("Sistema Arvorecer"),
> cadastro de aluno expandido (CPF, endereço, PCD, LGPD), plano de pagamento
> parcelado por aluno com auto-cancelamento por status, módulo financeiro com
> integração Cora em modo mock. Em fase de aprimoramento para implantação no
> Instituto Arvorecer.

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Stack tecnológica](#2-stack-tecnológica)
3. [Estrutura de arquivos](#3-estrutura-de-arquivos)
4. [Modelos de dados](#4-modelos-de-dados)
5. [Rotas e endpoints](#5-rotas-e-endpoints)
6. [Lógica de negócio](#6-lógica-de-negócio)
7. [Como rodar](#7-como-rodar)
8. [Contas de teste](#8-contas-de-teste)
9. [O que já foi feito](#9-o-que-já-foi-feito)
10. [Bugs conhecidos e corrigidos](#10-bugs-conhecidos-e-corrigidos)
11. [Próximos passos](#11-próximos-passos)

---

## 1. Visão geral

Quatro perfis de usuário com acesso separado:

| Perfil | O que pode fazer |
|---|---|
| **Admin** | CRUD completo de alunos, turmas, professores, disciplinas, responsáveis, usuários e cursos. Vê relatórios gerais. Gerencia backup, configurações do sistema (nome/logo) e o financeiro (mensalidades, boletos, inadimplentes, fluxo de caixa). |
| **Professor** | Lança notas mensais, registra frequência por data/disciplina, cria atividades, escreve observações, exporta CSV, vê histórico do aluno. |
| **Responsável** | Consulta boletim do filho, histórico de frequência, atividades e alertas automáticos. |
| **Aluno** | Acompanha o próprio boletim, frequência e cursos online (com videoaulas embutidas). |

O sistema **não depende de internet** para o uso básico — roda localmente com
SQLite. A integração com o Banco Cora (financeiro) está em modo mock por
padrão; quando a conta CoraPro for ativada, basta trocar a config para acessar
a API real.

---

## 2. Stack tecnológica

| Camada | Tecnologia | Versão |
|---|---|---|
| Linguagem | Python | 3.14 |
| Framework web | Flask | 2.3.3 |
| ORM | Flask-SQLAlchemy | 3.0.5 |
| Migrações | Flask-Migrate / Alembic | 4.0.4 |
| Autenticação | Flask-Login | 0.6.3 |
| Hash de senha | bcrypt | 4.0.1 |
| Variáveis de ambiente | python-dotenv | 1.0.0 |
| Banco de dados (dev) | SQLite | — |
| Banco de dados (prod) | PostgreSQL | — |
| Frontend | HTML + Jinja2 + Bootstrap 5.3 + Bootstrap Icons | — |
| Tipografia | Sora (Google Fonts) | — |
| Gráficos | Chart.js | — |
| Integração financeira | Banco Cora (mTLS + OAuth2) | mock por padrão |

---

## 3. Estrutura de arquivos

```
EducaMais/
├── app/
│   ├── __init__.py            # Factory create_app(); registra blueprints e context processor
│   ├── models.py              # Todos os modelos SQLAlchemy
│   ├── auth.py                # Blueprint de autenticação (login/logout/register)
│   ├── routes_admin.py        # Blueprint /admin (CRUDs + cursos + backup + financeiro)
│   ├── routes_professor.py    # Blueprint /professor
│   ├── routes_responsavel.py  # Blueprint /responsavel
│   ├── routes_aluno.py        # Blueprint /aluno (boletim + cursos + videoaulas)
│   ├── services.py            # Lógica de negócio: médias, alertas, frequência, embed_url
│   ├── services_backup.py     # Criar/restaurar/listar backups (zip do .db + uploads)
│   ├── services_financeiro.py # Regras do financeiro (mensalidades, KPIs, fluxo)
│   ├── services_cora.py       # Cliente Cora (CoraMockClient, CoraRealClient, factory)
│   ├── static/
│   │   ├── css/style.css      # Design system (tokens light + dark, components)
│   │   ├── js/main.js
│   │   └── uploads/           # Logos do sistema + comprovantes/ (financeiro)
│   └── templates/
│       ├── base.html          # App-shell: sidebar flutuante + topbar + drawer mobile + tema
│       ├── login.html | register.html
│       ├── dashboard_admin.html | dashboard_professor.html | dashboard_responsavel.html
│       ├── admin_*.html       # Telas do admin (alunos, turmas, ..., backup, financeiro_*)
│       ├── professor_*.html   # Notas, frequência, atividades, observações, histórico
│       ├── responsavel_*.html # Dashboard, alertas
│       └── aluno_*.html       # Dashboard, boletim, frequência, cursos, videoaula
├── migrations/                # Alembic (Flask-Migrate, render_as_batch=True para SQLite)
│   └── versions/*.py
├── scripts/
│   ├── init_db.sql            # Schema PostgreSQL (referência para produção)
│   ├── seed_data.py           # Popula banco com dados de exemplo
│   └── vincular_professores.py
├── instance/
│   ├── educamais.db           # Banco SQLite (gerado automaticamente)
│   ├── backups/               # Zip de backup (criado on-demand)
│   └── cora_mock.json         # Estado do CoraMockClient (boletos + movs fake)
├── venv/                      # Ambiente virtual Python (não versionado)
├── run.py                     # Ponto de entrada: cria app e inicia servidor
├── iniciar.bat                # Atalho Windows pra ativar venv + rodar run.py
├── requirements.txt
├── .env                       # SECRET_KEY, PORT, CORA_MODE
├── CLAUDE.md                  # Guia técnico para IAs trabalhando no projeto
└── README.md
```

---

## 4. Modelos de dados

### Relacionamentos

```
Turma 1───N Aluno N───N Responsavel
Turma 1───N Professor
Professor N───N Disciplina
Aluno 1───N Nota (por disciplina + mês + ano)
Aluno 1───N Frequencia (por disciplina + data)
Aluno 1───N Observacao (por professor)
Aluno 1───1 User (vínculo opcional pra dar acesso)
Turma 1───N Atividade
Disciplina 1───N Atividade

Curso 1───N Modulo 1───N Videoaula
Aluno N───N Curso (via MatriculaCurso)
Aluno + Videoaula → ProgressoVideoaula

Aluno 1───N Mensalidade 1───N Boleto
Boleto 1───1 Movimentacao (entrada quando pago)
CategoriaDespesa 1───N Movimentacao (saídas manuais)
ConfigSistema (singleton: nome + logo)
```

### Tabelas

| Tabela | Campos principais |
|---|---|
| `usuarios` | id, nome, email, senha (bcrypt), tipo (admin/professor/responsavel/aluno) |
| `turmas` | id, nome |
| `disciplinas` | id, nome |
| `alunos` | id, nome, data_nascimento, turma_id, user_id (opcional), **mensalidade_padrao**, **cpf (unique)**, **sexo, cor_raca, telefone**, endereço (**cep, logradouro, numero, complemento, bairro, cidade, uf**), **pcd + pcd_descricao**, **status (ativo/evadido/formado)**, **autoriza_imagem + data_consentimento_imagem** |
| `responsaveis` | id, nome, telefone, email |
| `aluno_responsavel` | aluno_id, responsavel_id (junção N:N) |
| `professores` | id, nome, turma_id, user_id |
| `professor_disciplina` | professor_id, disciplina_id (junção N:N) |
| `notas` | id, aluno_id, disciplina_id, mes (1–12), ano, valor; UNIQUE(aluno+disc+mes+ano) |
| `frequencias` | id, aluno_id, disciplina_id, data, status (presente/falta/justificada) |
| `atividades` | id, titulo, descricao, data, turma_id, disciplina_id, professor_id |
| `observacoes` | id, aluno_id, professor_id, texto, data |
| `cursos` | id, titulo, descricao, capa_url, ativo, **duracao_meses** |
| `modulos` | id, curso_id, titulo, ordem |
| `videoaulas` | id, modulo_id, titulo, video_url (YouTube/Vimeo), duracao_min, ordem |
| `matriculas_curso` | id, aluno_id, curso_id; UNIQUE(aluno+curso) |
| `progresso_videoaulas` | id, aluno_id, videoaula_id, assistido, data; UNIQUE(aluno+videoaula) |
| `config_sistema` | id (singleton), nome, logo_path |
| **`mensalidades`** | id, aluno_id, **responsavel_id (opcional, só obrigatório para menores)**, **plano_id (opcional)**, mes, ano, valor, vencimento, observacao, **cancelada_em**; UNIQUE(aluno+mes+ano) |
| **`planos_pagamento`** | id, aluno_id, n_parcelas, valor_parcela, dia_vencimento, data_primeira, status (ativo/cancelado/concluido), observacao, criado_em, cancelado_em |
| **`boletos`** | id, mensalidade_id, cora_boleto_id, status (aberto/pago/vencido/cancelado), valor, vencimento, pago_em, link_pdf, link_boleto |
| **`categorias_despesa`** | id, nome (unique), cor |
| **`movimentacoes`** | id, tipo (entrada/saida), categoria_id, descricao, valor, data, boleto_id, comprovante_path, criado_por_id |

---

## 5. Rotas e endpoints

### Autenticação (`auth_bp`, sem prefixo)

| Método | Rota | Descrição |
|---|---|---|
| GET/POST | `/login` | Tela de login. POST autentica e redireciona por tipo de usuário |
| GET/POST | `/register` | Cadastro de novo usuário |
| GET | `/logout` | Encerra sessão e redireciona para login |
| GET | `/` | Redireciona para `/login` |

### Admin (`admin_bp`, prefixo `/admin`)

#### Cadastros
| Rota | Descrição |
|---|---|
| `/admin/dashboard` | Painel: média geral, % frequência, alunos abaixo de 5.5 |
| `/admin/alunos` | Listar/cadastrar/editar/excluir alunos |
| `/admin/turmas` | CRUD de turmas (bloqueia exclusão se houver alunos) |
| `/admin/professores` | CRUD com associação N:N a disciplinas |
| `/admin/disciplinas` | CRUD de disciplinas |
| `/admin/responsaveis` | CRUD com vinculação N:N a alunos |
| `/admin/usuarios` | CRUD de usuários (admin/professor/responsavel/aluno) |
| `/admin/vincular` | Vincular aluno a turma |

#### Cursos
| Rota | Descrição |
|---|---|
| `/admin/cursos` | Listar cursos |
| `/admin/cursos/<id>` | Detalhe: módulos, videoaulas, matrícula |
| `/admin/cursos/<id>/excluir` | Excluir curso |

#### Sistema
| Rota | Descrição |
|---|---|
| `/admin/configuracoes` | Nome do sistema + upload de logo |
| `/admin/backup` | Listar/criar/baixar/excluir/restaurar backups |
| `/admin/backup/criar` (POST) | Gera novo zip |
| `/admin/backup/restaurar` (POST) | Restaura de upload (cria pre-restore automático) |

#### Financeiro
| Rota | Descrição |
|---|---|
| `/admin/financeiro` | Dashboard com 4 KPIs + últimas movimentações |
| `/admin/financeiro/mensalidades` | Listar mensalidades do mês, gerar lote |
| `/admin/financeiro/mensalidades/lote` (POST) | Cria 1 mensalidade por aluno do mês |
| `/admin/financeiro/planos/<aluno_id>` | Plano de pagamento parcelado por aluno (criar / listar parcelas / cancelar / histórico) |
| `/admin/financeiro/planos/<aluno_id>/criar` (POST) | Cria plano + N mensalidades; emite boleto da 1ª se vence em ≤ 30 dias |
| `/admin/financeiro/planos/<aluno_id>/cancelar` (POST) | Cancela plano + mensalidades futuras + boletos abertos no Cora |
| `/admin/financeiro/boletos` | Listar boletos com filtros + sincronizar status |
| `/admin/financeiro/boletos/emitir/<mensalidade_id>` (POST) | Emite boleto via Cora |
| `/admin/financeiro/boletos/<id>/cancelar` (POST) | Cancela boleto |
| `/admin/financeiro/inadimplentes` | Cards aluno+responsável + link WhatsApp |
| `/admin/financeiro/fluxo-caixa` | Entradas/saídas + lançamento manual |
| `/admin/financeiro/movimentacao/nova` (POST) | Lança despesa/entrada com comprovante opcional |
| `/admin/financeiro/categorias` | CRUD de categorias de despesa |
| `/admin/financeiro/cora/webhook` (POST, **público**) | Recebe notificação do Cora |
| `/admin/financeiro/cora/simular-pagamento/<boleto_id>` (POST, mock) | Marca como pago para teste |

### Professor (`professor_bp`, prefixo `/professor`)

| Rota | Descrição |
|---|---|
| `/professor/dashboard` | Visão geral dos alunos |
| `/professor/lancar-nota` | Grid mensal de notas (Jan–Dez) por turma/disciplina/ano |
| `/professor/notas/exportar` | Exporta CSV (BOM UTF-8 para Excel) |
| `/professor/frequencia` | Registrar frequência por turma/disciplina/data |
| `/professor/atividade` | Criar/listar atividades com filtros |
| `/professor/observacoes` | Registrar observação sobre aluno |
| `/professor/aluno/<id>` | Histórico completo (notas, frequência, observações) |

### Responsável (`responsavel_bp`, prefixo `/responsavel`)

| Rota | Descrição |
|---|---|
| `/responsavel/dashboard` | Boletim, frequência e atividades do(s) filho(s) |
| `/responsavel/alertas` | Alertas de desempenho e frequência |

### Aluno (`aluno_bp`, prefixo `/aluno`)

| Rota | Descrição |
|---|---|
| `/aluno/dashboard` | Cards de resumo + Chart.js de evolução mensal |
| `/aluno/boletim` | Boletim Jan–Dez com situação por disciplina |
| `/aluno/frequencia` | Barra de progresso + histórico |
| `/aluno/cursos` | Cursos matriculados com progresso |
| `/aluno/curso/<id>` | Detalhe do curso (accordion) |
| `/aluno/videoaula/<id>` | Player embed YouTube/Vimeo + marcar concluída |

---

## 6. Lógica de negócio

### `services.py` (acadêmico)
| Função | O que faz |
|---|---|
| `cpf_valido(cpf)` | Valida CPF pelos dois dígitos verificadores |
| `cep_valido(cep)`, `uf_valida(uf)` | Validações de endereço |
| `so_digitos(valor)` | Remove tudo que não é dígito |
| `media_aluno(aluno)` | Média geral de todas as notas do aluno |
| `media_turma(turma, incluir_inativos=False)` | Média da turma; só ativos por default |
| `frequencia_geral(incluir_inativos=False)` | % presença global; só ativos por default |
| `alunos_baixo_desempenho(limite=5.5, incluir_inativos=False)` | Lista alunos abaixo do limite (só ativos por default) |
| `queda_desempenho(aluno, disciplina_id)` | Detecta 3 notas em queda consecutiva |
| `stats_frequencia(aluno, disciplina_id)` | Total, presenças, faltas, justificadas, % |
| `faltas_consecutivas(aluno, disciplina_id, n=3)` | True se últimas N forem todas falta |
| `alertas_frequencia(aluno, disciplina_id)` | Alertas: <75% e/ou 3+ faltas seguidas |
| `aviso_whatsapp(aluno, disciplina)` | Texto formatado pra copiar no WhatsApp |
| `embed_url(youtube_or_vimeo_url)` | Converte URL pública em URL embutível |

### `services_financeiro.py`
| Função | O que faz |
|---|---|
| `seed_categorias_padrao()` | Cria 5 categorias defaults (idempotente) |
| `gerar_mensalidades_lote(mes, ano, valor_default=None)` | Itera alunos, cria mensalidades (responsável só obrigatório p/ menor) |
| `criar_mensalidade_avulsa(...)` | Mensalidade fora do lote (ajustes) |
| `emitir_boleto(mensalidade)` | Chama Cora e persiste `Boleto`. Usa aluno como pagador se não há responsável |
| `cancelar_boleto(boleto)` | Cancela no Cora e marca status |
| `registrar_pagamento_boleto(boleto, pago_em)` | Marca pago + cria entrada no fluxo |
| `sincronizar_status_boletos()` | Polling: consulta Cora pra cada boleto aberto |
| `kpis_mes(mes, ano)` | Recebido, atrasado, a receber hoje, previsto |
| `fluxo_caixa(de, ate)` | Entradas, saídas, saldo, movimentações |
| `inadimplentes(escopo, mes, ano)` | Lista por aluno+responsável (responsavel pode ser None) |
| `registrar_movimentacao_manual(...)` | Lançamento avulso de entrada/saída |
| **`criar_plano_pagamento(aluno, n, valor, dia, ...)`** | Cria `PlanoPagamento` + N mensalidades; emite boleto da 1ª se vence em ≤ 30 dias |
| **`cancelar_plano_aluno(aluno, motivo)`** | Cancela plano ativo + mensalidades futuras + boletos abertos no Cora |
| **`plano_ativo_do_aluno(aluno)`** | Retorna o `PlanoPagamento` com `status='ativo'` (ou None) |
| **`proximo_dia_util(d)`** | Empurra para próxima segunda se cair sábado/domingo |

### `services_cora.py`
| Componente | O que é |
|---|---|
| `CoraClient` | Interface base (4 métodos) |
| `CoraMockClient` | Implementação fake com estado em `instance/cora_mock.json` |
| `CoraRealClient` | Placeholder — implementar quando CoraPro estiver ativo |
| `get_cora_client()` | Factory que lê `CORA_MODE` do `.env` |

### `services_backup.py`
| Função | O que faz |
|---|---|
| `criar_backup(app, prefixo='backup')` | Snapshot SQLite via `sqlite3.backup()` + uploads em zip |
| `restaurar_backup(app, file_storage)` | Cria pre-restore + sobrescreve banco/uploads |
| `listar_backups(app)` | Lista zip ordenados por data |
| `excluir_backup(app, nome)` | Remove um zip (com bloqueio de path traversal) |

### Regras de alerta (acadêmico)
- Frequência < 75% → alerta
- 3 ou mais faltas consecutivas → alerta
- Últimas 3 notas em queda contínua → alerta de queda de rendimento
- Média < 5.5 → listado como baixo desempenho no dashboard admin

### Regras do financeiro
- Mensalidade é única por `(aluno, mês, ano)` — constraint no banco
- Inadimplência conta boletos com `status in (aberto, vencido)` E `vencimento < hoje`
- Boletos só são gerados via `services_cora.get_cora_client()` — nunca instanciar `CoraClient` direto
- `CORA_MODE=mock` (default) ou `real` (não implementado ainda)
- Webhook do Cora é público — em produção precisa validar HMAC antes de marcar pagamento
- **Responsável obrigatório só para menores de 18.** Adultos podem ter mensalidade/plano sem responsável; o próprio aluno vira pagador no Cora.
- **Plano de pagamento (estratégia híbrida):** cria N mensalidades de uma vez, mas só emite o boleto da 1ª (e apenas se vencer em ≤ 30 dias). Próximas emitidas sob demanda.
- **Vencimento empurrado para próxima segunda** se cair em sábado/domingo (sem feriados — decisão consciente para evitar dependência externa).
- **Auto-cancelamento por status:** ao mudar `status` do aluno de `ativo` → `evadido`, o plano ativo é cancelado automaticamente (mensalidades futuras + boletos abertos no Cora). Mensalidades pagas permanecem.

### Regras do cadastro de aluno
- **CPF**: salvo só com dígitos (11 chars), unique. Validação com algoritmo dos dois dígitos verificadores. Property `cpf_formatado` para exibição.
- **CEP**: salvo só com dígitos (8 chars). Form usa ViaCEP em JS para auto-preencher logradouro/bairro/cidade/uf.
- **Status**: `ativo` (default) / `evadido` / `formado`. Só `ativo` aparece em dashboards, médias gerais e selects de professor.
- **Idade**: property calculada a partir de `data_nascimento` (não é coluna).
- **LGPD**: campo `autoriza_imagem` (bool) + `data_consentimento_imagem` (Date auto-preenchida ao marcar).

---

## 7. Como rodar

### Pré-requisitos
- Python 3.10+
- O venv já está criado em `venv/`

```bash
# 1. Ativar o ambiente virtual (Windows)
venv\Scripts\Activate.ps1     # PowerShell
venv\Scripts\activate.bat     # CMD

# 2. Instalar dependências (apenas na primeira vez)
pip install -r requirements.txt

# 3. Criar .env na raiz (apenas na primeira vez)
# SECRET_KEY=uma_chave_forte_qualquer
# DATABASE_URL=sqlite:///educamais.db
# PORT=5555
# CORA_MODE=mock

# 4. Aplicar migrações (cria/atualiza schema do banco)
venv\Scripts\python.exe -m flask db upgrade

# 5. Popular com dados de exemplo (opcional, primeira vez)
set PYTHONPATH=.
venv\Scripts\python.exe scripts\seed_data.py

# 6. Subir servidor
venv\Scripts\python.exe run.py
# Ou: iniciar.bat (atalho Windows)

# 7. Acessar
# http://127.0.0.1:5555/login
```

> **Atenção:** a porta padrão é **5555** (não 5000) — 5000 conflita com AirTunes
> em Windows/macOS. Dá pra trocar na variável `PORT` do `.env`.

> **Migrações:** sempre rodar `flask db migrate` + `flask db upgrade` ao alterar
> models. Não confiar só em `db.create_all()` — ele não atualiza tabelas existentes.

---

## 8. Contas de teste

| Tipo | E-mail | Senha |
|---|---|---|
| Administrador | admin@escola.com | admin123 |
| Professor | prof@escola.com | prof123 |
| Responsável | resp@escola.com | resp123 |
| Aluno | aluno@escola.com | aluno123 |

---

## 9. O que já foi feito

### Infraestrutura
- [x] Projeto Flask com factory pattern (`create_app`)
- [x] Blueprints separados por perfil (auth, admin, professor, responsavel, aluno)
- [x] Autenticação com Flask-Login + bcrypt
- [x] Banco SQLite para dev, schema PostgreSQL pronto pra produção
- [x] Migrações Alembic via Flask-Migrate (`render_as_batch=True` pra SQLite)
- [x] Context processor injeta `config_sistema` em todos os templates

### Admin
- [x] Dashboard com média geral, % frequência e alunos abaixo da média (só ativos)
- [x] CRUD de alunos com **ficha completa v2** (CPF, sexo, cor/raça, endereço com ViaCEP, PCD, LGPD, status, cursos múltiplos)
- [x] Filtro de status na listagem de alunos (Todos / Ativo / Evadido / Formado)
- [x] CRUD de turmas, professores (N:N disciplinas), disciplinas
- [x] CRUD de responsáveis (N:N alunos), usuários (todos os tipos)
- [x] Gestão de cursos: criar curso → módulos → videoaulas, matricular alunos, **duração em meses**
- [x] Configurações do sistema (nome + upload de logo)
- [x] **Backup e restauração**: zip do banco + uploads, pre-restore automático
- [x] **Financeiro**: KPIs, mensalidades (gerar lote), boletos (emitir/cancelar/sincronizar),
      inadimplentes (com link WhatsApp), fluxo de caixa (lançamento manual com comprovante),
      categorias de despesa editáveis, integração Cora em modo mock
- [x] **Plano de pagamento parcelado por aluno** (`/admin/financeiro/planos/<aluno_id>`): cria N mensalidades, emite 1º boleto se ≤30 dias, vencimento em dia útil, cancelamento em massa, histórico
- [x] **Auto-cancelamento de plano** quando aluno é marcado como `evadido`

### Professor
- [x] Grid mensal de notas (Jan–Dez) com edição inline
- [x] Exportação de notas em CSV (compatível com Excel via BOM UTF-8)
- [x] Frequência por data/turma/disciplina, com totalizadores
- [x] Atividades com filtros, observações, histórico do aluno

### Responsável
- [x] Boletim do(s) filho(s), frequência, atividades
- [x] Tela de alertas (frequência, faltas consecutivas, queda)

### Aluno
- [x] Dashboard com cards e Chart.js de evolução mensal
- [x] Boletim Jan–Dez com situação por disciplina
- [x] Frequência com barra de progresso e histórico
- [x] Cursos matriculados com progresso, accordion, player embed YouTube/Vimeo
- [x] Marcar videoaula como concluída + navegação anterior/próximo

### Visual
- [x] Redesign completo "Sistema Arvorecer" (Sora, paleta azul, sidebar flutuante)
- [x] Dark mode com toggle + persistência em localStorage
- [x] Drawer mobile (<980px), responsivo

---

## 10. Bugs conhecidos e corrigidos

| Bug | Status | Detalhe |
|---|---|---|
| `seed_data.py` usava `disciplina_id=` no construtor de `Professor` | Corrigido | Modelo não tem campo direto; usa N:N. `prof.disciplinas.append(disciplina)`. |
| `admin_configuracoes.html` tinha `<form>` aninhado | Corrigido | Browser ignora forms aninhados. Refatorado com `form="formRemoverLogo"`. |
| Tabelas brancas no dark mode | Corrigido | Bootstrap 5.3 pinta `<td>` via `box-shadow inset` — neutralizado com `--bs-table-bg: transparent`. |
| `.bg-light/.text-dark` ignorando dark mode | Corrigido | Bootstrap usa `!important` — overrides em `style.css` mapeiam pros tokens. |
| Página `/admin/cursos` crashava com `TypeError` | Corrigido | `sum(attribute='videoaulas')` em listas — variável removida do template. |

---

## 11. Próximos passos

### Prioritários
- [ ] Exportação de boletim em PDF (sugestão: WeasyPrint ou ReportLab)
- [ ] Envio automático de alertas via WhatsApp (Z-API ou Evolution API) e e-mail
- [ ] Deploy em servidor (VPS, Railway ou Render) — pré-requisito pro webhook real do Cora
- [ ] Implementar `CoraRealClient` (auth mTLS + OAuth2, validação HMAC do webhook) quando o CoraPro for contratado

### Médio prazo
- [ ] Geração mensal automática de mensalidades (APScheduler)
- [ ] Backup agendado/automático (mesma necessidade do scheduler acima)
- [ ] Relatórios financeiros (DRE simplificado, exportação CSV/PDF)
- [ ] Conciliação bancária via importação OFX

### Conformidade
- [ ] LGPD: termos de uso, política de privacidade, logs de acesso
- [ ] Tratamento de CPF do responsável (hoje hardcoded `'00000000000'` no mock)

---

*Última atualização: 2026-05-04 — README sincronizado com cadastro v2, plano de pagamento parcelado, comportamento por status e regra de responsável só para menores. Para detalhes técnicos, decisões de design e regras críticas, ver [CLAUDE.md](CLAUDE.md).*
