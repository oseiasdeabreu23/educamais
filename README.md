# EducaMais — Sistema de Gestão Escolar

Plataforma web de gestão escolar desenvolvida para o **Instituto Arvorecer**.
Permite que administradores, professores e responsáveis acompanhem notas, frequência, atividades e alertas dos alunos.

> **Status:** Funcional e testado localmente. Em fase de aprimoramento para implantação no Instituto Arvorecer.

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

Três perfis de usuário com acesso separado:

| Perfil | O que pode fazer |
|---|---|
| **Admin** | CRUD completo de alunos, turmas, professores, disciplinas, responsáveis e usuários. Vê relatórios gerais. |
| **Professor** | Lança notas mensais, registra frequência por data/disciplina, cria atividades, escreve observações, exporta CSV. |
| **Responsável** | Consulta boletim do filho, histórico de frequência, atividades e alertas automáticos. |

O sistema **não depende de internet** — roda localmente com SQLite.

---

## 2. Stack tecnológica

| Camada | Tecnologia | Versão |
|---|---|---|
| Linguagem | Python | 3.14 |
| Framework web | Flask | 2.3.3 |
| ORM | Flask-SQLAlchemy | 3.0.5 |
| Migrações | Flask-Migrate | 4.0.4 |
| Autenticação | Flask-Login | 0.6.3 |
| Hash de senha | bcrypt | 4.0.1 |
| Variáveis de ambiente | python-dotenv | 1.0.0 |
| Banco de dados (dev) | SQLite | — |
| Banco de dados (prod) | PostgreSQL | — |
| Frontend | HTML + Jinja2 + Bootstrap | — |

---

## 3. Estrutura de arquivos

```
EducaMais/
├── app/
│   ├── __init__.py            # Factory do Flask: registra extensões e blueprints
│   ├── models.py              # Todos os modelos SQLAlchemy
│   ├── auth.py                # Blueprint de autenticação (login/logout/register)
│   ├── routes_admin.py        # Blueprint /admin — rotas do administrador
│   ├── routes_professor.py    # Blueprint /professor — rotas do professor
│   ├── routes_responsavel.py  # Blueprint /responsavel — rotas do responsável
│   ├── services.py            # Lógica de negócio isolada (médias, alertas, frequência)
│   ├── static/
│   │   └── js/main.js         # JavaScript auxiliar (interações de UI)
│   └── templates/
│       ├── base.html                    # Template base com navbar e flash messages
│       ├── login.html
│       ├── register.html
│       ├── dashboard_admin.html
│       ├── dashboard_professor.html
│       ├── dashboard_responsavel.html
│       ├── admin_alunos.html
│       ├── admin_turmas.html
│       ├── admin_professores.html
│       ├── admin_disciplinas.html
│       ├── admin_responsaveis.html
│       ├── admin_usuarios.html
│       ├── professor_lancar_nota.html   # Grid mensal de notas (Jan–Dez)
│       ├── professor_frequencia.html
│       ├── professor_atividade.html
│       ├── professor_observacoes.html
│       ├── professor_historico.html
│       └── responsavel_alerta.html
├── scripts/
│   ├── init_db.sql            # Schema PostgreSQL (referência para produção)
│   └── seed_data.py           # Popula banco com dados de exemplo
├── instance/
│   └── educamais.db           # Banco SQLite gerado automaticamente
├── venv/                      # Ambiente virtual Python
├── run.py                     # Ponto de entrada: cria app e inicia servidor
├── requirements.txt
├── .gitignore
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
Turma 1───N Atividade
Disciplina 1───N Atividade
```

### Tabelas

| Tabela | Campos principais |
|---|---|
| `usuarios` | id, nome, email, senha (bcrypt), tipo (admin/professor/responsavel) |
| `turmas` | id, nome |
| `disciplinas` | id, nome |
| `alunos` | id, nome, data_nascimento, turma_id (FK) |
| `responsaveis` | id, nome, telefone, email (opcional) |
| `aluno_responsavel` | aluno_id, responsavel_id (tabela de junção N:N) |
| `professores` | id, nome, turma_id (FK) |
| `professor_disciplina` | professor_id, disciplina_id (tabela de junção N:N) |
| `notas` | id, aluno_id, disciplina_id, mes (1–12), ano, valor; UNIQUE(aluno+disc+mes+ano) |
| `frequencias` | id, aluno_id, disciplina_id, data, status (presente/falta/justificada) |
| `atividades` | id, titulo, descricao, data, turma_id, disciplina_id, professor_id |
| `observacoes` | id, aluno_id, professor_id, texto, data |

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

| Método | Rota | Descrição |
|---|---|---|
| GET | `/admin/dashboard` | Painel: média geral, % frequência, alunos abaixo de 5.5 |
| GET/POST | `/admin/alunos` | Listar e cadastrar alunos |
| POST | `/admin/alunos/editar/<id>` | Editar aluno |
| POST | `/admin/alunos/excluir/<id>` | Excluir aluno |
| POST | `/admin/vincular` | Vincular aluno a uma turma |
| GET/POST | `/admin/turmas` | Listar e criar turmas |
| POST | `/admin/turmas/editar/<id>` | Editar turma |
| POST | `/admin/turmas/excluir/<id>` | Excluir turma (bloqueia se tiver alunos) |
| GET/POST | `/admin/professores` | Listar e cadastrar professores (com disciplinas N:N) |
| POST | `/admin/professores/editar/<id>` | Editar professor |
| POST | `/admin/professores/excluir/<id>` | Excluir professor |
| GET/POST | `/admin/disciplinas` | Listar e criar disciplinas |
| GET/POST | `/admin/responsaveis` | Listar e cadastrar responsáveis (vinculados a alunos) |
| GET/POST | `/admin/usuarios` | Criar/editar/excluir usuários (professor ou responsavel) |

### Professor (`professor_bp`, prefixo `/professor`)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/professor/dashboard` | Visão geral dos alunos |
| GET/POST | `/professor/lancar-nota` | Grid de notas mensais (Jan–Dez) por turma/disciplina/ano |
| GET | `/professor/notas/exportar` | Exporta notas em CSV (com BOM UTF-8 para Excel) |
| GET/POST | `/professor/frequencia` | Registrar frequência por turma/disciplina/data |
| GET/POST | `/professor/atividade` | Criar atividade e listar com filtros |
| POST | `/professor/atividade/excluir/<id>` | Excluir atividade |
| GET/POST | `/professor/observacoes` | Registrar observação sobre aluno |
| GET | `/professor/aluno/<id>` | Histórico completo do aluno (notas, frequência, observações) |

### Responsável (`responsavel_bp`, prefixo `/responsavel`)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/responsavel/dashboard` | Boletim, frequência e atividades do(s) filho(s) |
| GET | `/responsavel/alertas` | Alertas de desempenho e frequência |

---

## 6. Lógica de negócio (`services.py`)

| Função | O que faz |
|---|---|
| `media_aluno(aluno)` | Média geral de todas as notas do aluno |
| `media_turma(turma)` | Média de todos os alunos de uma turma |
| `frequencia_geral()` | % de presença global (todas as turmas) |
| `alunos_baixo_desempenho(limite=5.5)` | Lista alunos com média abaixo do limite |
| `queda_desempenho(aluno, disciplina_id)` | Detecta 3 notas consecutivas em queda |
| `stats_frequencia(aluno, disciplina_id)` | Retorna total, presenças, faltas, justificadas, percentual |
| `faltas_consecutivas(aluno, disciplina_id, n=3)` | True se as últimas N frequências forem todas falta |
| `alertas_frequencia(aluno, disciplina_id)` | Lista de alertas: abaixo de 75% e/ou 3+ faltas seguidas |
| `aviso_whatsapp(aluno, disciplina)` | Gera texto formatado para copiar no WhatsApp |

**Regras de alerta:**
- Frequência < 75% → alerta
- 3 ou mais faltas consecutivas → alerta
- Últimas 3 notas em queda contínua → alerta de queda de rendimento
- Média < 5.5 → listado como baixo desempenho no dashboard admin

---

## 7. Como rodar

### Pré-requisitos
- Python 3.10+
- O venv já está criado em `venv/`

```bash
# 1. Ativar o ambiente virtual
# Windows PowerShell:
venv\Scripts\Activate.ps1
# Windows CMD:
venv\Scripts\activate.bat

# 2. Instalar dependências (apenas na primeira vez)
pip install -r requirements.txt

# 3. Criar arquivo .env (apenas na primeira vez)
# Criar o arquivo .env na raiz com:
# SECRET_KEY=uma_chave_forte_qualquer
# DATABASE_URL=sqlite:///educamais.db

# 4. Inicializar o banco de dados
python run.py
# O run.py já chama db.create_all() automaticamente

# 5. Popular com dados de exemplo (opcional)
# Rodar a partir da raiz do projeto:
set PYTHONPATH=.
python scripts/seed_data.py

# 6. Acessar no navegador
# http://127.0.0.1:5000/login
```

> **Atenção:** sempre rodar `python scripts/seed_data.py` com `PYTHONPATH=.` definido, pois o script importa o módulo `app`.

---

## 8. Contas de teste

| Tipo | E-mail | Senha |
|---|---|---|
| Administrador | admin@escola.com | admin123 |
| Professor | prof@escola.com | prof123 |
| Responsável | resp@escola.com | resp123 |

---

## 9. O que já foi feito

### Infraestrutura
- [x] Projeto Flask com factory pattern (`create_app`)
- [x] Blueprints separados por perfil (auth, admin, professor, responsavel)
- [x] Autenticação com Flask-Login + bcrypt
- [x] Banco SQLite para desenvolvimento (sem necessidade de PostgreSQL)
- [x] Schema PostgreSQL disponível em `scripts/init_db.sql` para produção
- [x] `run.py` cria as tabelas automaticamente no primeiro uso
- [x] `seed_data.py` popula o banco com dados de exemplo

### Funcionalidades Admin
- [x] Dashboard com média geral, % frequência e alunos abaixo da média
- [x] CRUD completo de alunos (com vinculação de turma)
- [x] CRUD completo de turmas (bloqueia exclusão se houver alunos)
- [x] CRUD completo de professores (com associação N:N a disciplinas)
- [x] CRUD completo de disciplinas
- [x] Cadastro de responsáveis com vinculação N:N a alunos
- [x] Gestão de usuários (criar/editar/excluir acesso de professor e responsável)

### Funcionalidades Professor
- [x] Grid de lançamento de notas mensais (Jan–Dez) por turma/disciplina/ano
- [x] Edição e exclusão de nota diretamente no grid (campo limpo = exclui nota)
- [x] Exportação de notas em CSV (compatível com Excel via BOM UTF-8)
- [x] Registro de frequência por data, disciplina e turma
- [x] Totalizadores de presença/falta na tela de frequência
- [x] Criação e listagem de atividades com filtros por turma/disciplina/data
- [x] Exclusão de atividades
- [x] Registro de observações por aluno
- [x] Histórico completo do aluno (notas, frequência, observações, alertas)

### Funcionalidades Responsável
- [x] Dashboard com boletim do(s) filho(s)
- [x] Tela de alertas (frequência baixa, faltas consecutivas, queda de rendimento)

### Lógica de negócio
- [x] Cálculo de média por aluno e por turma
- [x] Detecção de queda de rendimento (3 notas em queda consecutiva)
- [x] Cálculo de % de frequência (presença + justificada / total)
- [x] Detecção de faltas consecutivas
- [x] Geração de texto para WhatsApp
- [x] Restrição de acesso por perfil (decorators `admin_required`, `professor_required`)

---

## 10. Bugs conhecidos e corrigidos

| Bug | Status | Detalhe |
|---|---|---|
| `seed_data.py` usava `disciplina_id=` no construtor de `Professor` | **Corrigido** | `Professor` não tem `disciplina_id` direto; usa relação N:N via `professor_disciplina`. Corrigido para `prof.disciplinas.append(disciplina)`. |
| Caminho errado no README original | **Corrigido** | README dizia `C:\...\EducaMais` mas o projeto está em `C:\...\Arvorecer\Sistema\EducaMais`. |

---

## 11. Próximos passos

### Alta prioridade
- [ ] Identidade visual do Instituto Arvorecer (logo, cores, tipografia no CSS)
- [ ] Área do aluno (login próprio para o aluno acompanhar o próprio desempenho)
- [ ] Exportação de boletim em PDF (sugestão: biblioteca `WeasyPrint` ou `ReportLab`)

### Média prioridade
- [ ] Gráficos de evolução de notas por disciplina (sugestão: Chart.js)
- [ ] Relatórios por turma em Excel/CSV pelo admin
- [ ] Histórico por ano letivo (hoje as notas não têm separação de ano letivo explícita além do campo `ano`)
- [ ] Multiturma para professores (hoje um professor tem apenas uma turma)

### Integrações futuras
- [ ] Envio automático de alertas via WhatsApp (Z-API ou Evolution API)
- [ ] Envio de alertas por e-mail (Flask-Mail)
- [ ] Deploy em servidor (sugestão: Railway, Render ou VPS próprio)

### Conformidade
- [ ] LGPD: termos de uso, política de privacidade, logs de acesso
- [ ] Backup automático do banco de dados

---

*Última atualização: 2026-04-28*
