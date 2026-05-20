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
