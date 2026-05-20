# Design system

Tokens, componentes e padrões visuais. Tudo em [app/static/css/style.css](../app/static/css/style.css).

## Tokens (CSS custom properties)

Light é o default; dark é ativado via `data-theme="dark"` no `<html>` (toggle no topbar
persiste em `localStorage` com a chave `arvorecer-theme`).

- **Brand:** azul `--brand-500: #3b82f6` (light usa `--primary: #2563eb`, dark usa `#3b82f6`).
- **Texto:** `--text` (principal), `--text-2` (secundário), `--text-3` (legendas/dim).
  No dark, `--text-3` é `#9ba5c4` (passa WCAG AA — não baixar).
- **Surface:** `--bg`, `--bg-2` (sidebar/topbar), `--surface` (card), `--surface-2`/`--surface-3`
  (hover/nested).
- **Score:** `--score-ok-bg/fg`, `--score-warn-bg/fg`, `--score-bad-bg/fg`. No dark os bg
  são `rgba(...,.22-.24)` + borda colorida (definida em regras `[data-theme="dark"]`)
  pra dar forma sobre o surface escuro.
- **Tipografia:** Sora (Google Fonts) em `--font-display` e `--font-body`.
- **Radius:** `--r-sm 8`, `--r-md 12`, `--r-lg 18` (cards), `--r-xl 24` (sidebar/topbar).
- **Aliases legados:** `--success`, `--danger`, `--warning`, `--text-primary`, `--text-muted`,
  `--card-bg`, etc. apontam pros tokens novos — preservados pra não quebrar templates antigos.

## Componentes principais

- **`.app-shell`** (no `<body class="app">`): grid de duas colunas — sidebar 248px + main.
- **`.sidebar`** flutuante com `border-radius` 24, fundo `--bg-2`, sticky. No mobile
  (<980px) vira drawer com `transform: translateX(-100%)` controlado por `.drawer-open` no body.
- **`.topbar`** com título + subtítulo, busca e botões de ícone (notificações + toggle de tema).
- **`.kpi`** com 6 variantes (`.kpi-blue`, `.kpi-cyan`, `.kpi-violet`, `.kpi-emerald`,
  `.kpi-amber`, `.kpi-rose`, `.kpi-soft`). Usadas em todos os dashboards.
- **`.score`** + `.score-ok/warn/bad` (notas e médias). Sempre com `font-variant-numeric: tabular-nums`.
- **`.badge`** pill (default + variantes `.badge-ok/warn/bad/info/primary`). Aliases pras
  classes do Bootstrap (`.bg-success`, `.bg-danger`, etc.) mapeiam pra `.badge-ok/bad`.
- **`.donut`** CSS-only via `conic-gradient` (usado no dashboard do responsável).
- **`.quick-action`** botão de ação rápida com ícone colorido + título + sub.
- **`.empty-state`** padrão pra "sem dados ainda".

## Sobrescritas obrigatórias do Bootstrap

Carregamos o Bootstrap 5.3 (modal, accordion, dropdown, grid, utilities) mas vários
utilities forçam cores claras com `!important`. As sobrescritas estão em `style.css`:

- `--bs-table-bg: transparent` e `--bs-table-hover-bg: var(--surface-2)` na `.table`
  (Bootstrap pinta cada `<td>` via box-shadow inset).
- `.bg-light` → `var(--surface-2)` / `.bg-white` → `var(--surface)`.
- `.table-light` (em `<thead>` ou `<tr>`) → mapeada pros tokens **e** com `box-shadow inset`
  pra vencer o truque do Bootstrap.
- `.text-dark`/`.text-light` em dark mode → `var(--text)` (senão badges com texto preto
  forçado ficam ilegíveis sobre fundo escuro).
- `.modal-content`, `.accordion-item`, `.accordion-button`, `.list-group-item`,
  `.breadcrumb-item`, `.alert.*` — todos restilizados pra usar tokens.

## Padrões de UI

- **Empty state**: ícone Bootstrap-Icons grande + opacidade 0.35 + mensagem dim centralizada.
- **Score colorido por faixa**: <5 = bad (vermelho), 5–6.9 = warn (amarelo), ≥7 = ok (verde).
- **CRUD admin**: form à esquerda (col-lg-4) + tabela à direita (col-lg-8) com modal de edição.
- **Breadcrumb**: usar Bootstrap markup (`<nav><ol class="breadcrumb">...`) — CSS já restilizado.
- **Forms**: usar `.input`, `.label`, `.select` (estilizados via tokens).
  `.form-control`/`.form-select`/`.form-label` do Bootstrap também funcionam (mesmo estilo).
- **Tema dark/light**: respeite os tokens — **nunca hardcode cores hex em templates novos**.
  Para cores semânticas use `var(--ok|warn|bad|primary)`. Para texto use `var(--text|text-2|text-3)`.

## Ícones

Usamos **Bootstrap Icons** (não os ícones Lucide do design original). Mapeamentos comuns:
`bi-tree-fill` (brand), `bi-grid-fill` (dashboard), `bi-people-fill` (turmas),
`bi-mortarboard-fill` (professores), `bi-play-btn-fill` (cursos), `bi-pencil-fill` (notas),
`bi-check-circle-fill` (frequência), `bi-clipboard-fill` (atividades), `bi-bell-fill`
(notificações), `bi-moon-stars-fill`/`bi-sun-fill` (toggle tema).
