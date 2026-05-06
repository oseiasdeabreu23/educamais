import re
from datetime import date
from app.models import Aluno, Nota, Frequencia, Observacao
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


def _alunos_filtro_status(query, incluir_inativos=False):
    """Aplica filtro de status='ativo' a uma query de Aluno, salvo override."""
    if incluir_inativos:
        return query
    return query.filter(Aluno.status == 'ativo')


def media_turma(turma, incluir_inativos=False):
    alunos = [a for a in turma.alunos if incluir_inativos or a.status == 'ativo']
    if not alunos:
        return 0

    soma = 0
    n = 0
    for aluno in alunos:
        for nota in aluno.notas:
            soma += nota.valor
            n += 1
    return round(soma / n, 2) if n > 0 else 0


def frequencia_geral(incluir_inativos=False):
    q = Frequencia.query
    if not incluir_inativos:
        q = q.join(Aluno, Frequencia.aluno_id == Aluno.id).filter(Aluno.status == 'ativo')
    total = q.count()
    if total == 0:
        return 0

    ausencias = q.filter(Frequencia.status == 'falta').count()
    return round((total - ausencias) / total * 100, 2)


def alunos_baixo_desempenho(limite=5.5, incluir_inativos=False):
    alunos = _alunos_filtro_status(Aluno.query, incluir_inativos).all()
    selecionados = []
    for aluno in alunos:
        media = media_aluno(aluno)
        if media and media < limite:
            selecionados.append({'aluno': aluno, 'media': media})
    return selecionados


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