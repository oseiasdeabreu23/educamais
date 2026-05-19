"""Estatísticas pra a página /admin/relatorios.

Funções puras (sem render) que consolidam contagens de Aluno e
MatriculaTurma em estruturas simples — dicts e listas de tuplas — pra
serem consumidas tanto pelos templates Jinja quanto pelo gerador de PDF
em ``services_export``.

Conceitos:
- "status do aluno" = status derivado (property em Aluno.status_derivado).
- "matrícula encerrada" = matrículas com status em
  ('formado', 'evadido', 'transferido'). Saídas são datadas pelo
  campo ``data_saida``.
- Período: tupla ``(data_inicio, data_fim)`` ou None. Quando setado,
  filtra fatos pela ``data_saida`` (pra histórico) ou ``data_matricula``
  (pra novas entradas).
"""
from datetime import date
from sqlalchemy import func, extract

from app import db
from app.models import Aluno, Turma, MatriculaTurma


STATUS_ENCERRADOS = ('formado', 'evadido', 'transferido')


# --------------------------------------------------------------------- #
# KPIs gerais
# --------------------------------------------------------------------- #

def kpis_status_alunos():
    """Contagem atual por status derivado, considerando todos os alunos.

    Retorna dict com:
        - ativos, formados, evadidos, transferidos, sem_vinculo
        - total
        - taxa_evasao (percentual, 0-100)
    """
    alunos = Aluno.query.all()
    cont = {'ativo': 0, 'formado': 0, 'evadido': 0,
            'transferido': 0, 'sem_vinculo': 0}
    for a in alunos:
        st = a.status_derivado
        if st not in cont:
            cont[st] = 0
        cont[st] += 1

    base = (cont['ativo'] + cont['formado']
            + cont['evadido'] + cont['transferido'])
    taxa_evasao = round((cont['evadido'] / base) * 100, 1) if base else 0.0

    return {
        'ativos':       cont['ativo'],
        'formados':     cont['formado'],
        'evadidos':     cont['evadido'],
        'transferidos': cont['transferido'],
        'sem_vinculo':  cont['sem_vinculo'],
        'total':        len(alunos),
        'taxa_evasao':  taxa_evasao,
    }


# --------------------------------------------------------------------- #
# Distribuição por turma
# --------------------------------------------------------------------- #

def distribuicao_por_turma():
    """Contagem de matrículas por turma e status.

    Retorna lista ordenada por nome da turma:
        [
          {turma: Turma, ativos, formados, evadidos, transferidos, total},
          ...
        ]
    """
    rows = (db.session.query(
                MatriculaTurma.turma_id,
                MatriculaTurma.status,
                func.count(MatriculaTurma.id),
            )
            .group_by(MatriculaTurma.turma_id, MatriculaTurma.status)
            .all())

    por_turma = {}
    for turma_id, status, count in rows:
        por_turma.setdefault(turma_id, {
            'ativo': 0, 'formado': 0, 'evadido': 0, 'transferido': 0,
        })
        if status in por_turma[turma_id]:
            por_turma[turma_id][status] += count

    resultado = []
    for t in Turma.query.order_by(Turma.nome).all():
        c = por_turma.get(t.id, {
            'ativo': 0, 'formado': 0, 'evadido': 0, 'transferido': 0,
        })
        total = c['ativo'] + c['formado'] + c['evadido'] + c['transferido']
        if total == 0:
            continue
        resultado.append({
            'turma':        t,
            'ativos':       c['ativo'],
            'formados':     c['formado'],
            'evadidos':     c['evadido'],
            'transferidos': c['transferido'],
            'total':        total,
        })
    return resultado


# --------------------------------------------------------------------- #
# Histórico anual (saídas)
# --------------------------------------------------------------------- #

def historico_anual(ano_inicio=None, ano_fim=None):
    """Saídas (formados/evadidos/transferidos) por ano de data_saida.

    Retorna lista ordenada por ano ascendente:
        [{ano, formados, evadidos, transferidos}, ...]

    Se ``ano_inicio`` / ``ano_fim`` forem None, usa min/max disponível.
    Sempre preenche TODOS os anos do intervalo (mesmo zerados) pra o
    gráfico ficar contínuo.
    """
    ano_col = extract('year', MatriculaTurma.data_saida).label('ano')
    q = (db.session.query(
            ano_col,
            MatriculaTurma.status,
            func.count(MatriculaTurma.id),
         )
         .filter(MatriculaTurma.data_saida.isnot(None))
         .filter(MatriculaTurma.status.in_(STATUS_ENCERRADOS))
         .group_by(ano_col, MatriculaTurma.status))

    bruto = {}
    for ano_val, status, count in q.all():
        if ano_val is None:
            continue
        ano = int(ano_val)
        bruto.setdefault(ano, {'formado': 0, 'evadido': 0, 'transferido': 0})
        if status in bruto[ano]:
            bruto[ano][status] += count

    if not bruto:
        return []

    anos_disp = sorted(bruto.keys())
    ai = ano_inicio if ano_inicio is not None else anos_disp[0]
    af = ano_fim if ano_fim is not None else anos_disp[-1]
    if ai > af:
        ai, af = af, ai

    resultado = []
    for ano in range(ai, af + 1):
        c = bruto.get(ano, {'formado': 0, 'evadido': 0, 'transferido': 0})
        resultado.append({
            'ano':          ano,
            'formados':     c['formado'],
            'evadidos':     c['evadido'],
            'transferidos': c['transferido'],
        })
    return resultado


# --------------------------------------------------------------------- #
# Snapshot completo (usado pela view e pelo PDF)
# --------------------------------------------------------------------- #

def snapshot_completo(turma_id=None):
    """Junta tudo num único payload. Se ``turma_id`` for setado, restringe
    a distribuição_por_turma àquela turma (KPIs e histórico continuam
    globais — eles fazem mais sentido sem filtro de turma).
    """
    kpis = kpis_status_alunos()
    dist = distribuicao_por_turma()
    if turma_id:
        dist = [d for d in dist if d['turma'].id == turma_id]
    hist = historico_anual()

    return {
        'kpis':        kpis,
        'por_turma':   dist,
        'historico':   hist,
        'gerado_em':   date.today(),
    }
