export const API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
  ? 'http://localhost:8000' 
  : ''; // Use relative paths for Vercel deployment

export async function buscarProdutosAPI(texto, categoria, marca, page = 1) {
  const params = new URLSearchParams();
  if (texto) params.append('q', texto);
  if (categoria) params.append('categoria', categoria);
  if (marca) params.append('marca', marca);
  params.append('page', page);
  params.append('limit', 100);
  
  const res = await fetch(`${API_URL}/api/produtos?${params.toString()}`);
  if (!res.ok) throw new Error('Falha na busca');
  return res.json();
}

export async function buscarCategoriasAPI() {
  const res = await fetch(`${API_URL}/api/categorias`);
  if (!res.ok) throw new Error('Falha ao buscar categorias');
  return res.json();
}

export async function buscarMarcasAPI(categoria) {
  const params = new URLSearchParams();
  if (categoria) params.append('categoria', categoria);
  const res = await fetch(`${API_URL}/api/marcas?${params.toString()}`);
  if (!res.ok) throw new Error('Falha ao buscar marcas');
  return res.json();
}

export async function calcularCestaAPI(lista) {
  const reqBody = {
    itens: lista.map(item => ({
      id: item.produto.id,
      qtd: item.qtd
    }))
  };
  const res = await fetch(`${API_URL}/api/calcular`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(reqBody)
  });
  if (!res.ok) throw new Error('Falha ao calcular');
  return res.json();
}

export async function buscarProdutoPorIdAPI(id) {
  const res = await fetch(`${API_URL}/api/produtos/${id}`);
  if (!res.ok) throw new Error('Falha ao buscar produto por ID');
  return res.json();
}
