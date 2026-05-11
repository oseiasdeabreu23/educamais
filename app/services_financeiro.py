"""Regras de negócio do módulo financeiro.

Este módulo é puro Python + SQLAlchemy. Não fala HTTP — quem fala com o Cora é
:mod:`app.services_cora`. A separação deixa estes serviços testáveis isoladamente
e permite trocar mock por real sem mexer aqui.
"""
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, func

from app import db
from app.models import (
    Aluno, Boleto, CategoriaDespesa, Mensalidade, Movimentacao, Responsavel,
    PlanoPagamento,
)
from app.services_cora import CoraError, get_cora_client


VENCIMENTO_DIA_PADRAO = 10  # dia do mês usado como vencimento default

CATEGORIAS_PADRAO = [
    ('Salário', '#3b82f6'),
    ('Aluguel', '#8b5cf6'),
    ('Material', '#10b981'),
    ('Água/Luz', '#f59e0b'),
    ('Outros', '#6b7280'),
]


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
def seed_categorias_padrao():
    """Cria as categorias padrão se ainda não existirem. Idempotente."""
    if CategoriaDespesa.query.count() > 0:
        return 0
    for nome, cor in CATEGORIAS_PADRAO:
        db.session.add(CategoriaDespesa(nome=nome, cor=cor))
    db.session.commit()
    return len(CATEGORIAS_PADRAO)


# --------------------------------------------------------------------------- #
# Mensalidades
# --------------------------------------------------------------------------- #
def _vencimento_padrao(mes, ano):
    """Devolve o ``date`` de vencimento padrão para um mês — dia ``VENCIMENTO_DIA_PADRAO``,
    truncado pro último dia do mês quando o mês é mais curto."""
    ultimo = monthrange(ano, mes)[1]
    dia = min(VENCIMENTO_DIA_PADRAO, ultimo)
    return date(ano, mes, dia)


def gerar_mensalidades_lote(mes, ano, valor_default=None, vencimento=None):
    """Gera ``Mensalidade`` pra cada aluno ativo que ainda não tenha uma do mês.

    Args:
        mes, ano: período da mensalidade.
        valor_default: usado quando aluno não tem ``mensalidade_padrao``.
            Se nem um nem outro existir, o aluno é pulado.
        vencimento: ``date`` opcional. Se omitido, usa dia ``VENCIMENTO_DIA_PADRAO`` do mês.

    Returns:
        dict ``{criadas: int, puladas: int, alunos_sem_valor: list[str], alunos_sem_responsavel: list[str]}``.
    """
    venc = vencimento or _vencimento_padrao(mes, ano)
    valor_default_dec = Decimal(str(valor_default)) if valor_default is not None else None

    criadas = 0
    puladas = 0
    sem_valor = []
    sem_resp = []

    alunos = Aluno.query.filter(Aluno.turma_id.isnot(None)).all()

    for aluno in alunos:
        ja_existe = Mensalidade.query.filter_by(
            aluno_id=aluno.id, mes=mes, ano=ano
        ).first()
        if ja_existe:
            puladas += 1
            continue

        # Responsável é obrigatório só para menores
        if aluno.idade is not None and aluno.idade < 18 and not aluno.responsaveis:
            sem_resp.append(aluno.nome)
            continue
        responsavel = aluno.responsaveis[0] if aluno.responsaveis else None

        valor = aluno.mensalidade_padrao or valor_default_dec
        if valor is None:
            sem_valor.append(aluno.nome)
            continue

        m = Mensalidade(
            aluno_id=aluno.id,
            responsavel_id=responsavel.id if responsavel else None,
            mes=mes,
            ano=ano,
            valor=Decimal(str(valor)),
            vencimento=venc,
        )
        db.session.add(m)
        criadas += 1

    db.session.commit()
    return {
        'criadas': criadas,
        'puladas': puladas,
        'alunos_sem_valor': sem_valor,
        'alunos_sem_responsavel': sem_resp,
    }


def criar_mensalidade_avulsa(aluno_id, responsavel_id, mes, ano, valor, vencimento, observacao=None):
    """Cria uma única mensalidade — usado pra casos fora do lote (ajustes, etc.)."""
    m = Mensalidade(
        aluno_id=aluno_id,
        responsavel_id=responsavel_id,
        mes=mes,
        ano=ano,
        valor=Decimal(str(valor)),
        vencimento=vencimento,
        observacao=observacao,
    )
    db.session.add(m)
    db.session.commit()
    return m


# --------------------------------------------------------------------------- #
# Boletos
# --------------------------------------------------------------------------- #
def emitir_boleto(mensalidade):
    """Chama o Cora pra emitir o boleto de uma mensalidade e salva no banco.

    Returns:
        :class:`Boleto` recém-criado.
    """
    aluno = mensalidade.aluno
    resp = mensalidade.responsavel

    cora = get_cora_client()
    if resp is not None:
        pagador = {
            'nome': resp.nome,
            'cpf': '00000000000',  # mock não valida; real precisa de CPF do responsável
            'email': resp.email or '',
            'telefone': resp.telefone or '',
        }
    else:
        # Aluno adulto sem responsável: ele mesmo é o pagador
        pagador = {
            'nome': aluno.nome,
            'cpf': aluno.cpf or '00000000000',
            'email': '',
            'telefone': aluno.telefone or '',
        }
    descricao = f'Mensalidade {mensalidade.mes:02d}/{mensalidade.ano} — {aluno.nome}'

    resp_cora = cora.criar_boleto(
        valor=mensalidade.valor,
        vencimento=mensalidade.vencimento,
        pagador=pagador,
        descricao=descricao,
    )

    boleto = Boleto(
        mensalidade_id=mensalidade.id,
        cora_boleto_id=resp_cora['cora_id'],
        status=resp_cora['status'],
        valor=mensalidade.valor,
        vencimento=mensalidade.vencimento,
        link_pdf=resp_cora.get('link_pdf'),
        link_boleto=resp_cora.get('link_boleto'),
    )
    db.session.add(boleto)
    db.session.commit()
    return boleto


def cancelar_boleto(boleto):
    """Cancela um boleto e atualiza status local.

    Para boletos manuais (boleto_manual/pix_manual) só atualiza o status.
    Para boletos do Cora chama a API.
    """
    if boleto.tipo_cobranca in ('boleto_manual', 'pix_manual') or not boleto.cora_boleto_id:
        boleto.status = 'cancelado'
        db.session.commit()
        return True
    cora = get_cora_client()
    ok = cora.cancelar_boleto(boleto.cora_boleto_id)
    if ok:
        boleto.status = 'cancelado'
        db.session.commit()
    return ok


# --------------------------------------------------------------------------- #
# Cobrança manual (boleto colado ou PIX copia-e-cola)
# --------------------------------------------------------------------------- #
def registrar_cobranca_manual(mensalidade, tipo, linha_digitavel=None,
                              pix_copia_cola=None, pdf_path=None):
    """Cria um Boleto manual vinculado a uma mensalidade, sem chamar Cora.

    Args:
        mensalidade: instância de :class:`Mensalidade`.
        tipo: ``'boleto_manual'`` ou ``'pix_manual'``.
        linha_digitavel: obrigatória se ``tipo='boleto_manual'``.
        pix_copia_cola: obrigatório se ``tipo='pix_manual'``.
        pdf_path: caminho relativo do PDF do boleto (opcional, só pra boleto_manual).

    Returns:
        :class:`Boleto` recém-criado.

    Raises:
        ValueError: se tipo inválido ou faltarem campos obrigatórios.
    """
    if tipo not in ('boleto_manual', 'pix_manual'):
        raise ValueError(f'tipo de cobrança inválido: {tipo}')
    if tipo == 'boleto_manual' and not (linha_digitavel or '').strip():
        raise ValueError('Linha digitável é obrigatória para boleto manual.')
    if tipo == 'pix_manual' and not (pix_copia_cola or '').strip():
        raise ValueError('Código PIX copia-e-cola é obrigatório.')

    boleto = Boleto(
        mensalidade_id=mensalidade.id,
        tipo_cobranca=tipo,
        status='aberto',
        valor=mensalidade.valor,
        vencimento=mensalidade.vencimento,
        linha_digitavel=(linha_digitavel or '').strip() or None,
        pix_copia_cola=(pix_copia_cola or '').strip() or None,
        pdf_path=pdf_path,
    )
    db.session.add(boleto)
    db.session.commit()
    return boleto


def marcar_cobranca_paga(boleto, pago_em=None):
    """Marca uma cobrança manual como paga e gera entrada no fluxo.

    Wrapper em torno de :func:`registrar_pagamento_boleto` pra manter a
    nomenclatura consistente nas rotas manuais.
    """
    return registrar_pagamento_boleto(boleto, pago_em=pago_em)


# --------------------------------------------------------------------------- #
# Cobrança via Mercado Pago
# --------------------------------------------------------------------------- #
def _montar_pagador_mp(mensalidade):
    """Extrai dict pagador a partir do aluno/responsável da mensalidade.

    Aluno é sempre o pagador (tem CPF e endereço completo no cadastro v2).
    Email e nome do responsável são usados quando há um.
    """
    aluno = mensalidade.aluno
    resp = mensalidade.responsavel
    nome = (resp.nome if resp else aluno.nome) or 'Pagador'
    partes = nome.strip().split(' ', 1)
    first = partes[0]
    last = partes[1] if len(partes) > 1 else ''
    email = (resp.email if resp and resp.email else None) or ''
    return {
        'nome': nome,
        'first_name': first,
        'last_name': last,
        'email': email,
        'cpf': aluno.cpf or '',
        'cep': aluno.cep or '',
        'logradouro': aluno.logradouro or '',
        'numero': aluno.numero or '',
        'bairro': aluno.bairro or '',
        'cidade': aluno.cidade or '',
        'uf': aluno.uf or '',
    }


def emitir_cobranca_mp(mensalidade, tipo):
    """Cria pagamento no Mercado Pago e persiste como Boleto local.

    Args:
        mensalidade: instância de :class:`Mensalidade`.
        tipo: ``'pix'`` ou ``'boleto'``.

    Returns:
        :class:`Boleto` recém-criado.

    Raises:
        ValueError: tipo inválido.
        MercadoPagoError: erro de configuração ou da API do MP.
    """
    from app.services_mercadopago import get_mp_client, MercadoPagoError  # noqa: F401

    if tipo not in ('pix', 'boleto'):
        raise ValueError(f"tipo MP inválido: {tipo} (use 'pix' ou 'boleto')")

    client = get_mp_client()
    pagador = _montar_pagador_mp(mensalidade)
    descricao = (f'Mensalidade {mensalidade.mes:02d}/{mensalidade.ano} '
                 f'— {mensalidade.aluno.nome}')

    if tipo == 'pix':
        res = client.criar_pagamento_pix(
            valor=mensalidade.valor,
            descricao=descricao,
            pagador=pagador,
            vencimento=mensalidade.vencimento,
        )
        boleto = Boleto(
            mensalidade_id=mensalidade.id,
            tipo_cobranca='mp_pix',
            status='aberto',
            valor=mensalidade.valor,
            vencimento=mensalidade.vencimento,
            mp_payment_id=res['payment_id'],
            pix_copia_cola=res['copia_cola'] or None,
            link_boleto=res['ticket_url'] or None,
        )
    else:
        res = client.criar_pagamento_boleto(
            valor=mensalidade.valor,
            descricao=descricao,
            pagador=pagador,
            vencimento=mensalidade.vencimento,
        )
        boleto = Boleto(
            mensalidade_id=mensalidade.id,
            tipo_cobranca='mp_boleto',
            status='aberto',
            valor=mensalidade.valor,
            vencimento=mensalidade.vencimento,
            mp_payment_id=res['payment_id'],
            linha_digitavel=res['linha_digitavel'] or None,
            link_pdf=res['pdf_url'] or None,
        )

    db.session.add(boleto)
    db.session.commit()
    return boleto


def boleto_por_mp_payment_id(payment_id):
    """Busca o Boleto local correspondente a um payment do MP."""
    if not payment_id:
        return None
    return Boleto.query.filter_by(mp_payment_id=str(payment_id)).first()


def registrar_pagamento_boleto(boleto, pago_em=None):
    """Marca um boleto como pago e gera a ``Movimentacao`` de entrada.

    Chamado pelo webhook do Cora ou pelo endpoint de simulação no mock.
    Idempotente: se já estiver pago, não duplica movimentação.
    """
    if boleto.status == 'pago':
        return False
    boleto.status = 'pago'
    boleto.pago_em = pago_em or datetime.utcnow()

    descr = f'Boleto #{boleto.id}'
    if boleto.mensalidade:
        m = boleto.mensalidade
        descr = f'Mensalidade {m.mes:02d}/{m.ano} — {m.aluno.nome}'

    mov = Movimentacao(
        tipo='entrada',
        descricao=descr,
        valor=boleto.valor,
        data=boleto.pago_em.date(),
        boleto_id=boleto.id,
    )
    db.session.add(mov)
    db.session.commit()
    return True


def sincronizar_status_boletos():
    """Consulta o Cora pra cada boleto ainda em aberto e atualiza local.

    Usado quando webhook não está disponível (ex.: ambiente local).
    Devolve dict com totais.
    """
    cora = get_cora_client()
    abertos = Boleto.query.filter(Boleto.status.in_(['aberto', 'vencido'])).all()
    pagos_agora = 0
    vencidos_agora = 0
    erros = 0
    for b in abertos:
        if not b.cora_boleto_id:
            continue
        try:
            info = cora.consultar_boleto(b.cora_boleto_id)
        except CoraError:
            erros += 1
            continue
        if info['status'] == 'pago' and b.status != 'pago':
            registrar_pagamento_boleto(b, pago_em=info.get('pago_em'))
            pagos_agora += 1
        elif info['status'] == 'vencido' and b.status != 'vencido':
            b.status = 'vencido'
            vencidos_agora += 1
    db.session.commit()
    return {'pagos': pagos_agora, 'vencidos': vencidos_agora, 'erros': erros}


# --------------------------------------------------------------------------- #
# KPIs e relatórios
# --------------------------------------------------------------------------- #
def _intervalo_mes(mes, ano):
    inicio = date(ano, mes, 1)
    ultimo = monthrange(ano, mes)[1]
    fim = date(ano, mes, ultimo)
    return inicio, fim


def kpis_mes(mes, ano):
    """KPIs do dashboard financeiro pra um mês.

    Returns:
        dict com:
        - ``recebido``: soma dos boletos pagos no mês (por ``pago_em``).
        - ``recebido_count``: quantidade.
        - ``atrasado``: soma dos boletos vencidos+abertos com vencimento <= hoje.
        - ``atrasado_count``: quantidade.
        - ``a_receber_hoje``: soma dos boletos com vencimento = hoje e status aberto.
        - ``a_receber_hoje_count``: quantidade.
        - ``previsto_mes``: soma de mensalidades do mês (independente de status).
    """
    inicio, fim = _intervalo_mes(mes, ano)
    hoje = date.today()

    recebido = db.session.query(
        func.coalesce(func.sum(Boleto.valor), 0),
        func.count(Boleto.id),
    ).filter(
        Boleto.status == 'pago',
        Boleto.pago_em >= datetime.combine(inicio, datetime.min.time()),
        Boleto.pago_em <= datetime.combine(fim, datetime.max.time()),
    ).one()

    atrasado = db.session.query(
        func.coalesce(func.sum(Boleto.valor), 0),
        func.count(Boleto.id),
    ).filter(
        Boleto.status.in_(['aberto', 'vencido']),
        Boleto.vencimento < hoje,
    ).one()

    a_receber_hoje = db.session.query(
        func.coalesce(func.sum(Boleto.valor), 0),
        func.count(Boleto.id),
    ).filter(
        Boleto.status == 'aberto',
        Boleto.vencimento == hoje,
    ).one()

    previsto = db.session.query(
        func.coalesce(func.sum(Mensalidade.valor), 0),
    ).filter(
        Mensalidade.mes == mes,
        Mensalidade.ano == ano,
    ).scalar()

    return {
        'recebido': Decimal(str(recebido[0])),
        'recebido_count': int(recebido[1]),
        'atrasado': Decimal(str(atrasado[0])),
        'atrasado_count': int(atrasado[1]),
        'a_receber_hoje': Decimal(str(a_receber_hoje[0])),
        'a_receber_hoje_count': int(a_receber_hoje[1]),
        'previsto_mes': Decimal(str(previsto)),
    }


def fluxo_caixa(de, ate):
    """Entradas, saídas e saldo no período.

    Returns:
        dict ``{entradas, saidas, saldo, movimentacoes}``.
    """
    movs = Movimentacao.query.filter(
        and_(Movimentacao.data >= de, Movimentacao.data <= ate)
    ).order_by(Movimentacao.data.desc(), Movimentacao.id.desc()).all()

    entradas = sum((m.valor for m in movs if m.tipo == 'entrada'), Decimal('0'))
    saidas = sum((m.valor for m in movs if m.tipo == 'saida'), Decimal('0'))
    return {
        'entradas': entradas,
        'saidas': saidas,
        'saldo': entradas - saidas,
        'movimentacoes': movs,
    }


def inadimplentes(escopo='mes', mes=None, ano=None):
    """Devolve lista de inadimplentes (aluno + responsável + boletos atrasados).

    Args:
        escopo: ``'mes'`` (boletos com vencimento dentro do mês informado e em
            atraso) ou ``'todos'`` (qualquer boleto vencido em aberto).
        mes, ano: obrigatórios quando ``escopo='mes'``. Default: mês atual.

    Returns:
        list de dicts ``{aluno, responsavel, boletos: [...], total_devido}``.
    """
    hoje = date.today()
    q = db.session.query(Boleto).filter(
        Boleto.status.in_(['aberto', 'vencido']),
        Boleto.vencimento < hoje,
    )
    if escopo == 'mes':
        mes = mes or hoje.month
        ano = ano or hoje.year
        inicio, fim = _intervalo_mes(mes, ano)
        q = q.filter(Boleto.vencimento >= inicio, Boleto.vencimento <= fim)

    boletos = q.all()

    # Agrupa por aluno
    por_aluno = {}
    for b in boletos:
        if not b.mensalidade:
            continue  # boleto avulso sem aluno — fora do "inadimplente aluno"
        aluno = b.mensalidade.aluno
        resp = b.mensalidade.responsavel  # pode ser None pra aluno adulto
        chave = aluno.id
        if chave not in por_aluno:
            por_aluno[chave] = {
                'aluno': aluno,
                'responsavel': resp,
                'boletos': [],
                'total_devido': Decimal('0'),
            }
        por_aluno[chave]['boletos'].append(b)
        por_aluno[chave]['total_devido'] += b.valor

    return sorted(
        por_aluno.values(),
        key=lambda x: x['total_devido'],
        reverse=True,
    )


# --------------------------------------------------------------------------- #
# Plano de pagamento (parcelamento)
# --------------------------------------------------------------------------- #
JANELA_EMISSAO_DIAS = 30  # boleto da 1ª mensalidade emitido se vence em ≤ 30 dias


def proximo_dia_util(d):
    """Empurra ``date`` pra próxima segunda se cair em sábado/domingo. Sem feriados."""
    while d.weekday() >= 5:  # 5=sábado, 6=domingo
        d = d + timedelta(days=1)
    return d


def _calcular_data_primeira(dia_vencimento, mes_inicio, ano_inicio):
    ultimo = monthrange(ano_inicio, mes_inicio)[1]
    dia = min(dia_vencimento, ultimo)
    return proximo_dia_util(date(ano_inicio, mes_inicio, dia))


def _avancar_mes(mes, ano):
    return (1, ano + 1) if mes == 12 else (mes + 1, ano)


def plano_ativo_do_aluno(aluno):
    return PlanoPagamento.query.filter_by(
        aluno_id=aluno.id, status='ativo'
    ).order_by(PlanoPagamento.criado_em.desc()).first()


def criar_plano_pagamento(aluno, n_parcelas, valor_parcela, dia_vencimento=10,
                          mes_inicio=None, ano_inicio=None, observacao=None):
    """Cria um plano de pagamento para o aluno e gera N mensalidades.

    Estratégia híbrida: registra as ``n_parcelas`` mensalidades de uma vez,
    mas só **emite** o boleto da primeira (e somente se vencer em ≤ 30 dias).
    As próximas ficam aguardando emissão (manual ou via scheduler futuro).

    Args:
        aluno: instância de :class:`Aluno`.
        n_parcelas: número de mensalidades.
        valor_parcela: valor de cada parcela (Decimal/str/float aceitos).
        dia_vencimento: dia do mês (1-28). Cai pra último dia se mês mais curto.
        mes_inicio, ano_inicio: período da primeira parcela. Default: mês atual
            se hoje + 5 dias <= dia do vencimento; senão, próximo mês.
        observacao: texto livre opcional.

    Returns:
        dict ``{plano, mensalidades_criadas: int, boleto_emitido: Boleto|None,
                 mensalidades_puladas: list[(mes, ano)]}``.

    Raises:
        ValueError: se aluno não tiver responsável ou já tiver plano ativo.
    """
    # Responsável é obrigatório só para menores de 18.
    if (aluno.idade is not None and aluno.idade < 18 and not aluno.responsaveis):
        raise ValueError('Aluno menor de idade precisa de responsável vinculado.')
    if plano_ativo_do_aluno(aluno):
        raise ValueError('Aluno já tem plano de pagamento ativo. Cancele ou renegocie.')
    if n_parcelas < 1 or n_parcelas > 60:
        raise ValueError('Número de parcelas deve estar entre 1 e 60.')
    if not 1 <= dia_vencimento <= 28:
        raise ValueError('Dia do vencimento deve estar entre 1 e 28.')

    valor = Decimal(str(valor_parcela))
    if valor <= 0:
        raise ValueError('Valor da parcela deve ser positivo.')

    hoje = date.today()
    if mes_inicio is None or ano_inicio is None:
        # Se ainda dá pra cobrar este mês com >=5 dias de antecedência, começa este mês.
        # Senão, próximo.
        candidata_este_mes = _calcular_data_primeira(dia_vencimento, hoje.month, hoje.year)
        if (candidata_este_mes - hoje).days >= 5:
            mes_inicio, ano_inicio = hoje.month, hoje.year
        else:
            mes_inicio, ano_inicio = _avancar_mes(hoje.month, hoje.year)

    data_primeira = _calcular_data_primeira(dia_vencimento, mes_inicio, ano_inicio)
    responsavel = aluno.responsaveis[0] if aluno.responsaveis else None

    plano = PlanoPagamento(
        aluno_id=aluno.id,
        n_parcelas=n_parcelas,
        valor_parcela=valor,
        dia_vencimento=dia_vencimento,
        data_primeira=data_primeira,
        status='ativo',
        observacao=observacao,
    )
    db.session.add(plano)
    db.session.flush()

    mes, ano = mes_inicio, ano_inicio
    criadas = []
    puladas = []
    for _ in range(n_parcelas):
        existe = Mensalidade.query.filter_by(
            aluno_id=aluno.id, mes=mes, ano=ano
        ).first()
        if existe:
            puladas.append((mes, ano))
        else:
            venc = _calcular_data_primeira(dia_vencimento, mes, ano)
            m = Mensalidade(
                aluno_id=aluno.id,
                responsavel_id=responsavel.id if responsavel else None,
                plano_id=plano.id,
                mes=mes, ano=ano,
                valor=valor,
                vencimento=venc,
            )
            db.session.add(m)
            criadas.append(m)
        mes, ano = _avancar_mes(mes, ano)

    db.session.flush()

    # Emite só o boleto da primeira mensalidade nova, se vencer em ≤ 30 dias
    boleto_emitido = None
    if criadas:
        primeira = criadas[0]
        if (primeira.vencimento - hoje).days <= JANELA_EMISSAO_DIAS:
            try:
                boleto_emitido = emitir_boleto(primeira)
            except CoraError:
                # Plano e mensalidades ficam — só o boleto falhou. Admin pode reemitir depois.
                pass

    db.session.commit()
    return {
        'plano': plano,
        'mensalidades_criadas': len(criadas),
        'mensalidades_puladas': puladas,
        'boleto_emitido': boleto_emitido,
    }


def cancelar_plano_aluno(aluno, motivo=None):
    """Cancela o plano ativo do aluno + mensalidades futuras + boletos abertos.

    Não toca em mensalidades pagas ou já vencidas que tenham sido pagas.
    Idempotente: se aluno não tem plano ativo, retorna contadores zerados.

    Returns:
        dict ``{plano_cancelado: bool, mensalidades_canceladas: int,
                 boletos_cancelados: int, erros_cora: int}``.
    """
    plano = plano_ativo_do_aluno(aluno)
    resultado = {
        'plano_cancelado': False,
        'mensalidades_canceladas': 0,
        'boletos_cancelados': 0,
        'erros_cora': 0,
    }
    if not plano:
        return resultado

    hoje = date.today()
    for m in plano.mensalidades:
        # Já cancelada anteriormente
        if m.cancelada_em:
            continue
        # Tem boleto aberto/vencido? cancela no Cora
        for b in m.boletos:
            if b.status in ('aberto', 'vencido'):
                try:
                    if cancelar_boleto(b):
                        resultado['boletos_cancelados'] += 1
                    else:
                        resultado['erros_cora'] += 1
                except CoraError:
                    resultado['erros_cora'] += 1
        # Marca mensalidade como cancelada se ainda não tem boleto pago
        tem_pago = any(b.status == 'pago' for b in m.boletos)
        if not tem_pago:
            m.cancelada_em = datetime.utcnow()
            resultado['mensalidades_canceladas'] += 1

    plano.status = 'cancelado'
    plano.cancelado_em = datetime.utcnow()
    if motivo:
        plano.observacao = (plano.observacao or '') + f'\n[cancelado] {motivo}'
    resultado['plano_cancelado'] = True

    db.session.commit()
    return resultado


# --------------------------------------------------------------------------- #
# Movimentação manual
# --------------------------------------------------------------------------- #
def registrar_movimentacao_manual(
    tipo, descricao, valor, data, categoria_id=None,
    comprovante_path=None, criado_por_id=None,
):
    """Lança uma movimentação manual (entrada ou saída) no fluxo de caixa.

    Usado pra despesas como salário/aluguel ou entradas avulsas que não
    vieram de boleto.
    """
    if tipo not in ('entrada', 'saida'):
        raise ValueError(f'tipo inválido: {tipo}')
    mov = Movimentacao(
        tipo=tipo,
        descricao=descricao,
        valor=Decimal(str(valor)),
        data=data,
        categoria_id=categoria_id,
        comprovante_path=comprovante_path,
        criado_por_id=criado_por_id,
    )
    db.session.add(mov)
    db.session.commit()
    return mov
