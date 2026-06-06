"""
Migração Supabase → Turso
Executa o schema e insere os dados exportados via JSON.
Uso: python scripts/turso_migrate.py <comando>
  schema   → cria todas as tabelas no Turso
  insert   → insere dados de um arquivo dados.json
"""
import json, sys, requests

TURSO_URL = "https://educamais-oseiasdeabreu23.aws-us-west-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3ODA3MDc1MjUsImlkIjoiMDE5ZTlhNzAtNWEwMS03MThjLWFlNTktOTI4ZWQ2OWQyMjY2IiwicmlkIjoiODliYzg1ZjYtZDcyMC00N2YwLWIwMGYtZDNjNDA4MDVjZGU1In0.wBes8_EoaAzWdpnGVxYWTfzYb9t9pkMJCoIF2UYmxdLC2kvJJPJkuWDyTNtE4bnmr84PQ7aOozjvUNEQ1wE7Bg"

HEADERS = {
    "Authorization": f"Bearer {TURSO_TOKEN}",
    "Content-Type": "application/json",
}

# Tabelas na ordem correta (pai antes de filho)
TABLE_ORDER = [
    "alembic_version",
    "usuarios",
    "turmas",
    "disciplinas",
    "responsaveis",
    "cursos",
    "categorias_despesa",
    "config_sistema",
    "config_licenca",
    "alunos",
    "professores",
    "professor_disciplina",
    "professor_turma",
    "aluno_responsavel",
    "matriculas_turma",
    "matriculas_curso",
    "modulos",
    "videoaulas",
    "progresso_videoaulas",
    "planos_pagamento",
    "mensalidades",
    "boletos",
    "movimentacoes",
    "notas",
    "frequencias",
    "atividades",
    "observacoes",
    "cora_mock_boletos",
    "cora_mock_movimentacoes",
    "integracao_mercadopago",
    "encontros_turma",
    "avisos",
    "aviso_leituras",
    "usuario_permissao",
]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
CREATE TABLE IF NOT EXISTS usuarios (id INTEGER NOT NULL, nome VARCHAR(100) NOT NULL, email VARCHAR(120) NOT NULL, senha VARCHAR(255) NOT NULL, tipo VARCHAR(20) NOT NULL, permissoes_customizadas BOOLEAN DEFAULT '0' NOT NULL, PRIMARY KEY (id), UNIQUE (email));
CREATE TABLE IF NOT EXISTS turmas (id INTEGER NOT NULL, nome VARCHAR(100) NOT NULL, PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS disciplinas (id INTEGER NOT NULL, nome VARCHAR(100) NOT NULL, PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS responsaveis (id INTEGER NOT NULL, nome VARCHAR(100) NOT NULL, telefone VARCHAR(50) NOT NULL, email VARCHAR(120), PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS cursos (id INTEGER NOT NULL, titulo VARCHAR(150) NOT NULL, descricao TEXT, capa_url VARCHAR(500), ativo BOOLEAN, duracao_meses INTEGER, PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS categorias_despesa (id INTEGER NOT NULL, nome VARCHAR(80) NOT NULL, cor VARCHAR(20), PRIMARY KEY (id), UNIQUE (nome));
CREATE TABLE IF NOT EXISTS config_sistema (id INTEGER NOT NULL, nome VARCHAR(100) NOT NULL, logo_path VARCHAR(500), machine_id VARCHAR(64), PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS config_licenca (id INTEGER NOT NULL, api_key TEXT, documento VARCHAR(20), tipo_cliente VARCHAR(30), modo VARCHAR(20) NOT NULL, atualizado_em DATETIME, atualizado_por_id INTEGER, PRIMARY KEY (id), FOREIGN KEY(atualizado_por_id) REFERENCES usuarios (id));
CREATE TABLE IF NOT EXISTS alunos (id INTEGER NOT NULL, nome VARCHAR(100) NOT NULL, data_nascimento DATE NOT NULL, turma_id INTEGER, user_id INTEGER, mensalidade_padrao NUMERIC(10, 2), cpf VARCHAR(11), sexo VARCHAR(30), cor_raca VARCHAR(30), telefone VARCHAR(20), cep VARCHAR(8), logradouro VARCHAR(150), numero VARCHAR(10), complemento VARCHAR(100), bairro VARCHAR(100), cidade VARCHAR(100), uf VARCHAR(2), pcd BOOLEAN NOT NULL, pcd_descricao TEXT, status VARCHAR(20) NOT NULL, autoriza_imagem BOOLEAN NOT NULL, data_consentimento_imagem DATE, PRIMARY KEY (id), FOREIGN KEY(turma_id) REFERENCES turmas (id), UNIQUE (user_id), FOREIGN KEY(user_id) REFERENCES usuarios (id), UNIQUE (cpf));
CREATE TABLE IF NOT EXISTS professores (id INTEGER NOT NULL, nome VARCHAR(100) NOT NULL, turma_id INTEGER, user_id INTEGER, PRIMARY KEY (id), FOREIGN KEY(turma_id) REFERENCES turmas (id), UNIQUE (user_id), FOREIGN KEY(user_id) REFERENCES usuarios (id));
CREATE TABLE IF NOT EXISTS professor_disciplina (professor_id INTEGER, disciplina_id INTEGER, FOREIGN KEY(professor_id) REFERENCES professores (id), FOREIGN KEY(disciplina_id) REFERENCES disciplinas (id));
CREATE TABLE IF NOT EXISTS professor_turma (professor_id INTEGER, turma_id INTEGER, FOREIGN KEY(professor_id) REFERENCES professores (id), FOREIGN KEY(turma_id) REFERENCES turmas (id));
CREATE TABLE IF NOT EXISTS aluno_responsavel (id INTEGER NOT NULL, aluno_id INTEGER, responsavel_id INTEGER, PRIMARY KEY (id), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(responsavel_id) REFERENCES responsaveis (id));
CREATE TABLE IF NOT EXISTS matriculas_turma (id INTEGER NOT NULL, aluno_id INTEGER NOT NULL, turma_id INTEGER NOT NULL, status VARCHAR(20) NOT NULL, data_matricula DATE NOT NULL, data_saida DATE, observacao TEXT, mensalidade_padrao NUMERIC(10, 2), PRIMARY KEY (id), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(turma_id) REFERENCES turmas (id));
CREATE TABLE IF NOT EXISTS matriculas_curso (id INTEGER NOT NULL, aluno_id INTEGER NOT NULL, curso_id INTEGER NOT NULL, data_matricula DATE, PRIMARY KEY (id), CONSTRAINT uq_matricula_aluno_curso UNIQUE (aluno_id, curso_id), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(curso_id) REFERENCES cursos (id));
CREATE TABLE IF NOT EXISTS modulos (id INTEGER NOT NULL, curso_id INTEGER NOT NULL, titulo VARCHAR(150) NOT NULL, ordem INTEGER, PRIMARY KEY (id), FOREIGN KEY(curso_id) REFERENCES cursos (id));
CREATE TABLE IF NOT EXISTS videoaulas (id INTEGER NOT NULL, modulo_id INTEGER NOT NULL, titulo VARCHAR(150) NOT NULL, video_url VARCHAR(500) NOT NULL, duracao_min INTEGER, ordem INTEGER, PRIMARY KEY (id), FOREIGN KEY(modulo_id) REFERENCES modulos (id));
CREATE TABLE IF NOT EXISTS progresso_videoaulas (id INTEGER NOT NULL, aluno_id INTEGER NOT NULL, videoaula_id INTEGER NOT NULL, assistido BOOLEAN, data DATE, PRIMARY KEY (id), CONSTRAINT uq_progresso_aluno_video UNIQUE (aluno_id, videoaula_id), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(videoaula_id) REFERENCES videoaulas (id));
CREATE TABLE IF NOT EXISTS planos_pagamento (id INTEGER NOT NULL, aluno_id INTEGER NOT NULL, matricula_turma_id INTEGER, responsavel_id INTEGER, n_parcelas INTEGER NOT NULL, valor_parcela NUMERIC(10, 2) NOT NULL, dia_vencimento INTEGER NOT NULL, data_primeira DATE NOT NULL, status VARCHAR(20) NOT NULL, observacao TEXT, criado_em DATETIME, cancelado_em DATETIME, PRIMARY KEY (id), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(matricula_turma_id) REFERENCES matriculas_turma (id), FOREIGN KEY(responsavel_id) REFERENCES responsaveis (id));
CREATE TABLE IF NOT EXISTS mensalidades (id INTEGER NOT NULL, aluno_id INTEGER NOT NULL, responsavel_id INTEGER, plano_id INTEGER, matricula_turma_id INTEGER, mes INTEGER NOT NULL, ano INTEGER NOT NULL, valor NUMERIC(10, 2) NOT NULL, vencimento DATE NOT NULL, observacao TEXT, cancelada_em DATETIME, criada_em DATETIME, PRIMARY KEY (id), CONSTRAINT uq_mensalidade_matricula_mes_ano UNIQUE (matricula_turma_id, mes, ano), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(responsavel_id) REFERENCES responsaveis (id), FOREIGN KEY(plano_id) REFERENCES planos_pagamento (id), FOREIGN KEY(matricula_turma_id) REFERENCES matriculas_turma (id));
CREATE TABLE IF NOT EXISTS boletos (id INTEGER NOT NULL, mensalidade_id INTEGER, cora_boleto_id VARCHAR(100), status VARCHAR(20) NOT NULL, valor NUMERIC(10, 2) NOT NULL, vencimento DATE NOT NULL, emitido_em DATETIME, pago_em DATETIME, link_pdf VARCHAR(500), link_boleto VARCHAR(500), tipo_cobranca VARCHAR(20) NOT NULL, linha_digitavel TEXT, pix_copia_cola TEXT, pdf_path VARCHAR(500), mp_payment_id VARCHAR(100), PRIMARY KEY (id), FOREIGN KEY(mensalidade_id) REFERENCES mensalidades (id));
CREATE TABLE IF NOT EXISTS movimentacoes (id INTEGER NOT NULL, tipo VARCHAR(10) NOT NULL, categoria_id INTEGER, descricao VARCHAR(200) NOT NULL, valor NUMERIC(10, 2) NOT NULL, data DATE NOT NULL, boleto_id INTEGER, comprovante_path VARCHAR(500), criada_em DATETIME, criado_por_id INTEGER, PRIMARY KEY (id), FOREIGN KEY(categoria_id) REFERENCES categorias_despesa (id), FOREIGN KEY(boleto_id) REFERENCES boletos (id), FOREIGN KEY(criado_por_id) REFERENCES usuarios (id));
CREATE TABLE IF NOT EXISTS notas (id INTEGER NOT NULL, aluno_id INTEGER NOT NULL, disciplina_id INTEGER NOT NULL, mes INTEGER NOT NULL, ano INTEGER NOT NULL, valor FLOAT NOT NULL, data DATE, PRIMARY KEY (id), CONSTRAINT uq_nota_aluno_disc_mes_ano UNIQUE (aluno_id, disciplina_id, mes, ano), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(disciplina_id) REFERENCES disciplinas (id));
CREATE TABLE IF NOT EXISTS frequencias (id INTEGER NOT NULL, aluno_id INTEGER NOT NULL, disciplina_id INTEGER, data DATE, status VARCHAR(20) NOT NULL, PRIMARY KEY (id), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(disciplina_id) REFERENCES disciplinas (id));
CREATE TABLE IF NOT EXISTS atividades (id INTEGER NOT NULL, titulo VARCHAR(120) NOT NULL, descricao TEXT, data DATE, turma_id INTEGER, disciplina_id INTEGER, professor_id INTEGER, PRIMARY KEY (id), FOREIGN KEY(turma_id) REFERENCES turmas (id), FOREIGN KEY(disciplina_id) REFERENCES disciplinas (id), FOREIGN KEY(professor_id) REFERENCES professores (id));
CREATE TABLE IF NOT EXISTS observacoes (id INTEGER NOT NULL, aluno_id INTEGER NOT NULL, professor_id INTEGER NOT NULL, texto TEXT NOT NULL, data DATE, PRIMARY KEY (id), FOREIGN KEY(aluno_id) REFERENCES alunos (id), FOREIGN KEY(professor_id) REFERENCES professores (id));
CREATE TABLE IF NOT EXISTS cora_mock_boletos (id INTEGER NOT NULL, cora_id VARCHAR(64) NOT NULL, status VARCHAR(20) NOT NULL, valor NUMERIC(10, 2) NOT NULL, vencimento DATE NOT NULL, pagador JSON, descricao TEXT, emitido_em DATETIME, pago_em DATETIME, PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS cora_mock_movimentacoes (id INTEGER NOT NULL, mov_id VARCHAR(64) NOT NULL, tipo VARCHAR(10) NOT NULL, valor NUMERIC(10, 2) NOT NULL, descricao VARCHAR(300), data DATE NOT NULL, cora_boleto_id VARCHAR(64), PRIMARY KEY (id), UNIQUE (mov_id));
CREATE TABLE IF NOT EXISTS integracao_mercadopago (id INTEGER NOT NULL, ativo BOOLEAN NOT NULL, ambiente VARCHAR(20) NOT NULL, access_token TEXT, webhook_secret VARCHAR(200), notification_url VARCHAR(500), atualizado_em DATETIME, atualizado_por_id INTEGER, PRIMARY KEY (id), FOREIGN KEY(atualizado_por_id) REFERENCES usuarios (id));
CREATE TABLE IF NOT EXISTS encontros_turma (id INTEGER NOT NULL, turma_id INTEGER NOT NULL, data DATE NOT NULL, ordem INTEGER NOT NULL, criado_em DATETIME, PRIMARY KEY (id), CONSTRAINT uq_encontro_turma_data UNIQUE (turma_id, data), FOREIGN KEY(turma_id) REFERENCES turmas (id));
CREATE TABLE IF NOT EXISTS avisos (id INTEGER NOT NULL, titulo VARCHAR(200) NOT NULL, mensagem TEXT NOT NULL, nivel VARCHAR(20) NOT NULL, escopo VARCHAR(20) NOT NULL, papeis_alvo VARCHAR(200), usuarios_alvo VARCHAR(500), criado_por_id INTEGER, criado_em DATETIME NOT NULL, expira_em DATETIME, ativo BOOLEAN NOT NULL, PRIMARY KEY (id), FOREIGN KEY(criado_por_id) REFERENCES usuarios (id));
CREATE TABLE IF NOT EXISTS aviso_leituras (id INTEGER NOT NULL, aviso_id INTEGER NOT NULL, usuario_id INTEGER NOT NULL, status VARCHAR(20) NOT NULL, atualizado_em DATETIME NOT NULL, lembrete_para DATETIME, PRIMARY KEY (id), CONSTRAINT uq_aviso_leitura UNIQUE (aviso_id, usuario_id), FOREIGN KEY(aviso_id) REFERENCES avisos (id), FOREIGN KEY(usuario_id) REFERENCES usuarios (id));
CREATE TABLE IF NOT EXISTS usuario_permissao (user_id INTEGER NOT NULL, chave VARCHAR(80) NOT NULL, PRIMARY KEY (user_id, chave), FOREIGN KEY(user_id) REFERENCES usuarios (id) ON DELETE CASCADE);
"""


def turso_execute_batch(statements):
    """Envia um lote de statements SQL para o Turso via HTTP pipeline."""
    requests_list = [{"type": "execute", "stmt": {"sql": s.strip()}} for s in statements if s.strip()]
    requests_list.append({"type": "close"})
    resp = requests.post(
        f"{TURSO_URL}/v2/pipeline",
        headers=HEADERS,
        json={"requests": requests_list},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    errors = [r for r in result.get("results", []) if r.get("type") == "error"]
    if errors:
        raise Exception(f"Turso error: {errors}")
    return result


def cmd_schema():
    print("Criando schema no Turso...")
    stmts = [s for s in SCHEMA_SQL.strip().split("\n") if s.strip()]
    # Envia em lotes de 10
    batch_size = 10
    for i in range(0, len(stmts), batch_size):
        batch = stmts[i:i+batch_size]
        turso_execute_batch(batch)
        print(f"  {min(i+batch_size, len(stmts))}/{len(stmts)} tabelas criadas")
    print("Schema criado com sucesso!")


def sql_val(v):
    """Converte um valor Python para literal SQL seguro."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict) or isinstance(v, list):
        return "'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'"
    return "'" + str(v).replace("'", "''") + "'"


def cmd_insert(dados_path):
    print(f"Carregando dados de {dados_path}...")
    with open(dados_path, "r", encoding="utf-8") as f:
        dados = json.load(f)

    total_inserido = 0
    for table in TABLE_ORDER:
        rows = dados.get(table, [])
        if not rows:
            print(f"  {table}: 0 linhas (pulando)")
            continue

        cols = list(rows[0].keys())
        col_list = ", ".join(cols)
        stmts = []
        for row in rows:
            vals = ", ".join(sql_val(row[c]) for c in cols)
            stmts.append(f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({vals})")

        # Envia em lotes de 50
        batch_size = 50
        for i in range(0, len(stmts), batch_size):
            turso_execute_batch(stmts[i:i+batch_size])

        total_inserido += len(rows)
        print(f"  {table}: {len(rows)} linhas inseridas")

    print(f"\nTotal inserido: {total_inserido} registros")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "schema"
    if cmd == "schema":
        cmd_schema()
    elif cmd == "insert" and len(sys.argv) > 2:
        cmd_insert(sys.argv[2])
    else:
        print("Uso: python scripts/turso_migrate.py schema")
        print("     python scripts/turso_migrate.py insert dados.json")
