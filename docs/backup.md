# Backup e restauração

Implementação em [app/services_backup.py](../app/services_backup.py) e rotas
`/admin/backup*` em [app/routes_admin.py](../app/routes_admin.py).

## Formato do backup
Cada backup é um `.zip` em `instance/backups/` contendo:
- `educamais.db` — snapshot do SQLite via API `sqlite3.backup()` (atômica, funciona com
  conexões abertas — não usar `shutil.copy` direto no arquivo do banco em runtime).
- `uploads/<arquivos>` — todo o conteúdo de `app/static/uploads/`.
- `manifest.json` — `{version, created_at, app, db_size_bytes, uploads}`.

Nome do arquivo: `backup_YYYY-MM-DD_HH-MM-SS.zip`. Pré-restaurações usam prefixo
`pre-restore_` pra distinção fácil na listagem.

## Resolução do caminho do SQLite
`SQLALCHEMY_DATABASE_URI = sqlite:///educamais.db` é **relativo ao `app.instance_path`**
(não ao `root_path`). O helper `_db_path()` cuida disso — se mexer no service, lembrar:
`Path(app.instance_path) / raw`.

## Restauração — rede de segurança
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

## Segurança
- `_extensao_valida` **não** se aplica aqui — quem valida é `caminho_backup()` /
  `excluir_backup()`: rejeitam `..`, `/`, `\` e qualquer nome que não termine em `.zip`.
- Restauração exige campo `confirmacao = "RESTAURAR"` no form (digitado a mão).
- Endpoints todos com `@admin_required`.

## Export portátil (produção) — 2026-05-25
Em produção (Vercel + Postgres/Supabase) o backup local **não funciona**: filesystem
read-only (não dá pra criar `instance/backups/`) e o banco não é SQLite. Para esse
cenário existe um caminho separado, **sem gravar em disco**:

- `backup_local_disponivel(app)` → `True` só com SQLite **e** filesystem gravável.
  É o que decide o ramo na rota `backup_criar` e o que a página renderiza.
- `exportar_dados(app)` → dump portátil de **todas as tabelas** via
  `db.metadata.sorted_tables` (ordem de FK). Funciona em Postgres e SQLite, **sem
  `pg_dump`** (o runtime do Vercel não tem o binário). Serialização: `Decimal`→string,
  `date/datetime`→ISO, `bytes`→base64 (`_json_safe`).
- `gerar_export_zip_bytes(app)` → monta um `.zip` em memória (`dados.json` +
  `manifest.json`) e devolve `(BytesIO, nome)`. A rota faz `send_file(as_attachment=True)`
  — download direto no navegador. Nome: `backup_dados_YYYY-MM-DD_HH-MM-SS.zip`.
- A rota `backup_criar` escolhe o ramo: SQLite gravável → backup local em disco (com
  round-trip de restauração); senão → export portátil por download.
- A página de backup recebe a flag `backup_local`. Em produção esconde a lista
  "Backups disponíveis" e o card de restauração (substituído por nota informativa).

**Restauração/import do `dados.json` ainda NÃO foi implementada** (fase futura) —
importar JSON no Postgres exige respeitar ordem de FK, resetar sequences e truncar
com cuidado. Por ora, o `.zip` de produção é **cópia de segurança/export off-site**;
recuperação de emergência usa os backups automáticos do Supabase (PITR). Uploads
(logos/comprovantes) **não** entram no zip — ficam no Supabase Storage.

## Limitações conhecidas
- Backup local (zip com `educamais.db`) é **só SQLite/dev**. Em prod usa o export
  portátil acima.
- Restauração (formato antigo) não migra schema — se o backup é de uma versão mais
  antiga do app (com migrations diferentes), pode quebrar. Sempre rodar
  `flask db upgrade` depois de restaurar um backup antigo.
- O export portátil roda dentro do limite de tempo/tamanho da função serverless do
  Vercel. Para o volume de um instituto é tranquilo; se crescer muito, paginar.
