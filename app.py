import streamlit as st
import pandas as pd
from google import genai
from pydantic import BaseModel
import io
import pdfplumber
from PIL import Image
import requests
from bs4 import BeautifulSoup

# --- SETUP DA PÁGINA ---
st.set_page_config(page_title="Gerar Cardápio", layout="wide")

# --- CONTROLE DE ESTADO (Para o botão Limpar) ---
# Isso cria uma "chave" que muda toda vez que você clica em Limpar, zerando os formulários
if 'reset_key' not in st.session_state:
    st.session_state.reset_key = 0

def limpar_tela():
    st.session_state.reset_key += 1

# --- ESTRUTURA DE DADOS ---
class Produto(BaseModel):
    Categoria: str
    Tipo: str
    Produto: str
    Preco: float
    Descricao: str
    Adicional: str

class Adicional(BaseModel):
    Tipo: str
    Adicional: str
    Minimo: int
    Maximo: int
    Item: str
    Preco: float
    Descricao: str

class CardapioCompleto(BaseModel):
    produtos: list[Produto]
    adicionais: list[Adicional]

# --- INTERFACE PRINCIPAL ---
# Título e Botão de Limpar alinhados
col1, col2 = st.columns([8, 1])
with col1:
    st.title("🗒️ Gerar Cardápio")
with col2:
    st.write("") # Espaçamento
    st.button("🔄 Limpar", on_click=limpar_tela, use_container_width=True)

# Obtendo a API Key dos Secrets (Oculto no código)
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ API Key não encontrada! Configure o arquivo secrets.toml.")
    api_key = None

tipo_entrada = st.selectbox(
    "Como deseja enviar o cardápio?", 
    [
        "Arquivo PDF", 
        "Imagem (Print/Foto)", 
        "Arquivo HTML (Página salva)",
        "Link de Site", 
        "Colar Texto"
    ],
    key=f"tipo_entrada_{st.session_state.reset_key}"
)

texto_cardapio = ""
imagem_cardapio = None

if tipo_entrada == "Colar Texto":
    texto_cardapio = st.text_area("Cole o texto do cardápio aqui:", height=200, key=f"texto_{st.session_state.reset_key}")

elif tipo_entrada == "Arquivo PDF":
    arquivo_pdf = st.file_uploader("Faça o upload do cardápio em PDF", type=["pdf"], key=f"pdf_{st.session_state.reset_key}")
    if arquivo_pdf:
        with pdfplumber.open(arquivo_pdf) as pdf:
            for pagina in pdf.pages:
                ext = pagina.extract_text()
                if ext:
                    texto_cardapio += ext + "\n"
        st.success("✅ PDF lido com sucesso!")

elif tipo_entrada == "Imagem (Print/Foto)":
    arquivo_img = st.file_uploader("Faça o upload da imagem", type=["jpg", "jpeg", "png"], key=f"img_{st.session_state.reset_key}")
    if arquivo_img:
        imagem_cardapio = Image.open(arquivo_img)
        st.image(imagem_cardapio, caption="Passe o mouse na imagem e clique nas setas no canto superior direito para ampliar", width=300)
        st.success("✅ Imagem pronta para análise!")

elif tipo_entrada == "Arquivo HTML (Página salva)":
    st.info("💡 Dica: Acesse o iFood/AnotaAi do cliente, aperte Ctrl+S para salvar a página no seu computador e faça o upload do arquivo .html aqui.")
    arquivo_html = st.file_uploader("Faça o upload do arquivo HTML", type=["html", "htm"], key=f"html_{st.session_state.reset_key}")
    if arquivo_html:
        sopa = BeautifulSoup(arquivo_html.read(), 'html.parser')
        texto_cardapio = sopa.get_text(separator='\n', strip=True)
        st.success("✅ Arquivo HTML lido com sucesso! ⚠️ Importante: Adicionais podem ter sido bloqueados na leitura.")

elif tipo_entrada == "Link de Site":
    st.info("💡 Dica: Se o site bloquear a leitura (como iFood, AnotaAi etc), use a opção 'Upload de Arquivo HTML'.")
    url = st.text_input("Cole o link (URL) do cardápio aqui:", key=f"link_{st.session_state.reset_key}")
    if url:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            resposta = requests.get(url, headers=headers, timeout=10)
            resposta.raise_for_status()
            
            sopa = BeautifulSoup(resposta.text, 'html.parser')
            texto_extraido = sopa.get_text(separator='\n', strip=True)
            
            if len(texto_extraido) < 150:
                st.error("❌ O site retornou muito pouco texto. Provavelmente possui bloqueio. Por favor, salve a página como .html, tire prints ou salve como PDF.")
            else:
                texto_cardapio = texto_extraido
                st.success("✅ Texto do site extraído com sucesso!")
        except Exception as e:
            st.error(f"❌ Erro ao acessar o link: {e}")

# --- PROCESSAMENTO ---
if st.button("Gerar Planilhas"):
    if not api_key:
        st.error("⚠️ A API Key não está configurada nos Secrets.")
    elif not texto_cardapio.strip() and imagem_cardapio is None:
        st.warning("⚠️ Por favor, forneça o cardápio (PDF, Imagem, HTML, Link ou Texto).")
    else:
        with st.spinner("Analisando o cardápio..."):
            try:
                client = genai.Client(api_key=api_key)

                prompt_sistema = """
                Você é um especialista em estruturação de dados de sistemas de delivery para a empresa Saipos.
                Sua tarefa é extrair as informações do cardápio fornecido e estruturar rigorosamente conforme o schema JSON exigido, gerando as planilhas de Produtos e Adicionais.

                [1. REGRAS DA TABELA DE PRODUTOS]
                - Tipo: DEVE ser exatamente 'Comida', 'Bebida' ou 'Pizza' (ex: 'Pastel sabor pizza' = 'Comida').
                - Preço: Use sempre ponto (.) para decimais. SE o produto não possuir preço direto no cardápio (ou se o preço depender do sabor escolhido), DEIXE O PREÇO ZERADO (0.00) e aplique os valores na tabela de Adicionais.
                - Descrição: Se não houver, deixe "".

                [2. REGRAS DE NOMENCLATURA NA IMPRESSÃO (MUITO IMPORTANTE)]
                Para evitar confusão na cozinha, o nome do produto deve ser claro. 
                CONCATENE o nome da categoria com o nome do produto APENAS nestes dois casos:
                A) Ingredientes genéricos que existem em várias categorias: Categoria 'Pastéis' e produto 'Carne' -> vira 'Pastel de Carne'.
                B) Recipientes, porções ou tamanhos: Categoria 'Doses' e produto 'Aperol' -> vira 'Dose Aperol'. Categoria 'Taças' e produto 'Vinho' -> vira 'Taça de Vinho'. Categoria 'Combos' e produto 'Top' -> vira 'Combo Top'.
                Se for um nome único e sem ambiguidade (ex: 'X-Bacon', 'Coca-Cola 2L', 'Smash Burger'), mantenha o nome original.

                [3. REGRAS DA TABELA DE ADICIONAIS E CHAVE DE LIGAÇÃO]
                - Tipo do Adicional: DEVE ser exatamente 'Outros', 'Sabor Pizza', 'Borda Pizza' ou 'Massa Pizza'. (Atenção: sabores de pastel ou hambúrguer são 'Outros').
                - Chave de Ligação (Coluna Adicional): Se um produto tem adicionais ou exige escolha de sabor, crie uma palavra-chave no campo 'Adicional' do Produto (ex: 'Sabores Pastel'). Use essa EXATA mesma palavra na coluna 'Adicional' da segunda tabela para linkar os itens.
                - Mínimo e Máximo: Respeite o cardápio. Se for uma escolha obrigatória de sabor onde o preço está atrelado ao sabor, o Produto deve ter preço 0.00 e o Adicional deve ter mínimo 1.

                [4. REGRAS ESPECÍFICAS PARA PIZZAS (ATENÇÃO MÁXIMA)]
                A estrutura de cadastro de Pizzas difere do resto do cardápio. Siga rigorosamente estas etapas:

                A) TABELA DE PRODUTOS (A "Casca" da Pizza):
                - Categoria: Obrigatoriamente "Pizzas".
                - Tipo: Obrigatoriamente "Pizza".
                - Produto: Identifique e utilize o Tamanho/Formato da pizza (Ex: "Pizza Pequena", "Pizza Grande", "Pizza Doce Média").
                - Preço: DEVE SER SEMPRE 0.00. O valor será cobrado nos sabores.
                - Descrição: Se o cardápio não informar, use "Escolha os sabores da sua pizza".
                - Adicional (Chaves de Ligação): Crie a chave para os sabores (Ex: "Sabores Pizza Grande"). SE o cardápio tiver opções de Bordas Recheadas ou Massas, crie as chaves também e separe por vírgula. Exemplo: "Sabores Pizza Grande, Bordas, Massas".

                B) TABELA DE ADICIONAIS (Os Sabores):
                - Tipo: Estritamente "Sabor Pizza".
                - Adicional: Use a chave de ligação correspondente (Ex: "Sabores Pizza Grande").
                - Mínimo: Sempre pelo menos 1 (pois o cliente precisa escolher o sabor).
                - Máximo: Extraia do cardápio o limite de sabores permitidos para aquele tamanho. (Ex: se a pizza grande aceita "até 3 sabores" ou "meio a meio", o Máximo é 3 ou 2. Se o cardápio não informar, assuma 1).
                - Preço: O valor do sabor para o tamanho correspondente.
                
                C) TABELA DE ADICIONAIS (Bordas e Massas):
                - Se houver opções de borda recheada, o Tipo DEVE ser "Borda Pizza".
                - Se houver opções de massas especiais, o Tipo DEVE ser "Massa Pizza".
                - Mínimo: Geralmente 0 (opcional), a menos que o cardápio exija.
                - Máximo: Geralmente 1.
                """

                conteudo_ia = [prompt_sistema]
                if imagem_cardapio:
                    conteudo_ia.append(imagem_cardapio)
                else:
                    conteudo_ia.append(texto_cardapio)

                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=conteudo_ia,
                    config={
                        'response_mime_type': 'application/json',
                        'response_schema': CardapioCompleto,
                        'temperature': 0.1
                    },
                )

                cardapio = response.parsed

                df_produtos = pd.DataFrame([p.model_dump() for p in cardapio.produtos])
                df_adicionais = pd.DataFrame([a.model_dump() for a in cardapio.adicionais])

                st.success("✅ Dados estruturados com sucesso!")

                st.subheader("Planilha de Produtos")
                st.dataframe(df_produtos)

                st.subheader("Planilha de Adicionais")
                st.dataframe(df_adicionais)

                # --- GERA EXCEL ---
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_produtos.to_excel(writer, sheet_name='Produtos', index=False)
                    df_adicionais.to_excel(writer, sheet_name='Adicionais', index=False)

                st.download_button(
                    label="📥 Baixar Planilhas em Excel",
                    data=buffer.getvalue(),
                    file_name="cardapio_saipos.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            except Exception as e:
                st.error(f"Erro ao processar com a IA: {e}")