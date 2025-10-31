import streamlit as st
import requests
import unicodedata
import re
import json
import os
from urllib.parse import urlparse
# Importações necessárias para a busca assíncrona do Shibata
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Constantes NAGUMO ---

LOGO_NAGUMO_URL = "https://rawcdn.githack.com/gymbr/precosmercados/main/logo-nagumo2.png"
DEFAULT_IMAGE_URL = "https://rawcdn.githack.com/gymbr/precosmercados/main/sem-imagem.png"

NAGUMO_API_URL = "https://nextgentheadless.instaleap.io/api/v3"
NAGUMO_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.nagumo.com",
    "Referer": "https://www.nagumo.com/",
    "User-Agent": "Mozilla/5.0",
    "apollographql-client-name": "Ecommerce SSR",
    "apollographql-client-version": "0.11.0"
}
NAGUMO_QUERY = """
query SearchProducts($searchProductsInput: SearchProductsInput!) {
  searchProducts(searchProductsInput: $searchProductsInput) {
    products {
      name
      price
      photosUrl
      sku
      stock
      description
      unit
      promotion {
        isActive
        type
        conditions {
          price
          priceBeforeTaxes
        }
      }
    }
  }
}
"""
# --- Constantes SHIBATA (Copiadas de main (1).py) ---

LOGO_SHIBATA_URL = "https://rawcdn.githack.com/gymbr/precosmercados/main/logo-shibata.png" 

# TOKEN atualizado no anexo. O ideal é que o usuário obtenha um token fresco.
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJ2aXBjb21tZXJjZSIsImF1ZCI6ImFwaS1hZG1pbiIsInN1YiI6IjZiYzQ4NjdlLWRjYTktMTFlOS04NzQyLTAyMGQ3OTM1OWNhMCIsInZpcGNvbW1lcmNlQ2xpZW50ZUlkIjpudWxsLCJpYXQiOjE3NTE5MjQ5MjgsInZlciI6MSwiY2xpZW50IjpudWxsLCJvcGVyYXRvciI6bnVsbCwib3JnIjoiMTYxIn0.yDCjqkeJv7D3wJ0T_fu3AaKlX9s5PQYXD19cESWpH-jF_Is-Zb-bDdUvduwoI_RkOeqbYCuxN0ppQQXb1ArVg"
ORG_ID = "161"
HEADERS_SHIBATA = {
    "Authorization": f"Bearer {TOKEN}",
    "organizationid": ORG_ID,
    "sessao-id": "4ea572793a132ad95d7e758a4eaf6b09",
    "domainkey": "loja.shibata.com.br",
    "User-Agent": "Mozilla/5.0"
}

# Nome do arquivo JSON
JSON_FILE = "itens.json"

# --- Funções de Leitura/Criação do JSON ---

def criar_json_padrao():
    """Cria o arquivo itens.json padrão com a estrutura VÁLIDA, se ele não existir."""
    if not os.path.exists(JSON_FILE):
        st.info(f"Arquivo '{JSON_FILE}' não encontrado. Criando um arquivo de exemplo VÁLIDO...")
        # Estrutura com URLs entre aspas duplas e um "nome" para busca no Shibata
        default_data = [
            { "nome": "Banana Nanica", "nagumo": "https://www.nagumo.com/p/banana-nanica-kg-2004", "shibata": "https://www.loja.shibata.com.br/produto/16286/banana-nanica-14kg-aprox-6-unidades" },
            { "nome": "Banana Prata", "nagumo": "https://www.nagumo.com/p/banana-prata-kg-2011", "shibata": "https://www.loja.shibata.com.br/produto/16465/banana-prata-11kg-aprox-8-unidades" }
        ]
        try:
            with open(JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            st.error(f"Erro ao criar o arquivo {JSON_FILE}: {e}")
            return None
    return ler_itens_json()

def ler_itens_json():
    """Lê o arquivo itens.json e retorna a lista de itens."""
    if not os.path.exists(JSON_FILE):
        return criar_json_padrao()
    
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not data:
                 st.warning(f"O arquivo '{JSON_FILE}' está vazio. Tentando criar padrão...")
                 return criar_json_padrao()
            return data
    except json.JSONDecodeError:
        st.error(f"Erro: O arquivo '{JSON_FILE}' contém um JSON inválido. Verifique a formatação (URLs devem estar entre aspas duplas).")
        st.info("Tentando criar um arquivo padrão válido para continuar a execução...")
        return criar_json_padrao() 
    except IOError as e:
        st.error(f"Erro ao ler o arquivo {JSON_FILE}: {e}")
        return []

# --- Funções Utilitárias (Gerais e Nagumo) ---

def remover_acentos(texto):
    if not texto:
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').lower()

def contem_papel_toalha(texto):
    texto = remover_acentos(texto.lower())
    return "papel" in texto and "toalha" in texto

def extrair_info_papel_toalha(nome, descricao):
    texto_nome = remover_acentos(nome.lower())
    texto_desc = remover_acentos(descricao.lower())

    match = re.search(r'(\d+)\s*(un|unidades?|rolos?)\s*(\d+)\s*(folhas|toalhas)', texto_nome)
    if match:
        rolos = int(match.group(1))
        folhas_por_rolo = int(match.group(3))
        total_folhas = rolos * folhas_por_rolo
        return rolos, folhas_por_rolo, total_folhas, f"{rolos} {match.group(2)}, {folhas_por_rolo} {match.group(4)}"
    match = re.search(r'(\d+)\s*(folhas|toalhas)', texto_nome)
    if match:
        total_folhas = int(match.group(1))
        return None, None, total_folhas, f"{total_folhas} {match.group(2)}"
    texto_completo = f"{texto_nome} {texto_desc}"
    match = re.search(r'(\d+)\s*(un|unidades?|rolos?)\s*.*?(\d+)\s*(folhas|toalhas)', texto_completo)
    if match:
        rolos = int(match.group(1))
        folhas_por_rolo = int(match.group(3))
        total_folhas = rolos * folhas_por_rolo
        return rolos, folhas_por_rolo, total_folhas, f"{rolos} {match.group(2)}, {folhas_por_rolo} {match.group(4)}"
    match = re.search(r'(\d+)\s*(folhas|toalhas)', texto_completo)
    if match:
        total_folhas = int(match.group(1))
        return None, None, total_folhas, f"{total_folhas} {match.group(2)}"
    m_un = re.search(r"(\d+)\s*(un|unidades?)", texto_completo)
    if m_un:
        total = int(m_un.group(1))
        return None, None, total, f"{total} unidades"
    return None, None, None, None

def calcular_preco_unitario_nagumo(preco_valor, descricao, nome, unidade_api=None):
    preco_unitario = "Sem unidade"
    texto_completo = f"{nome} {descricao}".lower() 

    if contem_papel_toalha(texto_completo):
        rolos, folhas_por_rolo, total_folhas, texto_exibicao = extrair_info_papel_toalha(nome, descricao)
        if total_folhas and total_folhas > 0:
            preco_por_item = preco_valor / total_folhas
            return f"R$ {preco_por_item:.3f}/folha"
        return "Preço por folha: n/d"

    if "papel higi" in texto_completo:
        match_rolos = re.search(r"leve\s*0*(\d+)", texto_completo)
        if not match_rolos:
            match_rolos = re.search(r"\blv?\s*0*(\d+)", texto_completo)
        if not match_rolos:
            match_rolos = re.search(r"\blv?(\d+)", texto_completo)
        if not match_rolos:
            match_rolos = re.search(r"\bl\s*0*(\d+)", texto_completo)
        if not match_rolos:
            match_rolos = re.search(r"c/\s*0*(\d+)", texto_completo)
        if not match_rolos:
            match_rolos = re.search(r"(\d+)\s*rolos?", texto_completo)
        if not match_rolos:
            match_rolos = re.search(r"(\d+)\s*(un|unidades?)", texto_completo)
        match_metros = re.search(r"(\d+[.,]?\d*)\s*(m|metros?|mt)", texto_completo)
        if match_rolos and match_metros:
            try:
                rolos = int(match_rolos.group(1))
                metros = float(match_metros.group(1).replace(',', '.'))
                if rolos > 0 and metros > 0:
                    preco_por_metro = preco_valor / rolos / metros
                    return f"R$ {preco_por_metro:.3f}/m"
            except:
                pass

    fontes = [descricao.lower(), nome.lower()]
    for fonte in fontes:
        match_g = re.search(r"(\d+[.,]?\d*)\s*(g|gramas?)", fonte)
        if match_g:
            gramas = float(match_g.group(1).replace(',', '.'))
            if gramas > 0:
                return f"R$ {preco_valor / (gramas / 1000):.2f}/kg"
        match_kg = re.search(r"(\d+[.,]?\d*)\s*(kg|quilo)", fonte)
        if match_kg:
            kg = float(match_kg.group(1).replace(',', '.'))
            if kg > 0:
                return f"R$ {preco_valor / kg:.2f}/kg"
        match_ml = re.search(r"(\d+[.,]?\d*)\s*(ml|mililitros?)", fonte)
        if match_ml:
            ml = float(match_ml.group(1).replace(',', '.'))
            if ml > 0:
                return f"R$ {preco_valor / (ml / 1000):.2f}/L"
        match_l = re.search(r"(\d+[.,]?\d*)\s*(l|litros?)", fonte)
        if match_l:
            litros = float(match_l.group(1).replace(',', '.'))
            if litros > 0:
                return f"R$ {preco_valor / litros:.2f}/L"
        match_un = re.search(r"(\d+[.,]?\d*)\s*(un|unidades?)", fonte)
        if match_un:
            unidades = float(match_un.group(1).replace(',', '.'))
            if unidades > 0:
                return f"R$ {preco_valor / unidades:.2f}/un"

    if unidade_api:
        unidade_api = unidade_api.lower()
        if unidade_api == 'kg':
            return f"R$ {preco_valor:.2f}/kg"
        elif unidade_api == 'g':
            return f"R$ {preco_valor * 1000:.2f}/kg"
        elif unidade_api == 'l':
            return f"R$ {preco_valor:.2f}/L"
        elif unidade_api == 'ml':
            return f"R$ {preco_valor * 1000:.2f}/L"
        elif unidade_api == 'un':
            return f"R$ {preco_valor:.2f}/un"

    return preco_unitario

def extrair_sku_da_url_nagumo(url_nagumo: str):
    """Extrai o SKU do final de uma URL do Nagumo."""
    if not url_nagumo or not isinstance(url_nagumo, str):
        return None
    try:
        path = urlparse(url_nagumo).path
        path_segments = [seg for seg in path.split('/') if seg]
        
        if path_segments:
            last_segment = path_segments[-1]
            match = re.search(r'-(\d+)$', last_segment)
            if match:
                return match.group(1)
                
    except Exception as e:
        return None
    return None

def buscar_produto_nagumo_pela_url(url_nagumo: str):
    """Extrai o SKU da URL do Nagumo e busca o produto na API."""
    sku = extrair_sku_da_url_nagumo(url_nagumo)
    
    if not sku:
        st.error(f"Não foi possível extrair o SKU da URL do Nagumo: {url_nagumo}")
        return None
        
    payload = {
        "operationName": "SearchProducts",
        "variables": {
            "searchProductsInput": {
                "clientId": "NAGUMO",
                "storeReference": "22",
                "currentPage": 1,
                "minScore": 0.1,  
                "pageSize": 10,   
                "search": [{"query": str(sku)}],
                "filters": {},
                "googleAnalyticsSessionId": ""
            }
        },
        "query": NAGUMO_QUERY
    }
    try:
        response = requests.post(NAGUMO_API_URL, headers=NAGUMO_HEADERS, json=payload, timeout=10)
        response.raise_for_status() 
        data = response.json()
        produtos = data.get("data", {}).get("searchProducts", {}).get("products", [])
        
        for produto in produtos:
            if produto.get('sku') == str(sku):
                return produto
        
        if produtos:
            return produtos[0]
            
        return None
        
    except requests.exceptions.RequestException as e:
        # A API pode retornar 400 se o SKU não existir ou for inválido.
        # st.error(f"Erro de conexão com Nagumo ao buscar URL {url_nagumo} (SKU {sku}): {e}")
        return None
    except Exception as e:
        # st.error(f"Ocorreu um erro ao processar a resposta do Nagumo (URL {url_nagumo}, SKU {sku}): {e}")
        return None

# --- Funções SHIBATA (Copiadas e adaptadas de main (1).py) ---

def gerar_formas_variantes(termo):
    """Gera singular/plural automaticamente com regras básicas"""
    termo = remover_acentos(termo.strip())
    variantes = {termo}

    if termo.endswith("s"):
        variantes.add(termo[:-1])
    else:
        variantes.add(termo + "s")

    return list(variantes)

def calcular_preco_unidade_shibata(descricao, preco_total):
    """Calcula o preço por unidade (kg, L, un) para Shibata (baseado em main (1).py)"""
    desc_minus = remover_acentos(descricao)
    
    # 1. KG
    match_kg = re.search(r'(\d+[.,]?\d*)\s*(kg|quilo)', desc_minus)
    if match_kg:
        peso = float(match_kg.group(1).replace(',', '.'))
        return preco_total / peso, f"R$ {preco_total / peso:.2f}".replace('.', ',') + "/kg"
    
    # 2. Gramas
    match_g = re.search(r'(\d+[.,]?\d*)\s*(g|gramas?)', desc_minus)
    if match_g:
        peso = float(match_g.group(1).replace(',', '.')) / 1000
        return preco_total / peso, f"R$ {preco_total / peso:.2f}".replace('.', ',') + "/kg"
    
    # 3. Litros
    match_l = re.search(r'(\d+[.,]?\d*)\s*(l|litros?)', desc_minus)
    if match_l:
        litros = float(match_l.group(1).replace(',', '.'))
        return preco_total / litros, f"R$ {preco_total / litros:.2f}".replace('.', ',') + "/L"
    
    # 4. Mililitros
    match_ml = re.search(r'(\d+[.,]?\d*)\s*(ml|mililitros?)', desc_minus)
    if match_ml:
        litros = float(match_ml.group(1).replace(',', '.')) / 1000
        return preco_total / litros, f"R$ {preco_total / litros:.2f}".replace('.', ',') + "/L"
        
    # 5. Unidades (geral)
    match_un = re.search(r'(\d+)\s*(un|unidades?|rolos?|ovos?|pacotes?)', desc_minus)
    if match_un:
        unidades = float(match_un.group(1).replace(',', '.'))
        return preco_total / unidades, f"R$ {preco_total / unidades:.2f}".replace('.', ',') + "/un"
        
    return None, None

def calcular_preco_papel_toalha_shibata(descricao, preco_total):
    """Calcula o preço por folha para papel toalha (baseado em main (1).py)"""
    desc = descricao.lower()
    
    # 1. Padrão X Un Y Folhas (ex: 2un 60 folhas)
    match = re.search(r'(\d+)\s*(rolos|unidades|uni|pacotes|kits?)\s*.*?(\d+)\s*(folhas|toalhas)', desc)
    if match:
        unidades = int(match.group(1))
        folhas_por_unidade = int(match.group(3))
        total_folhas = unidades * folhas_por_unidade
        preco_por_folha = preco_total / total_folhas if total_folhas else None
        return total_folhas, preco_por_folha

    # 2. Padrão X Folhas (ex: 200 folhas)
    match_folhas = re.search(r'(\d+)\s*(folhas|toalhas)', desc)
    if match_folhas:
        total_folhas = int(match_folhas.group(1))
        preco_por_folha = preco_total / total_folhas if total_folhas else None
        return total_folhas, preco_por_folha

    return None, None

def formatar_preco_unidade_personalizado(preco_total, quantidade, unidade):
    """Formata o preço baseado na quantidade e unidade nativa da API (baseado em main (1).py)"""
    if not unidade:
        return f"R$ {preco_total:.2f}".replace('.', ',')
        
    unidade = unidade.lower()
    if quantidade and quantidade != 1:
        # A API Shibata às vezes retorna 1000g, 1000ml, 0,5kg, etc.
        return f"R$ {preco_total:.2f}".replace('.', ',') + f"/{str(quantidade).replace('.', ',')}{unidade.lower()}"
    else:
        return f"R$ {preco_total:.2f}".replace('.', ',') + f"/{unidade.lower()}"

def buscar_pagina_shibata(termo, pagina):
    """Busca uma única página no Shibata (baseado em main (1).py)"""
    url = f"https://services.vipcommerce.com.br/api-admin/v1/org/{ORG_ID}/filial/1/centro_distribuicao/1/loja/buscas/produtos/termo/{termo}?page={pagina}"
    try:
        response = requests.get(url, headers=HEADERS_SHIBATA, timeout=5) # Reduzido timeout
        if response.status_code == 200:
            data = response.json().get('data', {}).get('produtos', [])
            return [produto for produto in data if produto.get("disponivel", True)]
        # st.error(f"Erro na busca do Shibata (página {pagina}, termo {termo}): Status {response.status_code}")
        return []
    except requests.exceptions.RequestException:
        # st.error(f"Erro de conexão com Shibata (página {pagina}, termo {termo})")
        return []
    except Exception:
        # st.error(f"Erro ao processar resposta do Shibata (página {pagina}, termo {termo})")
        return []

def buscar_produto_shibata_por_nome(nome_busca: str):
    """
    Busca o melhor produto no Shibata para o nome de busca, utilizando paralelismo.
    Retorna o produto com o preço mais baixo por unidade (se calculável).
    """
    termo_sem_acento = remover_acentos(nome_busca)
    termos_expandidos = gerar_formas_variantes(termo_sem_acento.split()[0]) # Expande apenas a primeira palavra
    palavras_chave = [remover_acentos(p) for p in nome_busca.split()]
    
    produtos_shibata = []
    # Busca por apenas 2 páginas para ser mais rápido (pode aumentar se for necessário)
    max_paginas = 2 
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(buscar_pagina_shibata, t, pagina)
                       for t in termos_expandidos
                       for pagina in range(1, max_paginas + 1)]
        
        for future in as_completed(futures):
                produtos_shibata.extend(future.result())

    # Remover duplicados por ID
    ids_vistos = set()
    produtos_shibata = [p for p in produtos_shibata if p.get('id') and p.get('id') not in ids_vistos and not ids_vistos.add(p.get('id'))]

    # Filtrar produtos que contenham todas as palavras-chave principais
    produtos_shibata_filtrados = [
        p for p in produtos_shibata
        if all(
            palavra in remover_acentos(
                f"{p.get('descricao', '')} {p.get('nome', '')}"
            ) for palavra in palavras_chave
        )
    ]
    
    if not produtos_shibata_filtrados:
        return None

    # Processar e encontrar o melhor preço por unidade
    produtos_processados = []
    for p in produtos_shibata_filtrados:
        preco = float(p.get('preco') or 0)
        em_oferta = p.get('em_oferta', False)
        oferta_info = p.get('oferta') or {}
        preco_oferta = oferta_info.get('preco_oferta')
        preco_total = float(preco_oferta) if em_oferta and preco_oferta else preco
        descricao = f"{p.get('descricao', '')} {p.get('nome', '')}"

        # 1. Calcula preço por unidade (R$/kg, R$/L, R$/un)
        preco_unidade_val, preco_unidade_str = calcular_preco_unidade_shibata(descricao, preco_total)

        # 2. Calcula preço por folha (se for papel toalha)
        if 'papel toalha' in remover_acentos(nome_busca):
            total_folhas, preco_por_folha = calcular_preco_papel_toalha_shibata(descricao, preco_total)
            if preco_por_folha:
                 p['preco_unitario_valor_real'] = preco_por_folha
                 p['preco_unitario_str_real'] = f"R$ {preco_por_folha:.3f}".replace('.', ',') + "/folha"
                 produtos_processados.append(p)
                 continue # Já encontrou o critério mais específico
        
        # 3. Se não for papel toalha, usa o preço por unidade (kg/L/un)
        if preco_unidade_val:
            p['preco_unitario_valor_real'] = preco_unidade_val
            p['preco_unitario_str_real'] = preco_unidade_str
        else:
            # Fallback: se não conseguiu extrair unidade, usa o preço total
            p['preco_unitario_valor_real'] = preco_total
            p['preco_unitario_str_real'] = f"R$ {preco_total:.2f}".replace('.', ',') + "/un (Total)"

        produtos_processados.append(p)
    
    # Retorna o produto com o menor preço por unidade calculado
    produtos_ordenados = sorted(produtos_processados, key=lambda x: x.get('preco_unitario_valor_real', float('inf')))
    
    return produtos_ordenados[0] if produtos_ordenados else None

# --- Configuração da Página Streamlit ---

st.set_page_config(page_title="Preços Nagumo vs Shibata", page_icon="🛒", layout="wide")

st.markdown("""
    <style>
        /* CSS Geral e Layout */
        .block-container { 
            padding-top: 0rem; 
            padding-bottom: 15px !important;
            margin-bottom: 15px !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        footer {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        header[data-testid="stHeader"] { display: none; }

        /* Estilos do Bloco de Produto */
        div, span, strong, small { font-size: 0.75rem !important; }
        img { max-width: 80px; height: auto; }
        hr.product-separator {
            border: none;
            border-top: 1px solid #eee;
            margin: 10px 0;
        }
        .info-cinza { color: gray; font-size: 0.8rem; }
        
        /* Layout de Preços */
        .price-container {
            display: flex;
            flex-direction: column;
            gap: 5px; /* Espaço entre Nagumo e Shibata */
            margin-top: 5px;
        }
        .price-box {
            border: 1px solid #ddd;
            padding: 5px;
            border-radius: 4px;
            font-size: 0.8rem !important;
        }
        .market-logo {
            width: 40px; /* Reduz o tamanho do logo do mercado */
            height: auto;
            margin-right: 5px;
            vertical-align: middle;
        }
        .market-header {
            font-weight: bold;
            display: flex;
            align-items: center;
        }
        .price-value {
            font-weight: bold;
            font-size: 1rem;
            color: #1e8449; /* Verde para destaque */
        }
    </style>
""", unsafe_allow_html=True)

# --- Interface Principal ---

# Cabeçalho com Logos
st.markdown(f"""
    <h5 style="display: flex; align-items: center; justify-content: center; margin-top: 1rem;">
        <img src="{LOGO_NAGUMO_URL}" width="120" alt="Nagumo" style="margin-right:15px; border-radius: 6px; border: 1.5px solid white; padding: 0px;"/>
        <img src="{LOGO_SHIBATA_URL}" width="120" alt="Shibata" style="border-radius: 6px; border: 1.5px solid white; padding: 0px;"/>
    </h5>
    <h6 style='text-align: center;'>🛒 Comparação de Preços</h6>
""", unsafe_allow_html=True)

# Carrega os itens do JSON
itens_para_buscar = ler_itens_json()

if not itens_para_buscar:
    st.error("❌ Não foi possível carregar os itens. Verifique o arquivo 'itens.json'.")
else:
    st.markdown(f"<small style='text-align: center; display: block;'>🔎 Consultando {len(itens_para_buscar)} item(ns)...</small>", unsafe_allow_html=True)
    st.markdown("---")

    with st.spinner("Buscando preços..."):
        for item in itens_para_buscar:
            url_nagumo = item.get("nagumo")
            nome_shibata_busca = item.get("nome", "").strip() # Use o nome para buscar no Shibata
            
            # 1. Busca Nagumo
            p_nagumo = None
            if url_nagumo:
                p_nagumo = buscar_produto_nagumo_pela_url(url_nagumo)

            # 2. Busca Shibata (REAL)
            p_shibata = None
            if nome_shibata_busca:
                 p_shibata = buscar_produto_shibata_por_nome(nome_shibata_busca)

            # Se Nagumo não for encontrado ou se for um item sem nome de busca no Shibata, exibe aviso e continua
            if not p_nagumo and not p_shibata:
                st.warning(f"Nenhum produto encontrado para o item: {nome_shibata_busca}")
                st.markdown("<hr class='product-separator' />", unsafe_allow_html=True)
                continue
            
            # --- Processamento dos dados Nagumo ---
            if p_nagumo:
                photos_list = p_nagumo.get('photosUrl')
                imagem = photos_list[0] if photos_list else DEFAULT_IMAGE_URL
                
                # Preço Nagumo
                preco_normal_nagumo = p_nagumo.get("price", 0)
                promocao = p_nagumo.get("promotion") or {}
                cond = promocao.get("conditions") or []
                preco_desconto_nagumo = None
                if promocao.get("isActive") and isinstance(cond, list) and len(cond) > 0:
                    preco_desconto_nagumo = cond[0].get("price")
                preco_exibir_nagumo = preco_desconto_nagumo if preco_desconto_nagumo else preco_normal_nagumo
                
                preco_unitario_nagumo_str = calcular_preco_unitario_nagumo(
                    preco_exibir_nagumo, 
                    p_nagumo.get('description', ''), 
                    p_nagumo.get('name', ''), 
                    p_nagumo.get("unit")
                )

                # Título Nagumo
                titulo_nagumo = p_nagumo['name']
                texto_completo = p_nagumo['name'] + " " + p_nagumo.get('description', '')
                if contem_papel_toalha(texto_completo):
                    rolos, folhas_por_rolo, total_folhas, texto_exibicao = extrair_info_papel_toalha(p_nagumo['name'], p_nagumo['description'])
                    if texto_exibicao:
                        titulo_nagumo += f" <span class='info-cinza'>({texto_exibicao})</span>"
                if "papel higi" in remover_acentos(titulo_nagumo.lower()):
                    titulo_lower = remover_acentos(titulo_nagumo.lower())
                    if "folha simples" in titulo_lower:
                        titulo_nagumo = re.sub(r"(folha simples)", r"<span style='color:red; font-weight:bold;'>\1</span>", titulo_nagumo, flags=re.IGNORECASE)
                    if "folha dupla" in titulo_lower or "folha tripla" in titulo_lower:
                        titulo_nagumo = re.sub(r"(folha dupla|folha tripla)", r"<span style='color:green; font-weight:bold;'>\1</span>", titulo_nagumo, flags=re.IGNORECASE)

                # HTML do Preço Nagumo
                if preco_desconto_nagumo and preco_desconto_nagumo < preco_normal_nagumo:
                    desconto_percentual = ((preco_normal_nagumo - preco_desconto_nagumo) / preco_normal_nagumo) * 100
                    preco_nagumo_html = f"""
                        <span class='price-value'>R$ {preco_desconto_nagumo:.2f}</span>
                        <span style='color: red; font-weight: bold; font-size:0.8em;'> ({desconto_percentual:.0f}% OFF)</span><br>
                        <span style='text-decoration: line-through; color: gray; font-size:0.8em;'>R$ {preco_normal_nagumo:.2f}</span>
                    """
                else:
                    preco_nagumo_html = f"<span class='price-value'>R$ {preco_normal_nagumo:.2f}</span>"
                estoque_nagumo = p_nagumo.get('stock', 'N/D')
            else:
                titulo_nagumo = f"{nome_shibata_busca} (Nagumo não encontrado)"
                imagem = DEFAULT_IMAGE_URL
                preco_nagumo_html = "<span style='color:red;'>Produto não encontrado/SKU inválido.</span>"
                preco_unitario_nagumo_str = "N/D"
                estoque_nagumo = "N/D"

            # --- Processamento dos dados Shibata ---
            if p_shibata:
                preco_shibata = float(p_shibata.get('preco') or 0)
                em_oferta_shibata = p_shibata.get('em_oferta', False)
                oferta_info_shibata = p_shibata.get('oferta') or {}
                preco_oferta_shibata = oferta_info_shibata.get('preco_oferta')
                preco_antigo_shibata = oferta_info_shibata.get('preco_antigo')
                
                preco_total_shibata = float(preco_oferta_shibata) if em_oferta_shibata and preco_oferta_shibata else preco_shibata
                
                titulo_shibata = p_shibata.get('descricao', p_shibata.get('nome', 'Produto Shibata'))
                preco_unitario_shibata_str = p_shibata.get('preco_unitario_str_real', 'N/D') # Usa o valor calculado no search

                # HTML do Preço Shibata
                if em_oferta_shibata and preco_oferta_shibata and preco_antigo_shibata:
                    preco_oferta_val = float(preco_oferta_shibata)
                    preco_antigo_val = float(preco_antigo_shibata)
                    desconto = round(100 * (preco_antigo_val - preco_oferta_val) / preco_antigo_val) if preco_antigo_val else 0
                    preco_antigo_str = f"R$ {preco_antigo_val:.2f}".replace('.', ',')
                    
                    preco_shibata_html = f"""
                        <span class='price-value'>R$ {preco_oferta_val:.2f}</span>
                        <span style='color: red; font-weight: bold; font-size:0.8em;'> ({desconto}% OFF)</span><br>
                        <span style='text-decoration: line-through; color: gray; font-size:0.8em;'>{preco_antigo_str}</span>
                    """
                else:
                    preco_shibata_html = f"<span class='price-value'>R$ {preco_total_shibata:.2f}</span>"
            else:
                titulo_shibata = f"{nome_shibata_busca} (Shibata não encontrado)"
                preco_shibata_html = "<span style='color:red;'>Produto não encontrado.</span>"
                preco_unitario_shibata_str = "N/D"
            
            # Usa o nome do item do JSON como título principal
            titulo_principal = item.get("nome", titulo_nagumo if p_nagumo else nome_shibata_busca)

            # --- Renderização com Colunas ---
            col1, col2 = st.columns([1, 1.5]) 
            
            with col1:
                # Layout de Imagem e Título (Baseado no Nagumo se encontrado, senão no nome)
                st.markdown(f"""
                    <div style="display: flex; align-items: flex-start; gap: 10px; margin-bottom: 0rem;">
                        <div style="flex: 0 0 auto;">
                            <img src="{imagem}" width="80" style="background-color: white; border-radius: 6px; display: block;"/>
                        </div>
                        <div style="flex: 1; word-break: break-word; overflow-wrap: anywhere;">
                            <strong>{titulo_principal}</strong><br>
                            <div style="color: gray; font-size: 0.8em;">(Baseado em: {titulo_nagumo if p_nagumo else titulo_shibata})</div>
                            <div style="margin-top: 4px; font-size: 0.9em; color: #666;">
                                Nagumo: {preco_unitario_nagumo_str} <br>
                                Shibata: {preco_unitario_shibata_str}
                            </div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

            with col2:
                # Layout de Preços Nagumo vs Shibata
                st.markdown(f"""
                    <div class="price-container">
                        <div class="price-box" style="border-color: #581845;">
                            <div class="market-header">
                                <img src="{LOGO_NAGUMO_URL}" class="market-logo" alt="Nagumo Logo"> Nagumo
                            </div>
                            {preco_nagumo_html}
                            <small style='color: gray;'>Estoque: {estoque_nagumo}</small>
                        </div>
                        
                        <div class="price-box" style="border-color: #ffc300;">
                            <div class="market-header">
                                <img src="{LOGO_SHIBATA_URL}" class="market-logo" alt="Shibata Logo"> Shibata
                            </div>
                            {preco_shibata_html}
                            {f"<small style='color: #666;'>Produto: {titulo_shibata}</small>" if p_shibata else ""}
                        </div>
                    </div>
                """, unsafe_allow_html=True)
            
            st.markdown("<hr class='product-separator' />", unsafe_allow_html=True)
