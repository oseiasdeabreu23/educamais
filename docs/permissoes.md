# Permissões e RBAC

RBAC com matriz padrão por papel **+** snapshot customizado por usuário.
Implementação em [app/permissoes.py](../app/permissoes.py) (matriz, catálogo,
`pode()`, `requires`), [app/services_permissoes.py](../app/services_permissoes.py)
(snapshot/save/restore) e [app/models.py](../app/models.py) (`UsuarioPermissao` +
`User.permissoes_customizadas`). UI de edição em
[app/templates/admin_usuario_permissoes.html](../app/templates/admin_usuario_permissoes.html).

## Papéis existentes

| Papel | Resumo |
|---|---|
| `admin` | Wildcard `*` — tudo. **Imutável**: não pode ser customizado nem perder permissões. |
| `coordenador` | Cadastra alunos/profs/responsáveis (sem editar/excluir), matrícula, financeiro básico, relatórios. |
| `gestor` | Só leitura — dashboards, relatórios, financeiro. |
| `secretario` | Cadastra **e edita** alunos/responsáveis/profs/turmas, financeiro do dia-a-dia (gera mensalidades, emite/sincroniza boletos, registra pagamento manual, lança movimentação). **Não exclui, não cancela**. |
| `professor`, `responsavel`, `aluno` | Não usam a matriz. UI própria em blueprints separadas. |

`ROLES_ADMIN_LIKE = {'admin', 'coordenador', 'gestor', 'secretario'}` — papéis que
usam o painel `/admin/*` e são redirecionados pra `admin.dashboard` no login.

## Catálogo de permissões

`PERMISSOES_CATALOGO` é a fonte da verdade pra UI de customização. Cada permissão
tem chave (`recurso.acao`) e label legível, agrupadas por área temática.

**45 chaves em 13 grupos** (2026-05-20): alunos/professores/responsáveis/turmas/
disciplinas/cursos (ver/criar/editar/excluir), matrículas, aniversariantes,
dashboard, relatórios (ver/exportar), financeiro (leitura/mensalidades+boletos/
fluxo), administração (usuários/configuração/backup/avisos).

Pra adicionar uma chave nova:
1. Adiciona no `PERMISSOES_CATALOGO` (grupo + chave + label).
2. Inclui nos sets dos papéis que devem tê-la por padrão.
3. Usa `@requires('nova.chave')` na rota / `{% if pode('nova.chave') %}` no template.

## Customização por usuário

Modelo de **snapshot persistido**:

1. Usuário criado herda o set padrão do papel. `permissoes_customizadas = False`.
2. Admin clica "Personalizar permissões" em `/admin/usuarios/<id>/permissoes`:
   - `snapshot_permissoes_papel(user)` copia o set do papel pra
     `usuario_permissao` (tabela de junção (user_id, chave)).
   - `permissoes_customizadas = True`.
3. Admin marca/desmarca checkboxes e salva. `salvar_permissoes_customizadas(user, chaves)`
   substitui todas as linhas em `usuario_permissao` pelo novo set.
4. Pra voltar ao default: "Restaurar padrão do papel" →
   `restaurar_padrao_papel(user)` apaga as linhas e seta a flag de volta pra `False`.

A partir daí, `pode(user, acao)` consulta o snapshot quando a flag tá ligada e
o set padrão do papel quando tá desligada.

### Avaliação no `pode()`

Ordem:
1. **Admin** sempre retorna `True` (independente da customização — proteção do
   "último admin").
2. Se `permissoes_customizadas == True` → consulta `UsuarioPermissao` (modelo
   aditivo: ausência = negada). Cache no objeto user evita N queries por request.
3. Senão → consulta o set padrão do papel em `PERMISSOES`.

### Quando o papel default muda depois da customização

Usuário com `permissoes_customizadas=True` **não recebe** mudanças no default
do papel. Pra propagar, admin precisa "Restaurar padrão" e personalizar de novo
(ou apenas restaurar). Decisão consciente — customização significa "este
usuário em particular tem regras próprias".

## Proteções

- **Admin imutável**: `services_permissoes._validar_alvo()` levanta
  `PermissoesError` ao tentar customizar admin. UI esconde botão "Permissões".
- **Self-protection**: rota `/usuarios/<id>/permissoes` redireciona se
  `user.id == current_user.id`. UI esconde botão na própria linha.
- **Restrição a admin-like**: rota rejeita se `user.tipo not in ROLES_ADMIN_LIKE`.
  Customizar professor/responsável/aluno seria confuso porque eles usam
  blueprints próprias com decorators próprios — a matriz não vale pra eles.
- **Cascade na exclusão**: FK `usuario_permissao.user_id → usuarios.id` é
  `ON DELETE CASCADE`. Excluir um usuário remove suas permissões automaticamente.

## Decorators e helpers

- **Rota**: `@requires('aluno.criar')` → 403 se faltar. Usado em rotas
  admin/coordenador/gestor/secretário.
- **Rota estritamente admin** (raras — ferramentas de dev do Cora): mantém
  `@admin_required` legacy.
- **Rota com GET listagem + POST criação**: decorator com `.ver` no topo +
  `if not pode(current_user, 'X.criar'): abort(403)` dentro do POST.
- **Template**: `{% if pode('aluno.editar') %}…{% endif %}`. `pode` é injetado
  em todo template via context processor (`inject_permissoes()` em
  `app/__init__.py`).

## Adicionar um papel novo

1. Adiciona em `PERMISSOES` com o set apropriado.
2. Adiciona label em `ROLES_LABEL`.
3. Inclui em `ROLES_ADMIN_LIKE` se usa o painel `/admin/*`.
4. Inclui em `ROLES_CRIAVEIS_ADMIN` se admin deve poder criar via `/admin/usuarios`.
5. Adiciona botão "Criar acesso de X" em `admin_usuarios.html` e badge na lista.
6. Inclui no condicional do botão "Permissões" no `admin_usuarios.html` se
   esse papel também deve aceitar customização individual.
7. (Sem migration — `User.tipo` é `String(20)` e aceita qualquer valor.)
