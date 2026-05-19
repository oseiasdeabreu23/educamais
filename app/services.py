import re
from datetime import date, timedelta
from sqlalchemy import extract, or_, and_, func
from app.models import Aluno, Nota, Frequencia, Observacao, MatriculaTurma, Turma
from app import db


# ── CPF / CEP / UF ─────────────────────────────────────────────────────────────

UFS_BR = ('AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT',
          'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO',
          'RR', 'SC', 'SP', 'SE', 'TO')


def so_digitos(valor):
    if not valor:
        return ''
    return re.sub(r'\D', '', str(valor))


def cpf_valido(cpf):
    """Valida CPF pelo algoritmo dos dígitos verificadores (somente dígitos)."""
    cpf = so_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for i in (9, 10):
        soma = sum(int(cpf[n]) * ((i + 1) - n) for n in range(i))
        dig = (soma * 10) % 11
        if dig == 10:
            dig = 0
        if dig != int(cpf[i]):
            return False
    return True


def cep_valido(cep):
    return len(so_digitos(cep)) == 8


def uf_valida(uf):
    return (uf or '').strip().upper() in UFS_BR


# ── Matrículas em turma ────────────────────────────────────────────────────────

STATUS_MATRICULA_ENCERRADO = ('formado', 'evadido', 'transferido')


def matricula_ativa(aluno, turma):
    """Retorna a MatriculaTurma ativa do par (aluno, turma) ou None."""
    return MatriculaTurma.query.filter_by(
        aluno_id=aluno.id, turma_id=turma.id, status='ativo'
    ).first()


def matricular_em_turma(aluno, turma, data_matricula=None, observacao=None):
    """Cria uma MatriculaTurma ativa. Falha se já existe uma ativa para o par.

    Não faz commit — caller decide a transação.
    """
    if matricula_ativa(aluno, turma):
        raise ValueError(f'{aluno.nome} já tem matrícula ativa em {turma.nome}.')
    m = MatriculaTurma(
        aluno_id=aluno.id,
        turma_id=turma.id,
        status='ativo',
        data_matricula=data_matricula or date.today(),
        observacao=observacao or None,
    )
    db.session.add(m)
    return m


def _encerrar_matricula(matricula, novo_status, data_saida=None, observacao=None):
    if novo_status not in STATUS_MATRICULA_ENCERRADO:
        raise ValueError(f'Status inválido para encerramento: {novo_status}')
    if matricula.status != 'ativo':
        raise ValueError('Matrícula já está encerrada.')
    matricula.status = novo_status
    matricula.data_saida = data_saida or date.today()
    if observacao:
        matricula.observacao = (
            f'{matricula.observacao}\n{observacao}' if matricula.observacao else observacao
        )
    return matricula


def formar_em_turma(matricula, data_saida=None, observacao=None):
    return _encerrar_matricula(matricula, 'formado', data_saida, observacao)


def evadir_em_turma(matricula, data_saida=None, observacao=None):
    return _encerrar_matricula(matricula, 'evadido', data_saida, observacao)


def transferir_em_turma(matricula, data_saida=None, observacao=None):
    return _encerrar_matricula(matricula, 'transferido', data_saida, observacao)


# ── Filtros ────────────────────────────────────────────────────────────────────

def _aluno_ativo_clausula():
    """Cláusula SQL: aluno é ativo se tem ao menos 1 matrícula ativa
    OU (não tem nenhuma matrícula AND Aluno.status legacy = 'ativo').

    O fallback evita sumir alunos cadastrados antes da Fase 1 que ainda
    não foram matriculados em turma nenhuma.
    """
    tem_ativa = MatriculaTurma.query.filter(
        MatriculaTurma.aluno_id == Aluno.id,
        MatriculaTurma.status == 'ativo',
    ).exists()
    sem_matricula = ~MatriculaTurma.query.filter(
        MatriculaTurma.aluno_id == Aluno.id,
    ).exists()
    return or_(tem_ativa, and_(sem_matricula, Aluno.status == 'ativo'))


def _alunos_filtro_status(query, incluir_inativos=False):
    """Aplica filtro de "ativo" a uma query de Aluno, salvo override.

    Usa o status derivado das MatriculaTurma (fase 3), com fallback pra
    Aluno.status legacy quando o aluno não tem matrícula.
    """
    if incluir_inativos:
        return query
    return query.filter(_aluno_ativo_clausula())


def query_alunos_ativos_na_turma(turma_id, incluir_inativos=False):
    """Query de Aluno com matrícula ativa na turma indicada.

    Aplica fallback: se o aluno não tem matrícula nenhuma (caso legacy),
    cai na coluna ``Aluno.turma_id`` + ``Aluno.status='ativo'``.
    """
    tem_na_turma = MatriculaTurma.query.filter(
        MatriculaTurma.aluno_id == Aluno.id,
        MatriculaTurma.turma_id == turma_id,
        (MatriculaTurma.status == 'ativo') if not incluir_inativos else (1 == 1),
    ).exists()
    sem_matricula = ~MatriculaTurma.query.filter(
        MatriculaTurma.aluno_id == Aluno.id,
    ).exists()
    fallback_legacy = and_(
        sem_matricula,
        Aluno.turma_id == turma_id,
        Aluno.status == 'ativo',
    )
    return Aluno.query.filter(or_(tem_na_turma, fallback_legacy))


def alunos_ativos_na_turma(turma, incluir_inativos=False):
    """Lista de Aluno (ordenada por nome) ativos na turma."""
    return query_alunos_ativos_na_turma(
        turma.id, incluir_inativos=incluir_inativos
    ).order_by(Aluno.nome).all()


def _aluno_esta_ativo(aluno):
    """Versão Python do _aluno_ativo_clausula — pra filtragem em memória."""
    if any(m.status == 'ativo' for m in aluno.matriculas_turma):
        return True
    sem_matricula = aluno.matriculas_turma.count() == 0 if hasattr(
        aluno.matriculas_turma, 'count'
    ) else len(list(aluno.matriculas_turma)) == 0
    return sem_matricula and aluno.status == 'ativo'


def media_turma(turma, incluir_inativos=False):
    """Média da turma com base nas notas dos alunos com matrícula ativa nela.

    Uma única query agregada (AVG(nota.valor)) sobre o JOIN
    Nota ⋈ MatriculaTurma; sem lazy load. Quando a turma não tem nenhuma
    MatriculaTurma (caso raro pós-backfill), cai no caminho legacy via
    ``turma.alunos``.
    """
    q = db.session.query(func.avg(Nota.valor)).join(
        MatriculaTurma, MatriculaTurma.aluno_id == Nota.aluno_id
    ).filter(MatriculaTurma.turma_id == turma.id)
    if not incluir_inativos:
        q = q.filter(MatriculaTurma.status == 'ativo')
    media = q.scalar()
    if media is not None:
        return round(float(media), 2)

    # Fallback legacy: turma sem nenhuma MatriculaTurma — soma direto via
    # relação Aluno.turma_id. Some assim que todos os alunos legados forem
    # migrados (fase 5).
    alunos = [a for a in turma.alunos
              if incluir_inativos or (a.status or 'ativo') == 'ativo']
    if not alunos:
        return 0
    soma = 0
    n = 0
    for aluno in alunos:
        for nota in aluno.notas:
            soma += nota.valor
            n += 1
    return round(soma / n, 2) if n > 0 else 0


def medias_por_turma(incluir_inativos=False):
    """Retorna ``{turma_id: media}`` para TODAS as turmas em UMA única query.

    Substitui o padrão ``[media_turma(t) for t in turmas]`` (1 query por turma
    + N lazy loads) por um agregado com ``GROUP BY``. Turma sem nenhuma nota
    de aluno ativo fica ausente do dict — caller decide o fallback.
    """
    q = db.session.query(
        MatriculaTurma.turma_id,
        func.avg(Nota.valor),
    ).join(Nota, Nota.aluno_id == MatriculaTurma.aluno_id)
    if not incluir_inativos:
        q = q.filter(MatriculaTurma.status == 'ativo')
    q = q.group_by(MatriculaTurma.turma_id)
    return {turma_id: round(float(media), 2)
            for turma_id, media in q.all() if media is not None}


def frequencia_geral(incluir_inativos=False):
    q = Frequencia.query
    if not incluir_inativos:
        q = q.join(Aluno, Frequencia.aluno_id == Aluno.id).filter(
            _aluno_ativo_clausula()
        )
    total = q.count()
    if total == 0:
        return 0

    ausencias = q.filter(Frequencia.status == 'falta').count()
    return round((total - ausencias) / total * 100, 2)


def alunos_baixo_desempenho(limite=5.5, incluir_inativos=False):
    """Lista alunos ativos com média de notas abaixo de ``limite``.

    Uma única query: subquery agregada (AVG por aluno) com HAVING, juntada
    a Aluno e filtrada pelo critério de "ativo". Antes era N+1 (1 query pra
    listar ativos + 1 acesso lazy a ``aluno.notas`` por aluno).
    """
    media_subq = (
        db.session.query(
            Nota.aluno_id.label('aluno_id'),
            func.avg(Nota.valor).label('media'),
        )
        .group_by(Nota.aluno_id)
        .having(func.avg(Nota.valor) < limite)
        .subquery()
    )
    q = db.session.query(Aluno, media_subq.c.media).join(
        media_subq, Aluno.id == media_subq.c.aluno_id
    )
    if not incluir_inativos:
        q = q.filter(_aluno_ativo_clausula())
    return [{'aluno': aluno, 'media': round(float(media), 2)}
            for aluno, media in q.all()]


def status_derivado_por_aluno(aluno_ids):
    """Retorna ``{aluno_id: status_derivado}`` em UMA única query.

    Substitui o acesso N+1 a ``Aluno.status_derivado`` (que dispara uma query
    no backref ``matriculas_turma`` dinâmico por linha) ao listar muitos
    alunos. Aluno sem nenhuma MatriculaTurma fica ausente do dict — caller
    aplica fallback pra ``Aluno.status`` legacy.
    """
    if not aluno_ids:
        return {}
    rows = db.session.query(
        MatriculaTurma.aluno_id,
        MatriculaTurma.status,
        MatriculaTurma.data_saida,
        MatriculaTurma.data_matricula,
    ).filter(MatriculaTurma.aluno_id.in_(aluno_ids)).all()

    por_aluno = {}
    for aluno_id, status, ds, dm in rows:
        por_aluno.setdefault(aluno_id, []).append((status, ds or dm))

    resultado = {}
    for aluno_id, matriculas in por_aluno.items():
        if any(s == 'ativo' for s, _ in matriculas):
            resultado[aluno_id] = 'ativo'
        else:
            matriculas.sort(key=lambda x: x[1] or date.min, reverse=True)
            resultado[aluno_id] = matriculas[0][0]
    return resultado


def media_aluno(aluno):
    notas = aluno.notas
    if not notas:
        return 0
    soma = sum([nota.valor for nota in notas])
    return round(soma / len(notas), 2)


def queda_desempenho(aluno, disciplina_id=None):
    notas = [n for n in aluno.notas if disciplina_id is None or n.disciplina_id==disciplina_id]
    if len(notas) < 3:
        return False, ''
    notas = sorted(notas, key=lambda x: x.data)
    ultimas = [nota.valor for nota in notas[-3:]]
    if ultimas[0] > ultimas[1] > ultimas[2]:
        msg = f"O aluno apresentou queda de rendimento nas últimas avaliações."
        return True, msg
    return False, ''


def stats_frequencia(aluno, disciplina_id=None):
    """Retorna dict com total, presenças, faltas, justificadas, percentual."""
    freqs = [f for f in aluno.frequencias
             if disciplina_id is None or f.disciplina_id == disciplina_id]
    total       = len(freqs)
    presencas   = sum(1 for f in freqs if f.status == 'presente')
    justificadas = sum(1 for f in freqs if f.status == 'justificada')
    faltas      = sum(1 for f in freqs if f.status == 'falta')
    freq_valida = presencas + justificadas  # justificada conta como presença
    percentual  = round(freq_valida / total * 100, 1) if total > 0 else None
    return {
        'total': total,
        'presencas': presencas,
        'justificadas': justificadas,
        'faltas': faltas,
        'percentual': percentual,
    }


def faltas_consecutivas(aluno, disciplina_id=None, n=3):
    """Retorna True se o aluno tem n ou mais faltas consecutivas recentes."""
    freqs = sorted(
        [f for f in aluno.frequencias
         if disciplina_id is None or f.disciplina_id == disciplina_id],
        key=lambda x: x.data, reverse=True
    )
    if len(freqs) < n:
        return False
    return all(f.status == 'falta' for f in freqs[:n])


def alertas_frequencia(aluno, disciplina_id=None):
    """Retorna lista de strings com alertas de frequência."""
    alertas = []
    st = stats_frequencia(aluno, disciplina_id)
    if st['total'] == 0:
        return alertas
    if st['percentual'] is not None and st['percentual'] < 75:
        alertas.append(f"Frequência abaixo de 75% ({st['percentual']}%)")
    if faltas_consecutivas(aluno, disciplina_id, n=3):
        alertas.append("3 ou mais faltas consecutivas")
    return alertas


def embed_url(url):
    """Convert YouTube/Vimeo watch URLs to embed URLs."""
    import re
    yt = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    if yt:
        return f'https://www.youtube.com/embed/{yt.group(1)}'
    vimeo = re.search(r'vimeo\.com/(\d+)', url)
    if vimeo:
        return f'https://player.vimeo.com/video/{vimeo.group(1)}'
    return url


def aviso_whatsapp(aluno, disciplina):
    media = media_aluno(aluno)
    simbolo = '🟢' if media >= 7 else '⚠️' if media >= 5 else '🔴'
    return f"📊 EducaMais Informa:\nAluno: {aluno.nome}\n{disciplina.nome}: {media:.1f} {simbolo}\nAtenção: desempenho abaixo da média."


# ── Aniversariantes ────────────────────────────────────────────────────────────

ESCOPOS_ANIVERSARIO = ('dia', 'semana', 'mes')


def _idade_que_faz(data_nasc, ref):
    """Idade que a pessoa terá no aniversário deste ano (a partir de `ref`)."""
    if not data_nasc:
        return None
    anos = ref.year - data_nasc.year
    if (ref.month, ref.day) > (data_nasc.month, data_nasc.day):
        anos += 1
    return anos


def aniversariantes(escopo='dia', incluir_inativos=False, hoje=None):
    """
    Retorna alunos cujo aniversário cai no escopo informado.

    escopo:
      - 'dia'    → hoje
      - 'semana' → semana corrente (segunda a domingo) contendo `hoje`
      - 'mes'    → mês corrente

    Retorna lista de dicts: {aluno, dia, mes, data_aniversario_ano, idade_que_faz, dias_para}
    ordenada por (mes, dia) ascendente.
    """
    if hoje is None:
        hoje = date.today()
    if escopo not in ESCOPOS_ANIVERSARIO:
        escopo = 'dia'

    q = _alunos_filtro_status(Aluno.query, incluir_inativos)
    q = q.filter(Aluno.data_nascimento.isnot(None))

    if escopo == 'dia':
        q = q.filter(
            extract('month', Aluno.data_nascimento) == hoje.month,
            extract('day', Aluno.data_nascimento) == hoje.day,
        )
        intervalo = [hoje]
    elif escopo == 'semana':
        # semana corrente: segunda (weekday=0) a domingo (weekday=6)
        inicio = hoje - timedelta(days=hoje.weekday())
        fim = inicio + timedelta(days=6)
        intervalo = [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]
        # constrói OR de pares (mês, dia) — cobre o caso da semana cruzar virada de mês
        pares = {(d.month, d.day) for d in intervalo}
        q = q.filter(
            or_(*[
                and_(
                    extract('month', Aluno.data_nascimento) == m,
                    extract('day', Aluno.data_nascimento) == d,
                )
                for (m, d) in pares
            ])
        )
    else:  # 'mes'
        q = q.filter(extract('month', Aluno.data_nascimento) == hoje.month)

    alunos = q.all()

    resultado = []
    for aluno in alunos:
        nasc = aluno.data_nascimento
        try:
            aniv = nasc.replace(year=hoje.year)
        except ValueError:
            # 29/02 em ano não-bissexto → assume 28/02
            aniv = nasc.replace(year=hoje.year, day=28)
        resultado.append({
            'aluno': aluno,
            'dia': nasc.day,
            'mes': nasc.month,
            'data_aniversario_ano': aniv,
            'idade_que_faz': _idade_que_faz(nasc, hoje),
            'dias_para': (aniv - hoje).days,
        })

    resultado.sort(key=lambda r: (r['mes'], r['dia'], r['aluno'].nome.lower()))
    return resultado