"""Backfill: liga PlanoPagamento e Mensalidade às matrículas (MatriculaTurma).

Roda em modo interativo. Para cada caso ambíguo pergunta no terminal.
Faz tudo numa transação única — commit só no fim, com confirmação. Se você
cancelar ou interromper (Ctrl+C), rollback total.

O que faz:
  1. Planos sem matricula_turma_id:
     - aluno tem 1 matrícula ativa  -> liga automaticamente
     - aluno tem >1 matrícula ativa -> pergunta qual
     - aluno só tem históricas      -> oferece a mais recente (ou pular)
     - aluno sem matrícula nenhuma  -> pula

  2. Mensalidades sem matricula_turma_id:
     - tem plano_id          -> herda do plano (que já foi backfilled)
     - sem plano             -> herda da turma_corrente do aluno
     - sem matrícula nenhuma -> pula

  3. PlanoPagamento.responsavel_id NULL:
     - copia de Mensalidade.responsavel_id (a primeira mensalidade do plano
       que tem responsável definido). Se nenhuma tem, usa aluno.responsaveis[0].

  4. MatriculaTurma.mensalidade_padrao NULL:
     - copia de aluno.mensalidade_padrao se a matrícula está ativa.

Idempotente: planos/mensalidades já com matricula_turma_id são pulados.

Uso:
    set PYTHONPATH=.
    venv\\Scripts\\python.exe scripts\\backfill_planos_matricula.py
    venv\\Scripts\\python.exe scripts\\backfill_planos_matricula.py --auto

Modo --auto: roda sem prompts. Liga matrículas automaticamente quando há só 1
ativa; planos com ambiguidade (>1 matrícula ativa) ou sem matrícula ativa são
listados em JSON no fim em vez de perguntar. Sempre commita ao final.
"""
import argparse
import json
import sys

from app import create_app, db
from app.models import (
    Aluno, MatriculaTurma, Mensalidade, PlanoPagamento, Responsavel,
)


def perguntar(msg, opcoes_validas):
    """Pergunta no terminal até receber resposta válida. opcoes_validas é set de str."""
    while True:
        resp = input(msg).strip().lower()
        if resp in opcoes_validas:
            return resp
        print(f'  resposta inválida. opções: {sorted(opcoes_validas)}')


def escolher_matricula(aluno, matriculas):
    """Mostra as matrículas e devolve a escolhida (ou None se usuário pular)."""
    print(f'\n  Aluno "{aluno.nome}" (id={aluno.id}) tem múltiplas matrículas:')
    for i, m in enumerate(matriculas, 1):
        turma_nome = m.turma.nome if m.turma else '(turma removida)'
        print(f'    {i}. Matrícula #{m.id} — turma "{turma_nome}" — '
              f'status={m.status} — desde {m.data_matricula}')
    print(f'    p. pular este plano (deixa NULL, decido depois)')

    opcoes = {str(i) for i in range(1, len(matriculas) + 1)} | {'p'}
    resp = perguntar('  escolha [1-{}/p]: '.format(len(matriculas)), opcoes)
    if resp == 'p':
        return None
    return matriculas[int(resp) - 1]


def backfill_planos(auto=False, ambiguos_acc=None):
    """Liga planos a matrículas. Em auto=True, casos ambíguos são apenas listados.

    ambiguos_acc: lista mutável onde os casos ambíguos são acumulados
    (dicts com plano_id, aluno_id, aluno_nome, opcoes=[{matricula_id, turma_nome}]).
    """
    contadores = {'ligados_auto': 0, 'ligados_manual': 0, 'pulados': 0,
                  'sem_matricula': 0, 'ja_ok': 0, 'ambiguos': 0}
    if ambiguos_acc is None:
        ambiguos_acc = []

    planos = PlanoPagamento.query.order_by(PlanoPagamento.id).all()
    for p in planos:
        if p.matricula_turma_id:
            contadores['ja_ok'] += 1
            continue

        aluno = p.aluno
        if not aluno:
            print(f'  plano #{p.id} sem aluno (?) — pulado')
            contadores['pulados'] += 1
            continue

        ativas = aluno.vinculos_ativos
        historico = aluno.vinculos_historico

        if len(ativas) == 1:
            m = ativas[0]
            p.matricula_turma_id = m.id
            print(f'  plano #{p.id} ({aluno.nome}) -> matrícula #{m.id} '
                  f'(turma "{m.turma.nome}") [auto]')
            contadores['ligados_auto'] += 1

        elif len(ativas) > 1:
            if auto:
                ambiguos_acc.append({
                    'tipo': 'plano_multiplas_ativas',
                    'plano_id': p.id,
                    'aluno_id': aluno.id,
                    'aluno_nome': aluno.nome,
                    'opcoes': [
                        {'matricula_id': m.id,
                         'turma_nome': m.turma.nome if m.turma else '?',
                         'data_matricula': str(m.data_matricula)}
                        for m in ativas
                    ],
                })
                contadores['ambiguos'] += 1
            else:
                m = escolher_matricula(aluno, ativas)
                if m is None:
                    contadores['pulados'] += 1
                else:
                    p.matricula_turma_id = m.id
                    print(f'  plano #{p.id} -> matrícula #{m.id} [manual]')
                    contadores['ligados_manual'] += 1

        elif historico:
            if auto:
                ambiguos_acc.append({
                    'tipo': 'plano_sem_ativa',
                    'plano_id': p.id,
                    'aluno_id': aluno.id,
                    'aluno_nome': aluno.nome,
                    'mais_recente': {
                        'matricula_id': historico[0].id,
                        'turma_nome': historico[0].turma.nome if historico[0].turma else '?',
                        'status': historico[0].status,
                    },
                })
                contadores['ambiguos'] += 1
            else:
                mais_recente = historico[0]
                turma_nome = mais_recente.turma.nome if mais_recente.turma else '?'
                print(f'\n  plano #{p.id} ({aluno.nome}) — aluno sem matrícula ativa.')
                print(f'    mais recente: #{mais_recente.id} turma "{turma_nome}" '
                      f'status={mais_recente.status}')
                resp = perguntar('  ligar a essa? [s/N/p=pular]: ', {'s', 'n', 'p', ''})
                if resp == 's':
                    p.matricula_turma_id = mais_recente.id
                    contadores['ligados_manual'] += 1
                else:
                    contadores['pulados'] += 1

        else:
            print(f'  plano #{p.id} ({aluno.nome}) — aluno sem matrícula nenhuma '
                  f'— pulado')
            contadores['sem_matricula'] += 1

    return contadores


def backfill_mensalidades():
    """Liga Mensalidade.matricula_turma_id usando o plano ou a turma_corrente."""
    contadores = {'via_plano': 0, 'via_turma_corrente': 0, 'pulados': 0, 'ja_ok': 0}

    mensalidades = Mensalidade.query.order_by(Mensalidade.id).all()
    for m in mensalidades:
        if m.matricula_turma_id:
            contadores['ja_ok'] += 1
            continue

        # 1. Tem plano? Herda do plano (que já foi backfilled).
        if m.plano_id and m.plano and m.plano.matricula_turma_id:
            m.matricula_turma_id = m.plano.matricula_turma_id
            contadores['via_plano'] += 1
            continue

        # 2. Sem plano — herda da turma_corrente do aluno (se houver matrícula ativa).
        aluno = m.aluno if hasattr(m, 'aluno') else Aluno.query.get(m.aluno_id)
        if aluno:
            ativas = aluno.vinculos_ativos
            if len(ativas) == 1:
                m.matricula_turma_id = ativas[0].id
                contadores['via_turma_corrente'] += 1
                continue

        contadores['pulados'] += 1

    return contadores


def backfill_responsavel_planos():
    """PlanoPagamento.responsavel_id NULL: copia da primeira Mensalidade do plano,
    ou de aluno.responsaveis[0]."""
    contadores = {'preenchidos': 0, 'sem_responsavel': 0, 'ja_ok': 0}

    planos = PlanoPagamento.query.order_by(PlanoPagamento.id).all()
    for p in planos:
        if p.responsavel_id:
            contadores['ja_ok'] += 1
            continue

        # Tenta da primeira mensalidade
        resp_id = None
        for mens in p.mensalidades:
            if mens.responsavel_id:
                resp_id = mens.responsavel_id
                break

        # Senão, do aluno
        if not resp_id and p.aluno and p.aluno.responsaveis:
            resp_id = p.aluno.responsaveis[0].id

        if resp_id:
            p.responsavel_id = resp_id
            contadores['preenchidos'] += 1
        else:
            contadores['sem_responsavel'] += 1

    return contadores


def backfill_mensalidade_padrao_matricula():
    """MatriculaTurma.mensalidade_padrao NULL: copia de aluno.mensalidade_padrao
    para cada matrícula ativa do aluno (matrículas encerradas ignoradas)."""
    contadores = {'preenchidos': 0, 'sem_valor': 0, 'ja_ok': 0, 'nao_ativa': 0}

    matriculas = MatriculaTurma.query.order_by(MatriculaTurma.id).all()
    for mat in matriculas:
        if mat.mensalidade_padrao is not None:
            contadores['ja_ok'] += 1
            continue
        if mat.status != 'ativo':
            contadores['nao_ativa'] += 1
            continue

        aluno = mat.aluno
        if aluno and aluno.mensalidade_padrao is not None:
            mat.mensalidade_padrao = aluno.mensalidade_padrao
            contadores['preenchidos'] += 1
        else:
            contadores['sem_valor'] += 1

    return contadores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--auto', action='store_true',
                        help='Não-interativo: liga só casos não-ambíguos, '
                             'imprime ambíguos como JSON e commita.')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print('=' * 70)
        print(f'Backfill de planos/mensalidades por matrícula (modo={"auto" if args.auto else "interativo"})')
        print('=' * 70)

        total_planos = PlanoPagamento.query.count()
        total_mens = Mensalidade.query.count()
        total_mat = MatriculaTurma.query.count()
        print(f'\nTotais atuais: {total_planos} planos · {total_mens} mensalidades · '
              f'{total_mat} matrículas')

        ambiguos = []
        try:
            print('\n[1/4] Ligando planos a matrículas...')
            c_planos = backfill_planos(auto=args.auto, ambiguos_acc=ambiguos)
            print(f'  resumo: {c_planos}')

            print('\n[2/4] Ligando mensalidades a matrículas...')
            c_mens = backfill_mensalidades()
            print(f'  resumo: {c_mens}')

            print('\n[3/4] Preenchendo PlanoPagamento.responsavel_id...')
            c_resp = backfill_responsavel_planos()
            print(f'  resumo: {c_resp}')

            print('\n[4/4] Preenchendo MatriculaTurma.mensalidade_padrao...')
            c_pad = backfill_mensalidade_padrao_matricula()
            print(f'  resumo: {c_pad}')

            print('\n' + '=' * 70)
            if args.auto:
                db.session.commit()
                print('[OK] Commit feito (modo auto).')
                if ambiguos:
                    print(f'\n[!] {len(ambiguos)} caso(s) ambiguo(s) ficaram com '
                          f'matricula_turma_id=NULL e precisam de decisao manual:')
                    print('--- AMBIGUOS_JSON_BEGIN ---')
                    print(json.dumps(ambiguos, ensure_ascii=False, indent=2))
                    print('--- AMBIGUOS_JSON_END ---')
            else:
                print('TUDO PRONTO -- nada foi commitado ainda.')
                print('=' * 70)
                resp = perguntar('\nConfirmar commit? [s/N]: ', {'s', 'n', ''})
                if resp == 's':
                    db.session.commit()
                    print('\n[OK] Commit feito. Backfill aplicado.')
                else:
                    db.session.rollback()
                    print('\n[X] Rollback. Nada foi alterado no banco.')

        except KeyboardInterrupt:
            db.session.rollback()
            print('\n\n[!] Interrompido. Rollback executado.')
        except Exception as e:
            db.session.rollback()
            print(f'\n\n[ERRO] {e!r}. Rollback executado.')
            raise


if __name__ == '__main__':
    main()
