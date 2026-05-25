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
    Aluno, Boleto, CategoriaDespesa, MatriculaTurma, Mensalidade, Movimentacao,
    Responsavel, PlanoPagamento,
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
    """Gera ``Mensalidade`` pra cada matrícula ativa que ainda não tenha uma do mês.

    Itera matrículas (não alunos) — aluno com N turmas ativas gera N mensalidades.
    Valor por matrícula segue a ordem: ``matricula.mensalidade_padrao`` ->
    ``aluno.mensalidade_padrao`` -> ``valor_default``.

    Args:
        mes, ano: período da mensalidade.
        valor_default: fallback final quando matrícula e aluno não têm valor.
        vencimento: ``date`` opcional. Se omitido, usa dia ``VENCIMENTO_DIA_PADRAO`` do mês.

    Returns:
        dict ``{criadas, puladas, alunos_sem_valor, alunos_sem_responsavel}``.
        As listas usam ``"<aluno> (<turma>)"`` pra identificar a matrícula.
    """
    venc = vencimento or _vencimento_padrao(mes, ano)
    valor_default_dec = Decimal(str(valor_default)) if valor_default is not None else None

    criadas = 0
    puladas = 0
    sem_valor = []
    sem_resp = []

    matriculas = MatriculaTurma.query.filter_by(status='ativo').all()

    for matricula in matriculas:
        aluno = matricula.aluno
        if aluno is None:
            continue
        rotulo = f'{aluno.nome} ({matricula.turma.nome if matricula.turma else "?"})'

        ja_existe = Mensalidade.query.filter_by(
            matricula_turma_id=matricula.id, mes=mes, ano=ano
        ).first()
        if ja_existe:
            puladas += 1
            continue

        # Responsável obrigatório só pra menor de idade
        if aluno.idade is not None and aluno.idade < 18 and not aluno.responsaveis:
            sem_resp.append(rotulo)
            continue

        # Responsável: plano ativo da matrícula > aluno.responsaveis[0]
        plano = plano_ativo_da_matricula(matricula)
        if plano and plano.responsavel_id:
            responsavel_id = plano.responsavel_id
        elif aluno.responsaveis:
            responsavel_id = aluno.responsaveis[0].id
        else:
            responsavel_id = None

        # Valor: matrícula > aluno > default
        valor = matricula.mensalidade_padrao or aluno.mensalidade_padrao or valor_default_dec
        if valor is None:
            sem_valor.append(rotulo)
            continue

        m = Mensalidade(
            aluno_id=aluno.id,
            responsavel_id=responsavel_id,
            matricula_turma_id=matricula.id,
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


def _brl(v):
    """Formata número no padrão R$ 1.234,56."""
    if v is None:
        return 'R$ 0,00'
    s = f'{float(v):,.2f}'
    return 'R$ ' + s.replace(',', 'X').replace('.', ',').replace('X', '.')


def boletos_em_atraso_do_aluno(aluno):
    """Todos os boletos vencidos e em aberto de um aluno, ordenados por vencimento.

    Independente de filtro de mês — devolve a dívida completa (1, 2, 3+ meses),
    para o lembrete sempre refletir tudo o que o aluno deve.
    """
    hoje = date.today()
    return (
        db.session.query(Boleto)
        .join(Mensalidade, Boleto.mensalidade_id == Mensalidade.id)
        .filter(
            Mensalidade.aluno_id == aluno.id,
            Boleto.status.in_(['aberto', 'vencido']),
            Boleto.vencimento < hoje,
        )
        .order_by(Boleto.vencimento.asc())
        .all()
    )


def _nome_curso_do_boleto(boleto):
    """Nome da turma (curso) vinculada ao boleto, com fallback seguro."""
    mens = boleto.mensalidade
    if mens and mens.matricula and mens.matricula.turma:
        return mens.matricula.turma.nome
    return 'curso'


def texto_lembrete_inadimplencia(item):
    """Monta o texto do lembrete de WhatsApp para um inadimplente.

    ``item`` é um dict no formato devolvido por :func:`inadimplentes`
    (``{aluno, responsavel, ...}``). A mensagem lista **todos** os meses em
    atraso do aluno (não apenas os do filtro de tela) — uma linha por boleto.

    Regras:
      - 1 boleto em atraso → frase única e natural.
      - 2+ boletos → uma linha por mês (curso — valor — venc. dd/mm/aaaa) + total.
      - Se o aluno tem 2+ turmas ativas, acrescenta a linha "Você está inscrito(a) em".
    """
    aluno = item['aluno']
    resp = item.get('responsavel')
    nome_dest = resp.nome if resp else aluno.nome

    atrasados = boletos_em_atraso_do_aluno(aluno)
    if not atrasados:
        return f'Olá, {nome_dest}! Tudo bem?'

    linhas = [f'Olá, {nome_dest}! Tudo bem?']

    if len(atrasados) == 1:
        b = atrasados[0]
        linhas.append(
            f'Estou entrando em contato referente à mensalidade do curso de '
            f'{_nome_curso_do_boleto(b)}, que está em aberto no valor de '
            f'{_brl(b.valor)}, com vencimento para '
            f'{b.vencimento.strftime("%d/%m/%Y")}.'
        )
    else:
        linhas.append('Estou entrando em contato referente às mensalidades em aberto:')
        total = Decimal('0')
        for b in atrasados:
            total += b.valor
            linhas.append(
                f'• {_nome_curso_do_boleto(b)} — {_brl(b.valor)} '
                f'(venc. {b.vencimento.strftime("%d/%m/%Y")})'
            )
        linhas.append(f'Total em aberto: {_brl(total)}.')

    turmas_ativas = aluno.turmas_ativas
    if len(turmas_ativas) >= 2:
        nomes = ', '.join(t.nome for t in turmas_ativas)
        linhas.append('')
        linhas.append(f'Você está inscrito(a) em: {nomes}.')

    return '\n'.join(linhas)


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


def plano_ativo_da_matricula(matricula):
    """Plano ativo de uma matrícula específica (ou None)."""
    return PlanoPagamento.query.filter_by(
        matricula_turma_id=matricula.id, status='ativo'
    ).order_by(PlanoPagamento.criado_em.desc()).first()


def planos_ativos_do_aluno(aluno):
    """Lista de planos ativos do aluno — um por matrícula ativa que tenha plano."""
    return PlanoPagamento.query.filter(
        PlanoPagamento.aluno_id == aluno.id,
        PlanoPagamento.status == 'ativo',
    ).order_by(PlanoPagamento.criado_em.asc()).all()


def plano_ativo_do_aluno(aluno):
    """Compat: primeiro plano ativo do aluno (qualquer matrícula).

    Mantida pra código legado. Código novo deve usar
    :func:`plano_ativo_da_matricula` ou :func:`planos_ativos_do_aluno`.
    """
    planos = planos_ativos_do_aluno(aluno)
    return planos[0] if planos else None


def criar_plano_pagamento(matricula, n_parcelas, valor_parcela, dia_vencimento=10,
                          mes_inicio=None, ano_inicio=None, observacao=None,
                          responsavel_id=None):
    """Cria um plano de pagamento para uma matrícula e gera N mensalidades.

    Estratégia híbrida: registra as ``n_parcelas`` mensalidades de uma vez,
    mas só **emite** o boleto da primeira (e somente se vencer em ≤ 30 dias).
    As próximas ficam aguardando emissão (manual ou via scheduler futuro).

    Args:
        matricula: instância de :class:`MatriculaTurma` (precisa estar ``ativo``).
        n_parcelas: número de mensalidades.
        valor_parcela: valor de cada parcela (Decimal/str/float aceitos).
        dia_vencimento: dia do mês (1-28). Cai pra último dia se mês mais curto.
        mes_inicio, ano_inicio: período da primeira parcela. Default: mês atual
            se hoje + 5 dias <= dia do vencimento; senão, próximo mês.
        observacao: texto livre opcional.
        responsavel_id: pagador deste plano. Default: ``aluno.responsaveis[0]``.

    Returns:
        dict ``{plano, mensalidades_criadas: int, boleto_emitido: Boleto|None,
                 mensalidades_puladas: list[(mes, ano)]}``.

    Raises:
        ValueError: matrícula não-ativa, menor sem responsável, plano já existe
            na matrícula, parcelas/dia inválidos ou valor não-positivo.
    """
    if matricula.status != 'ativo':
        raise ValueError(
            f'Matrícula está com status "{matricula.status}" — só matrícula '
            f'ativa pode receber plano.'
        )
    aluno = matricula.aluno
    if (aluno.idade is not None and aluno.idade < 18 and not aluno.responsaveis):
        raise ValueError('Aluno menor de idade precisa de responsável vinculado.')
    if plano_ativo_da_matricula(matricula):
        raise ValueError(
            f'Matrícula em "{matricula.turma.nome}" já tem plano ativo. '
            f'Cancele ou renegocie.'
        )
    if n_parcelas < 1 or n_parcelas > 60:
        raise ValueError('Número de parcelas deve estar entre 1 e 60.')
    if not 1 <= dia_vencimento <= 28:
        raise ValueError('Dia do vencimento deve estar entre 1 e 28.')

    valor = Decimal(str(valor_parcela))
    if valor <= 0:
        raise ValueError('Valor da parcela deve ser positivo.')

    # Responsável: parâmetro explícito > primeiro do aluno > None (adulto)
    if responsavel_id is not None:
        # valida que pertence ao aluno
        responsavel = next((r for r in aluno.responsaveis
                            if r.id == int(responsavel_id)), None)
        if not responsavel:
            raise ValueError(
                'Responsável escolhido não está vinculado a este aluno.'
            )
    else:
        responsavel = aluno.responsaveis[0] if aluno.responsaveis else None

    hoje = date.today()
    if mes_inicio is None or ano_inicio is None:
        candidata_este_mes = _calcular_data_primeira(dia_vencimento, hoje.month, hoje.year)
        if (candidata_este_mes - hoje).days >= 5:
            mes_inicio, ano_inicio = hoje.month, hoje.year
        else:
            mes_inicio, ano_inicio = _avancar_mes(hoje.month, hoje.year)

    data_primeira = _calcular_data_primeira(dia_vencimento, mes_inicio, ano_inicio)

    plano = PlanoPagamento(
        aluno_id=aluno.id,
        matricula_turma_id=matricula.id,
        responsavel_id=responsavel.id if responsavel else None,
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
            matricula_turma_id=matricula.id, mes=mes, ano=ano
        ).first()
        if existe:
            puladas.append((mes, ano))
        else:
            venc = _calcular_data_primeira(dia_vencimento, mes, ano)
            m = Mensalidade(
                aluno_id=aluno.id,
                responsavel_id=responsavel.id if responsavel else None,
                matricula_turma_id=matricula.id,
                plano_id=plano.id,
                mes=mes, ano=ano,
                valor=valor,
                vencimento=venc,
            )
            db.session.add(m)
            criadas.append(m)
        mes, ano = _avancar_mes(mes, ano)

    db.session.flush()

    boleto_emitido = None
    if criadas:
        primeira = criadas[0]
        if (primeira.vencimento - hoje).days <= JANELA_EMISSAO_DIAS:
            try:
                boleto_emitido = emitir_boleto(primeira)
            except CoraError:
                pass

    db.session.commit()
    return {
        'plano': plano,
        'mensalidades_criadas': len(criadas),
        'mensalidades_puladas': puladas,
        'boleto_emitido': boleto_emitido,
    }


def cancelar_plano_matricula(matricula, motivo=None):
    """Cancela o plano ativo de uma matrícula + mensalidades futuras + boletos abertos.

    Não toca em mensalidades pagas. Idempotente: se a matrícula não tem plano
    ativo, retorna contadores zerados sem erro.

    Returns:
        dict ``{plano_cancelado, mensalidades_canceladas, boletos_cancelados, erros_cora}``.
    """
    plano = plano_ativo_da_matricula(matricula)
    resultado = {
        'plano_cancelado': False,
        'mensalidades_canceladas': 0,
        'boletos_cancelados': 0,
        'erros_cora': 0,
    }
    if not plano:
        return resultado

    for m in plano.mensalidades:
        if m.cancelada_em:
            continue
        for b in m.boletos:
            if b.status in ('aberto', 'vencido'):
                try:
                    if cancelar_boleto(b):
                        resultado['boletos_cancelados'] += 1
                    else:
                        resultado['erros_cora'] += 1
                except CoraError:
                    resultado['erros_cora'] += 1
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


def cancelar_plano_aluno(aluno, motivo=None):
    """Cancela TODOS os planos ativos do aluno (todas as matrículas).

    Usado quando o aluno como um todo é desligado (status legacy ``evadido``).
    Para cancelar apenas o plano de uma matrícula específica, use
    :func:`cancelar_plano_matricula`.

    Returns:
        dict agregado ``{plano_cancelado: bool, planos_cancelados: int,
                          mensalidades_canceladas, boletos_cancelados, erros_cora}``.
        ``plano_cancelado`` é True se pelo menos 1 plano foi cancelado (compat).
    """
    agregado = {
        'plano_cancelado': False,
        'planos_cancelados': 0,
        'mensalidades_canceladas': 0,
        'boletos_cancelados': 0,
        'erros_cora': 0,
    }
    matriculas_com_plano = (
        MatriculaTurma.query
        .join(PlanoPagamento,
              PlanoPagamento.matricula_turma_id == MatriculaTurma.id)
        .filter(
            MatriculaTurma.aluno_id == aluno.id,
            PlanoPagamento.status == 'ativo',
        )
        .distinct()
        .all()
    )
    for matricula in matriculas_com_plano:
        res = cancelar_plano_matricula(matricula, motivo=motivo)
        if res['plano_cancelado']:
            agregado['planos_cancelados'] += 1
            agregado['plano_cancelado'] = True
        agregado['mensalidades_canceladas'] += res['mensalidades_canceladas']
        agregado['boletos_cancelados'] += res['boletos_cancelados']
        agregado['erros_cora'] += res['erros_cora']

    # Fallback: planos legacy ligados via aluno_id sem matricula_turma_id
    # (caso o backfill não tenha rodado ou rodado parcialmente).
    legacy = PlanoPagamento.query.filter(
        PlanoPagamento.aluno_id == aluno.id,
        PlanoPagamento.status == 'ativo',
        PlanoPagamento.matricula_turma_id.is_(None),
    ).all()
    for plano in legacy:
        for m in plano.mensalidades:
            if m.cancelada_em:
                continue
            for b in m.boletos:
                if b.status in ('aberto', 'vencido'):
                    try:
                        if cancelar_boleto(b):
                            agregado['boletos_cancelados'] += 1
                        else:
                            agregado['erros_cora'] += 1
                    except CoraError:
                        agregado['erros_cora'] += 1
            if not any(b.status == 'pago' for b in m.boletos):
                m.cancelada_em = datetime.utcnow()
                agregado['mensalidades_canceladas'] += 1
        plano.status = 'cancelado'
        plano.cancelado_em = datetime.utcnow()
        if motivo:
            plano.observacao = (plano.observacao or '') + f'\n[cancelado] {motivo}'
        agregado['planos_cancelados'] += 1
        agregado['plano_cancelado'] = True
    if legacy:
        db.session.commit()

    return agregado


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
