/* ================================================================
   dataLoader.js — Configurações e Logos Oficiais das Lojas
   Dispensa Planejada Santos
   ================================================================ */

export const SVG_LOGOS = {
  carrefour: `<svg viewBox="0 0 51 34" fill="none" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%"><path clip-rule="evenodd" d="M25.6339 0C20.2716 0 18.1768 7.68829 18.1768 16.8493C18.1768 26.0149 20.2716 33.6 25.6339 33.6C28.853 33.6 31.5961 31.6929 31.6058 30.1262C31.6058 29.7839 31.476 29.4567 31.1919 29.1694C29.6672 27.6797 29.0719 26.1893 29.0641 24.8746C29.0564 22.3641 31.2099 20.4956 33.1924 20.4956C35.922 20.4956 37.5305 22.6645 37.5305 25.4722C37.5305 28.1329 36.4082 30.3521 35.1903 32.126C35.1419 32.1984 35.1213 32.2788 35.1213 32.35C35.1213 32.4871 35.202 32.6027 35.324 32.6027C35.3989 32.6027 35.4848 32.5629 35.5778 32.4682L49.2793 19.0685C49.9619 18.4775 50.3997 17.7865 50.3997 16.8023C50.3997 15.8155 49.9619 15.1245 49.2793 14.5373L35.5778 1.13313C35.4848 1.04104 35.3989 0.999242 35.324 0.999242C35.1994 0.999242 35.1213 1.11549 35.1213 1.2546C35.1213 1.32644 35.1419 1.40678 35.1903 1.48058C36.4082 3.25309 37.5305 5.47232 37.5305 8.12978C37.5305 10.9368 35.922 13.1097 33.1924 13.1097C31.2099 13.1097 29.0564 11.2385 29.0641 8.72802C29.0719 7.41594 29.6672 5.92426 31.1919 4.4352C31.476 4.14653 31.6058 3.82063 31.6058 3.4771C31.5961 1.90901 28.853 0 25.6339 0Z" fill="#1E5BC6" fill-rule="evenodd"/><path clip-rule="evenodd" d="M14.4233 0.960248C14.5075 0.874123 14.5905 0.839417 14.6609 0.839417C14.7872 0.839417 14.8752 0.953821 14.8721 1.09329C14.8677 1.17684 14.8325 1.26747 14.7526 1.34845C11.6253 5.3256 9.34947 9.97696 9.34947 16.4267C9.34947 22.8738 11.6253 27.4332 14.7526 31.4097C14.8325 31.4901 14.8677 31.5858 14.8721 31.6655C14.8752 31.8057 14.7872 31.9194 14.6609 31.9194C14.5905 31.9194 14.5075 31.8854 14.4233 31.7973L1.08981 18.6106C0.424862 18.029 0 17.3496 0 16.3804C0 15.4092 0.424862 14.7292 1.08981 14.1514L14.4233 0.960248Z" fill="#ED1C24" fill-rule="evenodd"/></svg>`,
  
  pao_de_acucar: `<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%"><path d="M20 3C11.5 3 5 9.5 5 18C5 26.5 12 34 20 37C28 34 35 26.5 35 18C35 9.5 28.5 3 20 3Z" fill="#007A33"/><path d="M20 7.5C13.5 7.5 8.5 12.5 8.5 19C8.5 25.5 14 31.5 20 34C26 31.5 31.5 25.5 31.5 19C31.5 12.5 26.5 7.5 20 7.5Z" fill="#70B836"/><path d="M20 12C15.5 12 12 15.5 12 20C12 24.5 16 28.5 20 30.5C24 28.5 28 24.5 28 20C28 15.5 24.5 12 20 12Z" fill="#005A26"/><path d="M20 16.5C17.5 16.5 15.5 18.5 15.5 21C15.5 23.5 18 25.5 20 27C22 25.5 24.5 23.5 24.5 21C24.5 18.5 22.5 16.5 20 16.5Z" fill="#FFFFFF"/></svg>`,
  
  atacadao: `<svg viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%"><circle cx="22" cy="22" r="21" fill="#E31B23" stroke="#F37021" stroke-width="2"/><circle cx="22" cy="22" r="18" fill="#E31B23"/><path d="M12 32L20.5 10H23.5L32 32H27.5L25.8 27H18.2L16.5 32H12ZM19.5 23H24.5L22 15.5L19.5 23Z" fill="#FFFFFF"/><path d="M7 23C7 23 14 26 22 26C30 26 37 23 37 23" stroke="#003366" stroke-width="3" stroke-linecap="round"/></svg>`,
  
  soudaki: `<svg viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg" style="width:100%;height:100%"><rect width="44" height="44" rx="10" fill="#7C3AED"/><path d="M24 7L12 23H21L19 37L32 19H23L24 7Z" fill="#FBBF24"/></svg>`
};

export const LOJAS = {
  carrefour: {
    nome: 'Carrefour - Ponta da Praia',
    cor: '#2563eb',
    logoSvg: SVG_LOGOS.carrefour
  },
  pao_de_acucar: {
    nome: 'Pão de Açúcar',
    cor: '#007A33',
    logoSvg: SVG_LOGOS.pao_de_acucar
  },
  atacadao: {
    nome: 'Atacadão',
    cor: '#E31B23',
    logoSvg: SVG_LOGOS.atacadao
  },
  soudaki: {
    nome: 'Soudaki',
    cor: '#7c3aed',
    logoSvg: SVG_LOGOS.soudaki
  }
};

export function renderStoreLogo(chave, size = 16, extraClass = '') {
  const loja = LOJAS[chave];
  const svg = SVG_LOGOS[chave];
  const title = loja ? loja.nome : chave;
  if (!svg) return '';
  return `<span class="store-logo-icon store-logo-${chave} ${extraClass}" style="width:${size}px;height:${size}px;" title="${title}" aria-label="${title}">${svg}</span>`;
}

// Retrocompatibilidade para quem lê LOJAS[chave].icone
for (const chave of Object.keys(LOJAS)) {
  LOJAS[chave].icone = renderStoreLogo(chave, 16);
}

export const CHAVES_LOJA = ['carrefour', 'pao_de_acucar', 'atacadao', 'soudaki'];
