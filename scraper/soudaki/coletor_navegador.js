/* Coletor do Soudaki que roda no navegador.
 *
 * Serve para quem não tem Python na máquina. O navegador já tem tudo o
 * que falta do lado de cá: o IP brasileiro, os cookies da sessão e a
 * aprovação do desafio do Cloudflare. Então ele faz só o transporte —
 * baixa o conteúdo de cada seção e salva num arquivo. Toda a lógica de
 * leitura (EAN, preço, marca) continua no Python já testado.
 *
 * COMO USAR
 *   1. Abra  https://soudaki.com/shop/laticinios/  e espere carregar.
 *   2. Tecle F12 e vá na aba "Console".
 *   3. Se o Chrome pedir, digite  allow pasting  e tecle Enter.
 *   4. Cole TODO este arquivo e tecle Enter.
 *   5. Espere. Ele avisa o progresso e baixa  soudaki_navegador.json.
 *   6. Mande esse arquivo para o repositório.
 *
 * Para pegar só algumas seções:
 *   coletarSoudaki(["laticinios", "bebidas"])
 */

(() => {
  const SECOES = [
    "hortifruti", "bebidas", "laticinios", "padaria", "matinais",
    "saudaveis", "mercearia", "molhos-e-conservas", "acougue-e-peixaria",
    "churrasco", "congelados", "pratico-e-rapido", "biscoitos-e-salgadinhos",
    "chocolates-e-doces", "sorvetes-e-acai", "cervejas-e-drinks",
    "vinhos-e-espumantes", "destilados", "limpeza", "higiene-e-beleza",
    "utilidades", "pets", "bebe", "produtos-daki", "farmacia",
  ];

  const PAUSA_MS = 900;          // gentileza com o site
  const RE_NEXT = /<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/;

  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

  /* Conta produtos para dar um retorno honesto no console.
   * A página traz parte em preloadedProducts e parte no cache do Apollo,
   * e o mesmo item pode estar nos dois. Por isso conta identificadores
   * únicos, não ocorrências. O que vale mesmo é o __NEXT_DATA__ inteiro,
   * que vai salvo inteiro — o Python é quem extrai de verdade. */
  function contar(textoJson) {
    let d;
    try {
      d = JSON.parse(textoJson);
    } catch (e) {
      return (textoJson.match(/"__typename":"Product"/g) || []).length;
    }
    const ids = new Set();

    const pre = d?.props?.pageProps?.preloadedProducts;
    const listas = Array.isArray(pre) ? [pre]
      : (pre && typeof pre === "object" ? Object.values(pre) : []);
    listas.forEach((lista) => {
      if (!Array.isArray(lista)) return;
      lista.forEach((p) => {
        if (p && typeof p === "object") {
          ids.add(String(p.sku ?? p.id ?? p.name ?? JSON.stringify(p).slice(0, 60)));
        }
      });
    });

    const apollo = d?.props?.pageProps?.__APOLLO_STATE__
      ?? d?.props?.__APOLLO_STATE__;
    if (apollo && typeof apollo === "object") {
      Object.keys(apollo).forEach((k) => {
        if (/^Product[:.]/i.test(k)) ids.add(k.replace(/^Product[:.]/i, ""));
      });
    }
    return ids.size;
  }

  function ehBloqueio(html) {
    if (!html) return true;
    if (html.includes("__NEXT_DATA__")) return false;
    const a = html.slice(0, 4000).toLowerCase();
    return a.includes("page not found")
      || a.includes("doesn't exist or has been moved")
      || a.includes("challenges.cloudflare.com")
      || a.includes("just a moment");
  }

  /* Descobre seções a partir dos links da página, caso a lista mude. */
  function descobrir() {
    const achadas = new Set();
    document.querySelectorAll('a[href*="/shop/"]').forEach((a) => {
      const m = (a.getAttribute("href") || "").match(/\/shop\/([a-z0-9-]+)\/?$/i);
      if (m && m[1] !== "search") achadas.add(m[1].toLowerCase());
    });
    return [...achadas];
  }

  function baixarArquivo(obj, nome) {
    const blob = new Blob([JSON.stringify(obj)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  async function coletarSoudaki(lista) {
    const doLink = descobrir();
    const secoes = lista || [...new Set([...SECOES, ...doLink])];

    console.log(`%cColetor Soudaki`, "font-weight:bold;font-size:14px");
    console.log(`${secoes.length} seções a visitar`
      + (doLink.length ? ` (${doLink.length} vieram dos links da página)` : ""));

    const resultado = {
      coletado_em: new Date().toISOString(),
      origem: location.origin,
      agente: navigator.userAgent,
      secoes: {},
    };
    let totalProdutos = 0;
    const falhas = [];

    for (let i = 0; i < secoes.length; i++) {
      const secao = secoes[i];
      const url = `${location.origin}/shop/${secao}/`;
      const rotulo = `[${String(i + 1).padStart(2)}/${secoes.length}] ${secao}`;
      try {
        const r = await fetch(url, {
          credentials: "include",
          headers: { "Accept": "text/html" },
        });
        const html = await r.text();

        if (ehBloqueio(html)) {
          console.warn(`${rotulo}: bloqueado ou inexistente (HTTP ${r.status})`);
          falhas.push(secao);
        } else {
          const m = html.match(RE_NEXT);
          if (!m) {
            console.warn(`${rotulo}: sem __NEXT_DATA__`);
            falhas.push(secao);
          } else {
            const n = contar(m[1]);
            resultado.secoes[secao] = m[1];
            totalProdutos += n;
            console.log(`${rotulo}: ${n} produtos`);
          }
        }
      } catch (e) {
        console.warn(`${rotulo}: ${e.name} ${e.message}`);
        falhas.push(secao);
      }
      await dormir(PAUSA_MS);
    }

    const ok = Object.keys(resultado.secoes).length;
    console.log(`\n%cPronto: ${totalProdutos} produtos em ${ok} seções`,
      "font-weight:bold;color:green");
    if (falhas.length) console.log(`Sem dados: ${falhas.join(", ")}`);

    if (!ok) {
      console.error("Nada coletado. Confirme que a loja está aberta nesta aba.");
      return resultado;
    }

    baixarArquivo(resultado, "soudaki_navegador.json");
    console.log("Arquivo soudaki_navegador.json baixado. "
      + "Mande-o para o repositório.");
    return resultado;
  }

  window.coletarSoudaki = coletarSoudaki;
  coletarSoudaki();
})();
