# 🛒 Tasks — Profissionalização Dispensa Planejada

## FASE 1 — Refatoração Arquitetural
- [/] **1.1** Separar `index.html` monolítico em HTML/CSS/JS modulares
  - [ ] Criar estrutura de diretórios (`css/`, `js/`, `assets/`)
  - [ ] Extrair HTML semântico limpo para `index.html`
  - [ ] Extrair CSS para `css/design-system.css`, `css/components.css`, `css/layout.css`
  - [ ] Extrair JS em módulos: `dataLoader.js`, `searchEngine.js`, `shoppingList.js`, `priceCalculator.js`, `checklist.js`, `ui.js`, `app.js`
- [ ] **1.2** Design System CSS puro (substituir Tailwind CDN)
  - [ ] Definir variáveis CSS (cores, tipografia, espaçamento)
  - [ ] Google Fonts (Inter/Outfit)
  - [ ] Componentes: cards, badges, inputs, botões
  - [ ] Dark mode com toggle
  - [ ] Micro-animações (hover, skeleton loaders)
- [ ] **1.3** Backend FastAPI
  - [ ] `main.py` com endpoints de busca paginada
  - [ ] `models.py` com Pydantic models
  - [ ] `services/product_service.py` — busca e filtros
  - [ ] `services/price_service.py` — cálculo de melhor loja
  - [ ] `data/loader.py` — carrega JSONs em memória
  - [ ] `requirements.txt` + `Procfile`

## FASE 2 — UX/UI Profissional
- [ ] **2.1** Responsividade mobile-first
- [ ] **2.2** Acessibilidade WCAG 2.1 AA
- [ ] **2.3** Persistência via localStorage
- [ ] **2.4** PWA (manifest + Service Worker)
- [ ] **2.5** Features premium (WhatsApp share, badge cesta básica, economia)

## FASE 3 — Deploy e Testes
- [ ] **3.1** Deploy público (Vercel + Render)
- [ ] **3.2** Testes automatizados
- [ ] **3.3** Sessão com comunidade externa

## FASE 4 — Relatório Parcial
- [ ] **4.1** Formatar em ABNT (capa, sumário, resumo)
- [ ] **4.2** Mapear 5+ disciplinas com referências

## FASE 5 — Solução Final + Relatório Final
- [ ] **5.1** Refinamentos pós-feedback
- [ ] **5.2** Relatório Final completo

## FASE 6 — Vídeo YouTube
- [ ] **6.1** Roteiro do vídeo (5-10 min)
- [ ] **6.2** Gravação + edição
- [ ] **6.3** Upload YouTube
