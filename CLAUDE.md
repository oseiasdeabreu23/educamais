# CLAUDE.md — Guia para IA: EducaMais

Este arquivo dá contexto completo para qualquer IA que trabalhe neste projeto.
Leia antes de qualquer alteração.

---

## O que é este projeto

**EducaMais** é um sistema web de gestão escolar construído em Python/Flask para o
**Instituto Arvorecer**. Permite que admins, professores, responsáveis e alunos
acompanhem notas, frequência, atividades, alertas e cursos com videoaulas.
O nome e a logo da plataforma são configuráveis pelo admin sem mexer no código.

**Estado atual (2026-04-28):** funcional e testado localmente. Em fase de
aprimoramento para implantação no instituto.

---

## Como rodar para testar

```bash
# Na raiz do projeto (C:\...\Arvorecer\Sistema\EducaMais)
venv\Scripts\python.exe run.py
# Acesse: http://127.0.0.1:5000/login
```

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
app/static/uploads/       → logos enviadas pelo admin (criado automaticamente)
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
- `Aluno` — tem `user_id` (FK → `usuarios.id`, nullable, unique) para vincular conta de acesso
- `Responsavel`, `AlunoResponsavel` (N:N)
- `Professor` — disciplinas via N:N `professor_disciplina` (**sem campo `disciplina_id` direto**)
- `Nota` — unique por `(aluno_id, disciplina_id, mes, ano)`
- `Frequencia`, `Atividade`, `Observacao`

### Novos (adicionados em 2026-04-28)
- `Curso` — título, descrição, capa_url, ativo
- `Modulo` — pertence a Curso, tem ordem
- `Videoaula` — pertence a Modulo, tem video_url (YouTube/Vimeo), duracao_min, ordem
- `MatriculaCurso` — N:N entre Aluno e Curso, unique por `(aluno_id, curso_id)`
- `ProgressoVideoaula` — aluno + videoaula + assistido (bool), unique por `(aluno_id, videoaula_id)`
- `ConfigSistema` — singleton (sempre ID=1): `nome` (str) + `logo_path` (str nullable)

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

---

## O que já foi implementado

**Admin:** CRUD de alunos, turmas, professores (N:N disciplinas), disciplinas,
responsáveis (N:N alunos), usuários (inclui tipo `aluno`). Dashboard com médias e alertas.
Gestão de cursos: criar curso → módulos → videoaulas, matricular/desmatricular alunos.
Configurações do sistema: alterar nome da plataforma e upload de logo.

**Professor:** Grid mensal de notas (Jan–Dez) com edição inline, exportação CSV,
frequência por data/turma/disciplina, atividades com filtros, observações por aluno,
histórico completo do aluno.

**Responsável:** boletim do filho, histórico de frequência, alertas automáticos.

**Aluno:** dashboard com cards de resumo e gráfico Chart.js (evolução mensal por disciplina),
boletim Jan–Dez com situação por disciplina, frequência com barra de progresso e histórico,
lista de cursos matriculados com progresso, detalhe do curso em accordion, player de videoaula
(embed YouTube/Vimeo) com marcação de aula concluída e navegação anterior/próximo.

**Serviços (`services.py`):** `media_aluno`, `media_turma`, `frequencia_geral`,
`alunos_baixo_desempenho`, `queda_desempenho`, `stats_frequencia`,
`faltas_consecutivas`, `alertas_frequencia`, `aviso_whatsapp`, `embed_url`.

**Context processor:** `inject_config_sistema()` em `__init__.py` injeta `config_sistema`
em **todos** os templates automaticamente (incluindo `login.html` que não herda de `base.html`).

---

## O que ainda NÃO foi feito (próximos passos)

1. Exportação de boletim em PDF
2. Envio automático de alertas via WhatsApp/e-mail
3. Deploy em servidor (hoje só roda local)
4. LGPD: termos de uso, logs de acesso
5. Backup automático do banco
6. ⚠️ Página `/admin/cursos/<id>` ainda apresenta falha — pendente de investigação

---

## Bugs já corrigidos (não reverter)

- `seed_data.py`: usava `Professor(disciplina_id=...)` — modelo não tem esse campo.
  Corrigido para `prof.disciplinas.append(disciplina)`.
- `admin_configuracoes.html`: botão "Remover logo" estava dentro de um `<form>` aninhado
  no form principal — HTML inválido, o browser ignorava o form interno. Corrigido usando
  `<form id="formRemoverLogo">` externo ao form principal e atributo `form="formRemoverLogo"`
  no botão. **Nunca aninhar `<form>` dentro de outro `<form>`.**

---

## Convenções do projeto

- Blueprints com decorator próprio de autorização: `admin_required`, `professor_required`,
  `aluno_required` (em `routes_aluno.py`) — em vez de roles no Flask-Login.
- Flash messages usam classes Bootstrap: `success`, `danger`, `warning`, `info`.
- Templates herdam de `base.html` via `{% extends 'base.html' %}`.
  Exceção: `login.html` é independente — mas recebe `config_sistema` via context processor.
- Senhas sempre com `bcrypt.hashpw` — nunca salvar em texto puro.
- Formulários de edição/exclusão usam POST com campo hidden `action`.
- O campo `PYTHONPATH=.` é necessário para rodar scripts fora da raiz do projeto.
- Migrações: sempre usar `flask db migrate` + `flask db upgrade`. Nunca confiar só em
  `db.create_all()` para alterar tabelas existentes.
- `render_as_batch=True` está ativo no Migrate — necessário para SQLite suportar
  `ALTER TABLE` via recriação de tabela.
