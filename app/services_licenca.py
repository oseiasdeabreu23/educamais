"""Cliente do Painel de Licenças — valida licença desta instância.

A função pública é :func:`validar_licenca`, chamada no ``before_request`` do
app (modo bloqueio) ou via botão "Revalidar" na tela ``/admin/licenca``.

Princípios:
- Mesmo padrão em camadas do ``services_cora``: zero referência a templates
  ou ``flask.g``; depende só de ``current_app`` (config + logger) e do
  helper :func:`obter_machine_id`.
- Cache local em ``instance/licenca_cache.json`` (TTL configurável). Em caso
  de falha de rede, segue usando o cache até o fim do *grace period*.
- Em prod (Postgres) o ``machine_id`` mora em ``ConfigSistema``; em dev
  (SQLite) mora em ``instance/machine_id.txt`` — porque o filesystem da
  Vercel é readonly.
- ``PAINEL_LICENCA_DEBUG_RESULTADO`` curto-circuita a chamada HTTP e devolve
  um resultado sintético — usado pra exercitar branches sem mexer no painel.

Resultados conhecidos do painel:
    ativo, vencido, pendente, suspenso, bloqueado, cancelado,
    nao_encontrado, limite_excedido
Acrescentamos os "locais":
    erro_rede, offline_grace_expirado, sem_configuracao
"""
import json
import os
import socket
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests
from flask import current_app

# Resultados em que a licença é considerada válida pra liberar o app.
RESULTADOS_VALIDOS = {'ativo'}

# Resultado retornado quando o painel devolve algo não-canônico.
RESULTADO_DESCONHECIDO = 'desconhecido'

# Erros locais (não vêm do painel).
ERRO_REDE = 'erro_rede'
GRACE_EXPIRADO = 'offline_grace_expirado'
SEM_CONFIGURACAO = 'sem_configuracao'

# HTTP — fixos conforme spec (não configuráveis via env).
_HTTP_TIMEOUT = 8
_HTTP_RETRIES = 2
_HTTP_BACKOFF_S = 0.6


# Cache em memória (escopo do processo). Em Vercel/Fluid Compute cada
# instância da Function reutiliza este dict entre requests — o que evita
# que cada request faça POST no painel mesmo quando o cache em disco não
# pode ser gravado (filesystem readonly).
_MEM_CACHE = {'data': None, 'expira_em': None}


# --------------------------------------------------------------------------- #
# Caminhos auxiliares
# --------------------------------------------------------------------------- #
def _instance_path():
    return Path(current_app.instance_path)


def _cache_path():
    return _instance_path() / 'licenca_cache.json'


def _machine_id_file():
    return _instance_path() / 'machine_id.txt'


def _usar_db_para_machine_id():
    """True quando rodando contra Postgres ou Turso (prod). False em SQLite dev."""
    # USING_TURSO é setado em __init__.py quando DATABASE_URL=libsql://
    if current_app.config.get('USING_TURSO'):
        return True
    uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '') or ''
    return not uri.startswith('sqlite:')


# --------------------------------------------------------------------------- #
# Machine ID
# --------------------------------------------------------------------------- #
def obter_machine_id():
    """Devolve o identificador desta instância. Cria na 1ª chamada.

    Em Postgres (prod) persiste em ``ConfigSistema.machine_id``. Em SQLite
    (dev) persiste em ``instance/machine_id.txt``. O comportamento é
    idempotente — chamadas seguintes devolvem sempre o mesmo valor.
    """
    if _usar_db_para_machine_id():
        return _obter_machine_id_db()
    return _obter_machine_id_arquivo()


def _obter_machine_id_db():
    # Import tardio pra evitar ciclo (services_licenca é importado em
    # app.__init__ antes dos models terem sido carregados).
    from app import db
    from app.models import ConfigSistema

    cfg = ConfigSistema.query.first()
    if cfg is None:
        cfg = ConfigSistema(nome='EducaMais', logo_path=None)
        db.session.add(cfg)

    if not cfg.machine_id:
        cfg.machine_id = uuid.uuid4().hex
        db.session.commit()
    return cfg.machine_id


def _obter_machine_id_arquivo():
    p = _machine_id_file()
    try:
        if p.exists():
            mid = p.read_text(encoding='utf-8').strip()
            if mid:
                return mid
    except OSError as e:
        current_app.logger.warning('[licenca] erro lendo machine_id: %s', e)

    mid = uuid.uuid4().hex
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(mid, encoding='utf-8')
        try:
            os.chmod(p, 0o600)
        except OSError:
            # Windows ignora chmod em alguns FS — não bloqueia.
            pass
    except OSError as e:
        current_app.logger.error('[licenca] erro gravando machine_id: %s', e)
    return mid


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def _ler_cache():
    p = _cache_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as e:
        current_app.logger.warning('[licenca] cache inválido: %s', e)
        return None


def _gravar_cache(payload):
    p = _cache_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding='utf-8')
    except OSError as e:
        # Em Vercel o instance/ pode estar readonly — não fatal, só perde
        # o cache em disco (o cache em memória cobre o caso comum).
        current_app.logger.warning('[licenca] não pude gravar cache: %s', e)


def _ler_cache_mem():
    """Retorna o cache em memória se ainda dentro do TTL, senão None."""
    exp = _MEM_CACHE.get('expira_em')
    if exp and datetime.utcnow() < exp:
        return _MEM_CACHE.get('data')
    return None


def _gravar_cache_mem(estado):
    """Grava no cache em memória usando o TTL configurado no app."""
    try:
        horas = int(current_app.config.get('PAINEL_LICENCA_CACHE_HORAS', 6) or 6)
    except Exception:
        horas = 6
    _MEM_CACHE['data'] = estado
    _MEM_CACHE['expira_em'] = datetime.utcnow() + timedelta(hours=horas)


def _invalidar_cache_mem():
    _MEM_CACHE['data'] = None
    _MEM_CACHE['expira_em'] = None


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def info_licenca():
    """Leitura pura do cache (sem chamar API). Devolve ``None`` se não há cache."""
    return _ler_cache()


def invalidar_cache():
    """Apaga o cache em memória E o arquivo de cache. Use após mudar
    config (api_key/documento/modo) ou para forçar revalidação."""
    _invalidar_cache_mem()
    p = _cache_path()
    try:
        if p.exists():
            p.unlink()
    except OSError as e:
        current_app.logger.warning('[licenca] não pude apagar cache: %s', e)


# --------------------------------------------------------------------------- #
# Validação
# --------------------------------------------------------------------------- #
def get_config_licenca():
    """Devolve o singleton ``ConfigLicenca``. Cria vazio se não existir.

    Import tardio dos models pra evitar ciclo com ``app.__init__``.
    """
    from app import db
    from app.models import ConfigLicenca

    cfg = ConfigLicenca.query.first()
    if cfg is None:
        cfg = ConfigLicenca(modo='bloqueio')
        db.session.add(cfg)
        db.session.commit()
    return cfg


def modo_atual():
    """Modo efetivo (log|bloqueio). Banco tem precedência sobre env."""
    try:
        cfg = get_config_licenca()
        if cfg.modo:
            return cfg.modo
    except Exception:
        # Banco pode não estar disponível durante boot inicial.
        pass
    return (current_app.config.get('PAINEL_LICENCA_MODO') or 'bloqueio').lower()


def _config_obrigatoria():
    """Lê config; devolve (url, api_key, documento, tipo_cliente) ou None.

    URL vem sempre do env (parâmetro técnico). API key, documento e
    tipo_cliente vêm do banco (UI em /admin/licenca); se vazios, faz
    fallback nas envs ``PAINEL_LICENCA_API_KEY`` etc. pra compatibilidade
    com instalações antigas que ainda configuram via .env.
    """
    url = (current_app.config.get('PAINEL_LICENCA_URL') or '').rstrip('/')
    if not url:
        return None

    api_key = ''
    documento = ''
    tipo_cliente = ''
    try:
        cfg = get_config_licenca()
        api_key = (cfg.api_key or '').strip()
        documento = (cfg.documento or '').strip()
        tipo_cliente = (cfg.tipo_cliente or '').strip()
    except Exception as e:
        current_app.logger.warning('[licenca] falha lendo ConfigLicenca: %s', e)

    if not api_key:
        api_key = current_app.config.get('PAINEL_LICENCA_API_KEY') or ''
    if not documento:
        documento = current_app.config.get('PAINEL_LICENCA_DOCUMENTO') or ''
    if not tipo_cliente:
        tipo_cliente = (current_app.config.get('PAINEL_LICENCA_TIPO_CLIENTE')
                        or 'empresa')

    if not api_key or not documento:
        return None
    return url, api_key, documento, tipo_cliente


def _resposta_debug():
    """Se PAINEL_LICENCA_DEBUG_RESULTADO setada, devolve dict sintético.

    Não persiste no cache real e não chama HTTP. Para testar branches do
    redirect sem mexer no banco do painel.
    """
    debug = current_app.config.get('PAINEL_LICENCA_DEBUG_RESULTADO') or ''
    debug = debug.strip()
    if not debug:
        return None
    return {
        'valido': debug in RESULTADOS_VALIDOS,
        'resultado': debug,
        'fonte': 'debug',
        'validado_em': datetime.utcnow().isoformat(timespec='seconds'),
        'expira_em': None,
        'mensagem': f'Resultado forçado via PAINEL_LICENCA_DEBUG_RESULTADO={debug}',
        'resposta_painel': None,
    }


def _payload_request(machine_id, documento, tipo_cliente):
    versao = current_app.config.get('APP_VERSION') or ''
    if not versao:
        # Lê __version__ do pacote app sem criar ciclo de import.
        try:
            from app import __version__ as v
            versao = v
        except Exception:
            versao = ''
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = 'desconhecido'
    return {
        'tipo_cliente': tipo_cliente or 'empresa',
        'documento': documento or '',
        'machine_id': machine_id,
        'nome_dispositivo': hostname,
        'versao': versao,
    }


def _chamar_painel(url, api_key, payload):
    """POST /api/licenses/validate com retries. Levanta ``RuntimeError`` em falha."""
    endpoint = f'{url}/api/licenses/validate'
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    last_exc = None
    for tentativa in range(_HTTP_RETRIES + 1):
        try:
            resp = requests.post(endpoint, json=payload, headers=headers,
                                 timeout=_HTTP_TIMEOUT)
        except requests.RequestException as e:
            last_exc = e
            current_app.logger.warning(
                '[licenca] tentativa %d/%d falhou: %s',
                tentativa + 1, _HTTP_RETRIES + 1, e,
            )
        else:
            if resp.status_code in (401, 403):
                current_app.logger.error(
                    '[licenca] painel rejeitou auth (%d): %s',
                    resp.status_code, resp.text[:200],
                )
                # Sem retry em auth — devolve a resposta pra capturar resultado.
                try:
                    return resp.json()
                except ValueError:
                    return {'valido': False, 'resultado': 'sem_configuracao'}
            if 200 <= resp.status_code < 300:
                try:
                    return resp.json()
                except ValueError as e:
                    last_exc = e
                    current_app.logger.error(
                        '[licenca] resposta não-JSON: %s', resp.text[:200])
            else:
                last_exc = RuntimeError(
                    f'HTTP {resp.status_code}: {resp.text[:200]}')
                current_app.logger.warning(
                    '[licenca] tentativa %d/%d HTTP %d',
                    tentativa + 1, _HTTP_RETRIES + 1, resp.status_code,
                )
        # backoff entre tentativas
        if tentativa < _HTTP_RETRIES:
            import time
            time.sleep(_HTTP_BACKOFF_S * (tentativa + 1))
    raise RuntimeError(f'Falha consultando painel após retries: {last_exc}')


def _construir_resultado(resp_painel, fonte):
    """Normaliza resposta do painel pro formato interno.

    O painel pode retornar o status sob ``resultado`` (spec antiga) ou
    ``status`` (resposta atual). Aceitamos os dois pra ficar resiliente
    a mudanças de versão.
    """
    if not isinstance(resp_painel, dict):
        return {
            'valido': False,
            'resultado': RESULTADO_DESCONHECIDO,
            'fonte': fonte,
            'validado_em': datetime.utcnow().isoformat(timespec='seconds'),
            'expira_em': None,
            'mensagem': 'Resposta do painel inesperada.',
            'resposta_painel': resp_painel,
        }
    resultado = (resp_painel.get('resultado')
                 or resp_painel.get('status')
                 or RESULTADO_DESCONHECIDO)
    valido = bool(resp_painel.get('valido')) and resultado in RESULTADOS_VALIDOS
    horas = int(current_app.config.get('PAINEL_LICENCA_CACHE_HORAS', 6) or 6)
    agora = datetime.utcnow()
    return {
        'valido': valido,
        'resultado': resultado,
        'fonte': fonte,
        'validado_em': agora.isoformat(timespec='seconds'),
        'expira_em': (agora + timedelta(hours=horas)).isoformat(timespec='seconds'),
        'mensagem': resp_painel.get('mensagem') or '',
        'resposta_painel': resp_painel,
    }


def _cache_dentro_do_grace(cache):
    if not cache:
        return False
    dias = int(current_app.config.get('PAINEL_LICENCA_GRACE_DIAS', 3) or 3)
    validado = _parse_iso(cache.get('validado_em'))
    if validado is None:
        return False
    return datetime.utcnow() <= validado + timedelta(days=dias)


def _cache_dentro_do_ttl(cache):
    if not cache:
        return False
    expira = _parse_iso(cache.get('expira_em'))
    if expira is None:
        return False
    return datetime.utcnow() < expira


def validar_licenca(force_refresh=False):
    """Valida a licença e devolve o estado consolidado.

    Fluxo:
    1. Se ``PAINEL_LICENCA_DEBUG_RESULTADO`` setado → resposta sintética.
    2. Cache em memória (processo) válido → usa direto. Crítico em
       serverless (Vercel) onde o cache em disco geralmente não persiste.
    3. Se config faltando → ``sem_configuracao``.
    4. Cache em disco dentro do TTL → usa (e re-popula o em memória).
    5. Tenta chamar painel (com retries).
    6. Em falha de rede: usa cache mesmo expirado se ainda no *grace*;
       senão devolve ``offline_grace_expirado``.
    """
    debug = _resposta_debug()
    if debug is not None:
        return debug

    if not force_refresh:
        em_memoria = _ler_cache_mem()
        if em_memoria is not None:
            return em_memoria

    cfg = _config_obrigatoria()
    if cfg is None:
        current_app.logger.warning(
            '[licenca] env vars do painel não configuradas — '
            'rodando como sem_configuracao.')
        estado_sem_cfg = {
            'valido': False,
            'resultado': SEM_CONFIGURACAO,
            'fonte': 'config',
            'validado_em': datetime.utcnow().isoformat(timespec='seconds'),
            'expira_em': None,
            'mensagem': ('Configure a licença em /admin/licenca '
                         '(API key, documento e tipo de cliente).'),
            'resposta_painel': None,
        }
        # Cacheia "sem_configuracao" em memória pra não relogar a cada request.
        _gravar_cache_mem(estado_sem_cfg)
        return estado_sem_cfg

    cache = _ler_cache()
    if (not force_refresh) and _cache_dentro_do_ttl(cache):
        cache = dict(cache)
        cache['fonte'] = 'cache'
        _gravar_cache_mem(cache)
        current_app.logger.info(
            '[licenca] ok (resultado=%s, fonte=cache)', cache.get('resultado'))
        return cache

    url, api_key, documento, tipo_cliente = cfg
    try:
        machine_id = obter_machine_id()
    except Exception as e:
        current_app.logger.error('[licenca] falha ao obter machine_id: %s', e)
        machine_id = 'unknown'

    payload = _payload_request(machine_id, documento, tipo_cliente)
    try:
        resp = _chamar_painel(url, api_key, payload)
    except RuntimeError as e:
        # Rede caiu — tenta grace.
        if _cache_dentro_do_grace(cache):
            current_app.logger.warning(
                '[licenca] painel inacessível — usando cache em grace (%s)',
                cache.get('resultado'))
            grace = dict(cache)
            grace['fonte'] = 'cache_grace'
            grace['mensagem'] = ('Painel inacessível; usando última validação '
                                 'em grace period.')
            # Cacheia em memória pra não tentar HTTP a cada request enquanto
            # o painel estiver fora do ar.
            _gravar_cache_mem(grace)
            return grace
        current_app.logger.error(
            '[licenca] painel inacessível e grace expirado: %s', e)
        estado_grace_exp = {
            'valido': False,
            'resultado': GRACE_EXPIRADO,
            'fonte': 'grace_expirado',
            'validado_em': datetime.utcnow().isoformat(timespec='seconds'),
            'expira_em': None,
            'mensagem': ('Sem conexão com o painel há mais tempo que o '
                         'grace_dias configurado.'),
            'resposta_painel': None,
        }
        _gravar_cache_mem(estado_grace_exp)
        return estado_grace_exp

    estado = _construir_resultado(resp, fonte='api')
    _gravar_cache(estado)
    _gravar_cache_mem(estado)
    nivel = current_app.logger.info if estado['valido'] else current_app.logger.warning
    nivel('[licenca] %s (resultado=%s, fonte=api)',
          'ok' if estado['valido'] else 'inválida', estado['resultado'])
    return estado
