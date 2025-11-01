import streamlit as st
import requests
import unicodedata
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------------------------------------------------------
# CONSTANTES GLOBAIS
# ----------------------------------------------------------------------
JSON_FILE = "itens.json" # Define o nome do arquivo JSON
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJ2aXBjb21tZXJjZSIsImF1ZCI6ImFwaS1hZG1pbiIsInN1YiI6IjZiYzQ4NjdlLWRjYTktMTFlOS04NzQyLTAyMGQ3OTM1OWNhMCIsInZpcGNvbW1lcmNlQ2xpZW50ZUlkIjpudWxsLCJpYXQiOjE3NTE5MjQ5MjgsInZlciI6MSwiY2xpZW50IjpudWxsLCJvcGVyYXRvciI6bnVsbCwib3JnIjoiMTYxIn0.yDCjqkeJv7D3wJ0T_fu3AaKlX9s5PQYXD19cESWpH-j3F_Is-Zb-bDdUvduwoI_RkOeqbYCuxN0ppQQXb1ArVg"
ORG_ID = "161"
HEADERS_SHIBATA = {
    "Authorization": f"Bearer {TOKEN}",
    "organizationid": ORG_ID,
    "sessao-id": "4ea572793a132ad95d7e758a4eaf6b09",
    "domainkey": "loja.shibata.com.br",
    "User-Agent": "Mozilla/5.0"
}

# Links dos logos
LOGO_SHIBATA_URL = "https://rawcdn.githack.com/gymbr/precosmercados/main/logo-shibata.png"
LOGO_NAGUMO_URL = "https://rawcdn.githack.com/gymbr/precosmercados/main/logo-nagumo2.png"
DEFAULT_IMAGE_URL = "https://rawcdn.githack.com/gymbr/precosmercados/main/sem-imagem.png"


# ----------------------------------------------------------------------
# FUNÇÕES DE LEITURA E EXTRAÇÃO DO JSON
# ----------------------------------------------------------------------

def ler_itens_json():
    """Lê o arquivo JSON especificado pela constante JSON_FILE."""
    try:
        # Tenta ler o arquivo local
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        st.error(f"Erro: Arquivo {JSON_FILE} não encontrado no diretório. Por favor, certifique-se de que ele existe.")
        return []
    except json.JSONDecodeError:
        st.error(f"Erro: Não foi possível decodificar o arquivo {JSON_FILE}. Verifique se o JSON está formatado corretamente.")
        return []
    except Exception as e:
        st.error(f"Erro inesperado ao ler o arquivo {JSON_FILE}: {e}")
        return []

def extrair_termos_busca(nome_completo):
    """Extrai o nome de busca e o nome de exibição do campo 'nome' do JSON."""
    # 1. Remove preços (R$XX ou R$X,XX) do nome
    nome_sem_preco = re.sub(r'\sR\$\d+(?:[.,]\d+)?', '', nome_completo, flags=re.IGNORECASE).strip()
    
    # 2. Assume que o termo de busca é o nome sem preço e sem emojis (apenas letras, números e espaços)
    nome_busca = re.sub(r'[^\w\s\-\/]', '', nome_sem_preco).strip()
    
    return nome_busca, nome_sem_preco # nome_busca, nome_exibicao

# Funções utilitárias (mantidas)
def remover_acentos(texto):
    if not texto:
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').lower()

def calcular_precos_papel(descricao, preco_total):
    desc_minus = descricao.lower()
    match_leve = re.search(r'leve\s*(\d+)', desc_minus)
    if match_leve:
        q_rolos = int(match_leve.group(1))
    else:
        match_rolos = re.search(r'(\d+)\s*(rolos|unidades|uni|pacotes|pacote)', desc_minus)
        q_rolos = int(match_rolos.group(1)) if match_rolos else None
    match_metros = re.search(r'(\d+(?:[\.,]\d+)?)\s*m(?:etros)?', desc_minus)
    m_rolos = float(match_metros.group(1).replace(',', '.')) if match_metros else None
    if q_rolos and m_rolos and q_rolos > 0 and m_rolos > 0:
        preco_por_metro = preco_total / (q_rolos * m_rolos)
        return preco_por_metro, f"R$ {preco_por_metro:.3f}".replace('.', ',') + "/m"
    return None, None

def calcular_preco_unidade(descricao, preco_total):
    desc_minus = remover_acentos(descricao)
    match_kg = re.search(r'(\d+(?:[\.,]\d+)?)\s*(kg|quilo)', desc_minus)
    if match_kg:
        peso = float(match_kg.group(1).replace(',', '.'))
        if peso > 0: return preco_total / peso, f"R$ {preco_total / peso:.2f}".replace('.', ',') + "/kg"
    match_g = re.search(r'(\d+(?:[\.,]\d+)?)\s*(g|gramas?)', desc_minus)
    if match_g:
        peso = float(match_g.group(1).replace(',', '.')) / 1000
        if peso > 0: return preco_total / peso, f"R$ {preco_total / peso:.2f}".replace('.', ',') + "/kg"
    match_l = re.search(r'(\d+(?:[\.,]\d+)?)\s*(l|litros?)', desc_minus)
    if match_l:
        litros = float(match_l.group(1).replace(',', '.'))
        if litros > 0: return preco_total / litros, f"R$ {preco_total / litros:.2f}".replace('.', ',') + "/L"
    match_ml = re.search(r'(\d+(?:[\.,]\d+)?)\s*(ml|mililitros?)', desc_minus)
    if match_ml:
        litros = float(match_ml.group(1).replace(',', '.')) / 1000
        if litros > 0: return preco_total / litros, f"R$ {preco_total / litros:.2f}".replace('.', ',') + "/L"
    return None, None

def calcular_preco_papel_toalha(descricao, preco_total):
    desc = descricao.lower()
    qtd_unidades = None
    match_unidades = re.search(r'(\d+)\s*(rolos|unidades|pacotes|pacote|kits?)', desc)
    if match_unidades:
        qtd_unidades = int(match_unidades.group(1))

    folhas_por_unidade = None
    match_folhas = re.search(r'(\d+)\s*(folhas|toalhas)\s*cada', desc)
    if not match_folhas:
        match_folhas = re.search(r'(\d+)\s*(folhas|toalhas)', desc)
    if match_folhas:
        folhas_por_unidade = int(match_folhas.group(1))

    match_leve_folhas = re.search(r'leve\s*(\d+)\s*pague\s*\d+\s*folhas', desc)
    if match_leve_folhas:
        folhas_leve = int(match_leve_folhas.group(1))
        preco_por_folha = preco_total / folhas_leve if folhas_leve else None
        return folhas_leve, preco_por_folha

    match_leve_pague = re.findall(r'(\d+)', desc)
    folhas_leve = None
    if 'leve' in desc and 'folhas' in desc and match_leve_pague:
        folhas_leve = max(int(n) for n in match_leve_pague)

    match_unidades_kit = re.search(r'unidades por kit[:\- ]+(\d+)', desc)
    match_folhas_rolo = re.search(r'quantidade de folhas por (?:rolo|unidade)[:\- ]+(\d+)', desc)
    if match_unidades_kit and match_folhas_rolo:
        total_folhas = int(match_unidades_kit.group(1)) * int(match_folhas_rolo.group(1))
        preco_por_folha = preco_total / total_folhas if total_folhas else None
        return total_folhas, preco_por_folha

    if qtd_unidades and folhas_por_unidade:
        total_folhas = qtd_unidades * folhas_por_unidade
        preco_por_folha = preco_total / total_folhas if total_folhas else None
        return total_folhas, preco_por_folha

    if folhas_por_unidade:
        preco_por_folha = preco_total / folhas_por_unidade
        return folhas_por_unidade, preco_por_folha

    if folhas_leve:
        preco_por_folha = preco_total / folhas_leve
        return folhas_leve, preco_por_folha

    return None, None


def formatar_preco_unidade_personalizado(preco_total, quantidade, unidade):
    if not unidade:
        return None
    unidade = unidade.lower()
    if quantidade and quantidade != 1:
        return f"R$ {preco_total:.2f}".replace('.', ',') + f"/{str(quantidade).replace('.', ',')}{unidade.lower()}"
    else:
        return f"R$ {preco_total:.2f}".replace('.', ',') + f"/{unidade.lower()}"

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
    
    if preco_valor == 0:
        return "N/D"

    if contem_papel_toalha(texto_completo):
        rolos, folhas_por_rolo, total_folhas, texto_exibicao = extrair_info_papel_toalha(nome, descricao)
        if total_folhas and total_folhas > 0:
            preco_por_item = preco_valor / total_folhas
            return f"R$ {preco_por_item:.3f}/folha"
        return "Preço por folha: n/d"
        
    if "papel higi" in texto_completo:
        match_rolos = re.search(r"(\d+)\s*rolos?", texto_completo)
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
        elif unidade_api == 'l':
            return f"R$ {preco_valor:.2f}/L"
        elif unidade_api == 'un':
            return f"R$ {preco_valor:.2f}/un"
            
    return preco_unitario

def extrair_valor_unitario(preco_unitario):
    match = re.search(r"R\$ (\d+[.,]?\d*)", preco_unitario)
    if match:
        return float(match.group(1).replace(',', '.'))
    return float('inf')


# ----------------------------------------------------------------------
# NOVAS FUNÇÕES DE BUSCA POR ID / SKU
# ----------------------------------------------------------------------

def buscar_detalhes_shibata(produto_id):
    """
    Busca os detalhes de um produto específico no Shibata pelo ID.
    Esta função resolve o erro 'OrganizationId' enviando os HEADERS corretos.
    """
    url = f"https://services.vipcommerce.com.br/api-admin/v1/org/{ORG_ID}/filial/1/centro_distribuicao/1/loja/produtos/{produto_id}/detalhes"
    try:
        response = requests.get(url, headers=HEADERS_SHIBATA, timeout=10)
        if response.status_code == 200:
            return response.json().get('data', {}).get('produto')
        else:
            st.warning(f"Shibata API (detalhes) falhou para ID {produto_id}. Status: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão ao buscar detalhes do Shibata (ID: {produto_id}): {e}")
        return None
    except Exception as e:
        st.error(f"Erro inesperado ao buscar detalhes do Shibata (ID: {produto_id}): {e}")
        return None

def buscar_detalhes_nagumo_por_sku(sku):
    """
    Busca os detalhes de um produto específico no Nagumo pelo SKU.
    Utiliza a mesma query 'SearchProducts', mas filtra pelo SKU.
    """
    url = "https://nextgentheadless.instaleap.io/api/v3"
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://www.nagumo.com",
        "Referer": "https://www.nagumo.com/",
        "User-Agent": "Mozilla/5.0",
        "apollographql-client-name": "Ecommerce SSR",
        "apollographql-client-version": "0.11.0"
    }
    payload = {
        "operationName": "SearchProducts",
        "variables": {
            "searchProductsInput": {
                "clientId": "NAGUMO",
                "storeReference": "22",
                "currentPage": 1,
                "minScore": 1,
                "pageSize": 1, # Queremos apenas 1 resultado
                "search": [], # NENHUM termo de busca
                "filters": {"sku": [sku]}, # FILTRA pelo SKU
                "googleAnalyticsSessionId": ""
            }
        },
        "query": """
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
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        data = response.json()
        produtos = data.get("data", {}).get("searchProducts", {}).get("products", [])
        if produtos:
            return produtos[0] # Retorna o primeiro produto encontrado
        else:
            st.warning(f"Nagumo API (SKU) não encontrou o item: {sku}")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão ao buscar detalhes do Nagumo (SKU: {sku}): {e}")
        return None
    except Exception as e:
        st.error(f"Erro inesperado ao buscar detalhes do Nagumo (SKU: {sku}): {e}")
        return None

# ----------------------------------------------------------------------
# FUNÇÕES DE PROCESSAMENTO PARA OBTENÇÃO DO MELHOR PREÇO UNITÁRIO
# ----------------------------------------------------------------------

def obter_melhor_preco_shibata(produtos_ordenados):
    """Retorna o melhor preço unitário (valor e string formatada) do Shibata."""
    if not produtos_ordenados:
        return float('inf'), "Preço indisponível"

    melhor_produto = produtos_ordenados[0]
    preco_total = float(melhor_produto.get('preco_oferta') or melhor_produto.get('preco') or 0)
    
    # Prioriza o preco_unidade_val calculado por nós
    if 'preco_unidade_val' in melhor_produto and melhor_produto['preco_unidade_val'] != float('inf') and melhor_produto['preco_unidade_val'] > 0:
        preco_unidade_val = melhor_produto['preco_unidade_val']
        
        # Usa a string de unidade que já calculamos
        preco_unidade_str = melhor_produto.get('preco_unidade_str', '/un')
        
        # Tenta extrair a unidade do 'preco_unidade_str'
        match = re.search(r"/([a-zA-Z]+)", preco_unidade_str)
        unidade = match.group(1).lower() if match else "un"
        
        # Formatação especial para kg e L
        if unidade in ['kg', 'l']:
            return preco_unidade_val, f"R$ {preco_unidade_val:.2f}/{unidade}"
        # Formatação especial para metro (papel)
        if unidade == 'm':
            return preco_unidade_val, f"R$ {preco_unidade_val:.3f}/{unidade}"
        
        return preco_unidade_val, f"R$ {preco_unidade_val:.2f}/{unidade}"
    
    # Fallback se o cálculo falhar
    unidade_sigla = melhor_produto.get('unidade_sigla') or 'un'
    return preco_total, f"R$ {preco_total:.2f}/{unidade_sigla.lower()}"

def obter_melhor_preco_nagumo(produtos_ordenados):
    """Retorna o melhor preço unitário (valor e string formatada) do Nagumo."""
    if not produtos_ordenados:
        return float('inf'), "Preço indisponível"

    melhor_produto = produtos_ordenados[0]
    preco_unitario_valor = melhor_produto['preco_unitario_valor']
    preco_unitario_str = melhor_produto['preco_unitario_str']
    
    if preco_unitario_valor != float('inf') and preco_unitario_valor > 0:
        return preco_unitario_valor, preco_unitario_str.replace('.', ',')
        
    preco_exibir = (melhor_produto.get("promotion") or {}).get("conditions", [{}])[0].get("price") or melhor_produto.get("price", 0)
    return preco_exibir, f"R$ {preco_exibir:.2f}/un"

# ----------------------------------------------------------------------
# LÓGICA PRINCIPAL DE COMPARAÇÃO
# ----------------------------------------------------------------------
def realizar_comparacao_automatica():
    """Executa a busca para a lista de itens lida do JSON e retorna os resultados formatados."""
    lista_itens = ler_itens_json()
    if not lista_itens:
        return []

    resultados_finais = []
    
    for item in lista_itens:
        # Extrai o nome de exibição do JSON
        nome_completo = item['nome']
        _, nome_exibicao = extrair_termos_busca(nome_completo)
        
        # ----------------------------------------------------------------------
        # 1. Busca e Processamento Shibata (POR ID)
        # ----------------------------------------------------------------------
        produtos_shibata_processados = []
        shibata_url = item['shibata']
        match_shibata_id = re.search(r'/produto/(\d+)', shibata_url)
        
        if match_shibata_id:
            produto_id = match_shibata_id.group(1)
            p = buscar_detalhes_shibata(produto_id) # p = 'produto_detalhe'
            
            if p and p.get("disponivel", True):
                preco = float(p.get('preco') or 0)
                em_oferta = p.get('em_oferta', False)
                preco_oferta = p.get('preco_oferta')
                
                if not preco_oferta:
                    oferta_info = p.get('oferta') or {}
                    preco_oferta = oferta_info.get('preco_oferta')
                    
                preco_total = float(preco_oferta) if em_oferta and preco_oferta else preco
                
                descricao = p.get('descricao', '')
                quantidade_dif = p.get('quantidade_unidade_diferente')
                unidade_sigla = p.get('unidade_sigla')
                if unidade_sigla and unidade_sigla.lower() == "grande": unidade_sigla = None
                
                preco_unidade_str = formatar_preco_unidade_personalizado(preco_total, quantidade_dif, unidade_sigla)
                
                # --- Lógica de cálculo de preço unitário ---
                descricao_limpa = descricao.lower().replace('grande', '').strip()
                
                # Tenta primeiro pelo papel (mais específico)
                preco_unidade_val, preco_un_str_papel = calcular_precos_papel(descricao, preco_total)
                if preco_un_str_papel:
                     preco_unidade_str = preco_un_str_papel
                
                # Se não for papel, tenta genérico
                if not preco_unidade_val:
                    preco_unidade_val, preco_un_str_generico = calcular_preco_unidade(descricao_limpa, preco_total)
                    if preco_un_str_generico:
                        preco_unidade_str = preco_un_str_generico

                # Verifica se o preço personalizado (ex: /500g) é melhor
                match = re.search(r"/\s*([\d.,]+)\s*(kg|g|l|ml)", str(preco_unidade_str).lower())
                if match:
                    try:
                        quantidade = float(match.group(1).replace(",", "."))
                        unidade = match.group(2).lower()
                        if unidade == "g": quantidade /= 1000
                        elif unidade == "ml": quantidade /= 1000
                        if quantidade > 0:
                            preco_unidade_val = preco_total / quantidade
                    except: pass
                
                if not preco_unidade_val or preco_unidade_val == float('inf'): preco_unidade_val = preco_total
                
                p['preco_unidade_val'] = preco_unidade_val
                p['preco_unidade_str'] = preco_unidade_str # Armazena a string calculada
                
                # (Lógica do papel higiênico / metro)
                preco_por_metro_val, preco_por_metro_str = calcular_precos_papel(descricao, preco_total)
                if preco_por_metro_val:
                     p['preco_unidade_val'] = preco_por_metro_val # Sobrescreve se for papel
                     p['preco_unidade_str'] = preco_por_metro_str
                # --- Fim da lógica de cálculo ---
                
                produtos_shibata_processados.append(p)
        else:
             st.warning(f"Não foi possível extrair ID do Shibata da URL: {shibata_url}.")

        produtos_shibata_ordenados = sorted(produtos_shibata_processados, key=lambda x: x['preco_unidade_val'])

        # ----------------------------------------------------------------------
        # 2. Busca e Processamento Nagumo (POR SKU)
        # ----------------------------------------------------------------------
        produtos_nagumo_processados = []
        nagumo_url = item['nagumo']
        
        # Extrai o último número da URL (o SKU)
        sku_match_list = re.findall(r'(\d+)', nagumo_url.split('?')[0])
        sku = sku_match_list[-1] if sku_match_list else None
        
        if sku and sku.isdigit():
            produto = buscar_detalhes_nagumo_por_sku(sku)
            
            if produto and (produto.get('stock', 0) > 0 or produto.get('stock') is None): # Aceita se o estoque for > 0 ou se não for informado
                preco_normal = produto.get("price", 0)
                promocao = produto.get("promotion") or {}
                cond = promocao.get("conditions") or []
                preco_desconto = None
                if promocao.get("isActive") and isinstance(cond, list) and len(cond) > 0:
                    preco_desconto = cond[0].get("price")
                preco_exibir = preco_desconto if preco_desconto else preco_normal

                produto['preco_unitario_str'] = calcular_preco_unitario_nagumo(preco_exibir, produto.get('description', ''), produto['name'], produto.get("unit"))
                produto['preco_unitario_valor'] = extrair_valor_unitario(produto['preco_unitario_str'])
                
                produtos_nagumo_processados.append(produto)
        else:
            st.warning(f"Não foi possível extrair SKU do Nagumo da URL: {nagumo_url}")

        produtos_nagumo_ordenados = sorted(produtos_nagumo_processados, key=lambda x: x['preco_unitario_valor'])

        # ----------------------------------------------------------------------
        # 3. Formata os Resultados Finais
        # ----------------------------------------------------------------------
        preco_shibata_val, preco_shibata_str = obter_melhor_preco_shibata(produtos_shibata_ordenados)
        preco_nagumo_val, preco_nagumo_str = obter_melhor_preco_nagumo(produtos_nagumo_ordenados)

        # Determina o preço mais baixo para exibição
        preco_principal_str = ""
        if preco_shibata_val <= preco_nagumo_val and preco_shibata_val != float('inf'):
            preco_principal_str = preco_shibata_str
        elif preco_nagumo_val < preco_shibata_val and preco_nagumo_val != float('inf'):
            preco_principal_str = preco_nagumo_str
        else:
            # Fallback se ambos forem inf ou indisponíveis
            preco_principal_str = preco_shibata_str if preco_shibata_str != "Preço indisponível" else preco_nagumo_str

        
        # Monta o objeto final
        resultados_finais.append({
            "nome": f"{nome_exibicao} ({preco_principal_str})",
            "nagumo": item['nagumo'], # Usa o link original do JSON
            "shibata": item['shibata'], # Usa o link original do JSON
            "shibata_preco_val": preco_shibata_val,
            "nagumo_preco_val": preco_nagumo_val,
            "shibata_preco_str": preco_shibata_str, 
            "nagumo_preco_str": preco_nagumo_str
        })
        
    resultados_finais.sort(key=lambda x: min(x['shibata_preco_val'], x['nagumo_preco_val']))
    
    return resultados_finais

# ----------------------------------------------------------------------
# CONFIGURAÇÃO E EXIBIÇÃO DO STREAMLIT
# ----------------------------------------------------------------------
st.set_page_config(page_title="Comparador de Preços", page_icon="🛒", layout="wide")

st.markdown("""
    <style>
        .block-container { padding-top: 0rem; }
        footer {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        .comparison-item {
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 10px;
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        .price-badge {
            font-weight: bold;
            font-size: 1.1em;
        }
        .market-link {
            text-decoration: none;
            display: block;
            padding: 5px 0;
        }
        .shibata-link { color: #880000; }
        .nagumo-link { color: #004488; }
    </style>
""", unsafe_allow_html=True)

st.markdown(f"<h6>🛒 Comparação Automática de Preços (Lendo {JSON_FILE})</h6>", unsafe_allow_html=True)
st.markdown("Itens carregados e comparados por ID/SKU.")

# Executa a comparação
with st.spinner("🔍 Buscando e comparando preços..."):
    resultados_comparacao = realizar_comparacao_automatica()

if resultados_comparacao:
    st.markdown("<h5>Resultados Comparativos (Preços Unitários Mais Baixos)</h5>", unsafe_allow_html=True)

    # Exibe os resultados na lista formatada
    for item in resultados_comparacao:
        is_shibata_melhor = item['shibata_preco_val'] <= item['nagumo_preco_val']
        
        shibata_link_style = "color: red; font-weight: bold;" if is_shibata_melhor and item['shibata_preco_val'] != float('inf') else "color: #880000;"
        nagumo_link_style = "color: red; font-weight: bold;" if not is_shibata_melhor and item['nagumo_preco_val'] != float('inf') else "color: #004488;"
        
        # Usa a string formatada que já calculamos
        shibata_preco_str_final = item['shibata_preco_str'] if item['shibata_preco_val'] != float('inf') else "N/D"
        nagumo_preco_str_final = item['nagumo_preco_str'] if item['nagumo_preco_val'] != float('inf') else "N/D"

        st.markdown(f"""
            <div class='comparison-item'>
                <div class='price-badge'>
                    {item['nome']}
                </div>
                
                <a href="{item['shibata']}" target="_blank" class='market-link shibata-link' style="{shibata_link_style}">
                    <img src="{LOGO_SHIBATA_URL}" width="20" style="vertical-align: middle; margin-right: 5px;"/> Shibata: {shibata_preco_str_final}
                </a>
                
                <a href="{item['nagumo']}" target="_blank" class='market-link nagumo-link' style="{nagumo_link_style}">
                    <img src="{LOGO_NAGUMO_URL}" width="20" style="vertical-align: middle; margin-right: 5px;"/> Nagumo: {nagumo_preco_str_final}
                </a>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<h5>Saída JSON (Estrutura Completa)</h5>", unsafe_allow_html=True)
    st.json(resultados_comparacao)

else:
    st.warning("Nenhum resultado para exibir. Verifique o arquivo JSON e as buscas.")
