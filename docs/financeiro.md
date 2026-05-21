# Financeiro e integração Cora

Implementação em [app/services_cora.py](../app/services_cora.py),
[app/services_financeiro.py](../app/services_financeiro.py) e rotas
`/admin/financeiro*` em [app/routes_admin.py](../app/routes_admin.py).
Templates: `admin_financeiro*.html`.

## Arquitetura em camadas

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
   - `gerar_mensalidades_lote(mes, ano, valor_default=None)` — itera **matrículas ativas**
     (não alunos), pula quem já tem mensalidade do mês na mesma matrícula. Valor por matrícula
     na ordem: `matricula.mensalidade_padrao` → `aluno.mensalidade_padrao` → `valor_default`.
     Responsável vem do plano ativo da matrícula se houver; senão `aluno.responsaveis[0]`.
   - **Planos por matrícula** (multi-plano em 2026-05-21):
     - `plano_ativo_da_matricula(matricula)` — lookup por matrícula
     - `planos_ativos_do_aluno(aluno)` — lista todos os planos ativos do aluno
     - `plano_ativo_do_aluno(aluno)` — compat: primeiro da lista
     - `criar_plano_pagamento(matricula, n_parcelas, valor_parcela, ..., responsavel_id=None)`
       — recebe matrícula (não aluno), bloqueia se já existe plano ativo nessa matrícula.
       `responsavel_id` pode ser qualquer responsável vinculado ao aluno (não força o primeiro).
     - `cancelar_plano_matricula(matricula)` — atômica, cancela plano + mensalidades futuras + boletos
     - `cancelar_plano_aluno(aluno)` — wrapper agregado: itera matrículas + fallback pra planos
       legacy sem `matricula_turma_id`. Usado em exclusão de aluno e status legacy `evadido`.
   - `emitir_boleto(mensalidade)` — chama `CoraClient.criar_boleto`, persiste `Boleto`.
   - `registrar_pagamento_boleto(boleto, pago_em=None)` — idempotente: se já está pago,
     não duplica `Movimentacao`. Cria entrada de fluxo com `boleto_id` ligado.
   - `sincronizar_status_boletos()` — fallback ao webhook: itera boletos abertos/vencidos
     e consulta o Cora. Devolve `{pagos, vencidos, erros}`.
   - `kpis_mes`, `fluxo_caixa`, `inadimplentes`, `registrar_movimentacao_manual`.

3. **`routes_admin.py`** — endpoints `/admin/financeiro*`. Todos `@admin_required`,
   exceto `/admin/financeiro/cora/webhook` que é **público** (Cora não autentica antes
   de chamar — em produção, validar HMAC).

## Multi-plano por matrícula (2026-05-21)

Aluno pode ter múltiplas matrículas ativas (uma por turma — ver
[matriculas.md](matriculas.md)). O modelo financeiro acompanha isso: **um plano de
pagamento por matrícula**, não por aluno. Aluno em Fund. II + Reforço pode ter 2
planos paralelos, cada um com responsável-pagador, valor e parcelas próprios.

### Modelo

- `PlanoPagamento.matricula_turma_id` (FK indexada) — fonte da verdade do vínculo.
- `PlanoPagamento.responsavel_id` (FK opcional) — pagador deste plano específico.
  Pode ser diferente entre planos do mesmo aluno (pai paga uma turma, mãe outra).
- `PlanoPagamento.aluno_id` — denormalizado, mantido por compat. **Não deve ser
  fonte da verdade em queries novas**: prefira `plano.matricula.aluno`.
- `Mensalidade.matricula_turma_id` (FK) + unique `(matricula_turma_id, mes, ano)`.
  NULLs são considerados distintos pelo SQLite — mensalidades legacy não migradas
  convivem sem conflito.
- `MatriculaTurma.mensalidade_padrao` — valor sugerido específico da turma.

### Tela `/admin/financeiro/planos/<aluno_id>`

Lista 1 card por matrícula ativa. Cada card é independente:
- Se a matrícula tem plano ativo: mostra parcelas + botão cancelar
- Se não tem: form de criação com select de responsável-pagador (lista responsáveis
  do aluno) e valor pré-preenchido por `matricula.mensalidade_padrao` (ou
  `aluno.mensalidade_padrao` como fallback)

O histórico (lado direito) mostra **todos** os planos antigos do aluno, com a turma
de cada um.

### Rotas

- `GET /admin/financeiro/planos/<aluno_id>` — view por aluno (lista das matrículas)
- `POST /admin/financeiro/planos/matricula/<matricula_id>/criar` — `responsavel_id` no form
- `POST /admin/financeiro/planos/matricula/<matricula_id>/cancelar`

### Auto-cancelamento de plano

- **Mudar status de matrícula específica pra `evadido`** (em `/admin/alunos/<id>/vinculos`):
  cancela só o plano daquela matrícula. Outras matrículas ativas do aluno continuam.
- **Aluno legacy com `status='evadido'`** (form antigo) ou exclusão do aluno: chama
  `cancelar_plano_aluno` que itera todas as matrículas. Inclui fallback pra planos
  legacy sem `matricula_turma_id` (planos pré-backfill).

### Backfill e migração

`scripts/backfill_planos_matricula.py` — script interativo que liga planos e
mensalidades existentes às matrículas. Idempotente, transação única, prompt de
confirmação no fim. Roda em casos ambíguos (aluno com >1 matrícula ativa) pedindo
escolha manual. Migrations relacionadas: `cb044fa74a08` (campos aditivos) e
`d7a8e2c3f1b9` (drop da unique constraint legacy `aluno+mes+ano`).

## Modo mock vs real

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

## Webhook do Cora

Endpoint `POST /admin/financeiro/cora/webhook` aceita JSON `{cora_id, evento}`
onde `evento ∈ {pago, cancelado}`. Sem autenticação Flask-Login (Cora chama de fora).

**Em produção**: o Cora envia um header com assinatura HMAC — validar antes de chamar
`registrar_pagamento_boleto()`. Sem essa validação, qualquer um na internet pode marcar
boleto como pago. **Não esquecer disso ao implementar `CoraRealClient`.**

Pra desenvolvimento local sem URL pública, usar o botão "Simular pagamento" no admin
ou chamar diretamente o endpoint via curl.

## Comprovantes

Lançamentos manuais de despesa (`/admin/financeiro/movimentacao/nova`) aceitam upload
opcional de comprovante. Salvos em `app/static/uploads/comprovantes/comp_<uuid12>.<ext>`,
acessíveis via `url_for('static', filename='uploads/' + comprovante_path)`. O backup
automático cobre essa pasta (parte de `app/static/uploads/`).

Validação no `routes_admin.py`: extensões em `COMPROVANTE_EXTENSOES`, tamanho máximo
em `COMPROVANTE_MAX_BYTES` (5 MB). Movimentação vinda de boleto **não** aceita
exclusão pelo botão de lixeira (cancelar o boleto é o caminho).

## Limitações conhecidas

- Geração mensal automática não está implementada — admin precisa clicar "Gerar lote"
  todo mês. Implementar com APScheduler quando o sistema estiver em produção contínua.
- `CoraRealClient` não implementado. Tudo testado em mock.
- Mock não gera PDF real — endpoints `/admin/financeiro/cora/mock-pdf/<cora_id>` e
  `/admin/financeiro/cora/mock-boleto/<cora_id>` retornam texto placeholder. Em produção
  o Cora retorna a URL pública do PDF/boleto.
- Lembrete por WhatsApp na tela de inadimplentes é só um link `wa.me/` — não envia
  automaticamente. Disparo automático fica pra fase 2 (provavelmente via `services.aviso_whatsapp`).
