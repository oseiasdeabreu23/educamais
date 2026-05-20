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

## Limitações conhecidas
- Só SQLite por enquanto. Se migrar pro Postgres em prod, trocar `_db_path()` por
  `pg_dump`/`pg_restore` em subprocess.
- Restauração não migra schema — se o backup é de uma versão mais antiga do app
  (com migrations diferentes), pode quebrar. Sempre rodar `flask db upgrade` depois
  de restaurar um backup antigo.
