# Licenciamento via Painel

Implementação em [app/services_licenca.py](../app/services_licenca.py),
[app/routes_licenca.py](../app/routes_licenca.py) e hook `before_request` em
[app/__init__.py](../app/__init__.py). Painel externo:
`https://painel-licencas-rho.vercel.app` (`POST /api/licenses/validate`).

## Visão geral

O app valida sua licença a cada request em endpoints não-livres. O resultado é
cacheado em `instance/licenca_cache.json` por `PAINEL_LICENCA_CACHE_HORAS` (default 6h).
Se o painel ficar inacessível, usa o cache mesmo expirado até `PAINEL_LICENCA_GRACE_DIAS`
(default 3). Passou disso, retorna `resultado=offline_grace_expirado`.

## Onde fica a configuração

- **API key, documento (CPF/CNPJ), tipo de cliente e modo** → tabela
  `config_licenca` (singleton, modelo `ConfigLicenca`). Editáveis pela UI
  em `/admin/licenca`. Persiste sem precisar mexer no `.env`.
- **URL do painel, cache, grace, debug** → variáveis em `.env`
  (`PAINEL_LICENCA_URL`, `PAINEL_LICENCA_CACHE_HORAS`,
  `PAINEL_LICENCA_GRACE_DIAS`, `PAINEL_LICENCA_DEBUG_RESULTADO`).

`services_licenca._config_obrigatoria()` lê do banco primeiro; se vazio,
faz fallback nas envs `PAINEL_LICENCA_API_KEY`/`_DOCUMENTO`/`_TIPO_CLIENTE`
(retrocompat com instalações antigas).

## Modos

- **`bloqueio`** (default): redireciona pra `/licenca-bloqueada` quando
  inválida. Enquanto a licença não validar como `ativo`, o app fica limitado —
  o admin ainda consegue logar e abrir `/admin/licenca` (whitelisted) pra
  configurar/revalidar.
- **`log`**: só registra `WARNING` quando inválida e segue. Útil em dev
  enquanto está validando a integração — não usar em produção.

## Endpoints sempre liberados (whitelist do `before_request`)

`static`, `healthz`, `licenca.bloqueada`, `licenca.admin`, `auth.login`,
`auth.logout`, `auth.register`. Endpoint `None` (404) também passa, pra não criar
loop em rotas inexistentes.

## Machine ID — onde mora?

- **Postgres (prod)**: coluna `machine_id String(64) nullable` em `ConfigSistema`
  (singleton). Vercel é readonly FS, então **não** dá pra usar arquivo.
- **SQLite (dev)**: `instance/machine_id.txt` (criado na 1ª chamada, mode 0600).

A detecção é feita por prefixo da URI: `current_app.config['SQLALCHEMY_DATABASE_URI']`
começando com `sqlite:` usa arquivo; qualquer outra coisa usa o banco. A coluna
existe em ambos os bancos via migration `e7b91d8f2c45` — só não é populada em dev.

## Cache e grace

O dict salvo em `licenca_cache.json` tem este formato:

```json
{
  "valido": true,
  "resultado": "ativo",
  "fonte": "api|cache|cache_grace|debug|grace_expirado|config",
  "validado_em": "2026-05-11T10:00:00",
  "expira_em": "2026-05-11T16:00:00",
  "mensagem": "",
  "resposta_painel": { ... }
}
```

`info_licenca()` é **leitura pura** (não bate no painel). `validar_licenca()` é
o orquestrador. `force_refresh=True` ignora o TTL mas ainda cai no grace se a
chamada HTTP falhar.

## Testando branches sem mexer no painel

`PAINEL_LICENCA_DEBUG_RESULTADO=<valor>` curto-circuita `validar_licenca` e
devolve um dict sintético com aquele `resultado`. **Não persiste no cache real**.
Aceita qualquer string — incluindo os "locais" (`erro_rede`, `offline_grace_expirado`).
Em produção, deixar vazio.

## Resultados possíveis

Do painel: `ativo`, `vencido`, `pendente`, `suspenso`, `bloqueado`, `cancelado`,
`nao_encontrado`, `limite_excedido`.
Locais: `erro_rede` (não usado diretamente), `offline_grace_expirado`,
`sem_configuracao` (envs faltando), `desconhecido` (resposta atípica).

Só `ativo` é considerado válido (`RESULTADOS_VALIDOS` em `services_licenca.py`).

## Telas

- `GET /licenca-bloqueada` — pública, standalone (não herda `base.html`).
  POST com `action=revalidar` força nova validação; se voltar a ficar válida,
  redireciona pro login. Admin logado vê atalho pra `/admin/licenca`.
- `GET /admin/licenca` — admin_required, dentro do app-shell. Mostra status,
  parâmetros técnicos (env), machine_id e form de edição com 4 campos:
  tipo de cliente, documento (CPF/CNPJ), modo, API key (mascarada quando já
  configurada). Ações:
  - `action=salvar` — persiste no banco, invalida cache, dispara
    `validar_licenca(force_refresh=True)` imediatamente.
  - `action=revalidar` — força nova consulta sem mexer na config.
  - `action=limpar_api_key` — remove só a key (mantém documento/modo).
- Card "Licença de uso" em `/admin/configuracoes` linka pro detalhe.

## Limitações conhecidas

- HTTP timeout e retries são **hardcoded** em `services_licenca.py`
  (`_HTTP_TIMEOUT=8s`, 2 retries com backoff 0.6s). Se precisar mexer, edita
  o módulo — não exposto via env.
- O Painel **não tem** webhook que avise mudança de status — depende do TTL
  + revalidação manual. Em uso real, o admin clica "Revalidar agora" depois
  de regularizar no painel.
- `before_request` consulta cache a cada request; numa rede muito lenta isso
  não é problema, mas evite chamar `force_refresh=True` em hot paths.
