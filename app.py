import streamlit as st
import pandas as pd
from google import genai
from pydantic import BaseModel, Field
import io
import pdfplumber
from PIL import Image
import requests
from bs4 import BeautifulSoup

# BASE
st.set_page_config(page_title="Gerar Cardápio", layout="wide", initial_sidebar_state="collapsed")

if 'reset_key' not in st.session_state:
    st.session_state.reset_key = 0

def limpar_tela():
    st.session_state.reset_key += 1
    if 'ordem_imagens' in st.session_state:
        del st.session_state['ordem_imagens']

# ESTRUTURA DE DADOS (PYDANTIC)
class Produto(BaseModel):
    Categoria: str = Field(description="Categoria do produto")
    Tipo: str = Field(description="Deve ser 'Comida', 'Bebida' ou 'Pizza'")
    Produto: str = Field(description="Nome do produto")
    Preco: str = Field(description="Preço no formato XX.XX")
    Descricao: str = Field(description="Descrição, se houver")
    Adicional: str = Field(description="Chaves de ligação separadas por vírgula")

class Adicional(BaseModel):
    Tipo: str = Field(description="Deve ser 'Sabor Pizza', 'Borda Pizza', 'Massa Pizza' ou 'Outro'")
    Adicional: str = Field(description="Chave de ligação idêntica à da aba Produtos")
    Nome: str = Field(description="Nome da opção (Ex: Calabresa, Borda de Catupiry)")
    Descricao: str = Field(description="Descrição da opção, se houver")
    Preco: str = Field(description="Preço no formato XX.XX")
    Minimo: int = Field(description="Quantidade mínima")
    Maximo: int = Field(description="Quantidade máxima")

class CardapioCompleto(BaseModel):
    raciocinio_interno: str
    produtos: list[Produto]
    adicionais: list[Adicional]

# INTERFACE PRINCIPAL
col1, col2 = st.columns([8, 1])
with col1:
    st.title("🗒️ Gerar Cardápio")
with col2:
    st.write("") 
    st.button("🔄 Limpar", on_click=limpar_tela, use_container_width=True)

# TIPO DE ESTABELECIMENTO
st.markdown("### 🏪 Perfil do Negócio")
lista_tipos = [
    "Selecione...", 
    "Açaí", "Bar", "Buffet por Kg", "Marmitas", "Cafeteria", 
    "Confeitaria/Doceria/Padaria", "Conveniencia", "FastFood", 
    "Lanchonete", "Mercado", "Pizzaria", "Restaurante padrão", "Sushi"
]
tipo_negocio = st.selectbox("Selecione o tipo de restaurante (Obrigatório):", lista_tipos, key=f"nicho_{st.session_state.reset_key}")
st.markdown("---")

# MENU LATERAL MINIMIZADO
with st.sidebar:
    st.header("⚙️ API")
    st.info("Alterne a chave de conexão caso o limite do Google seja atingido.")
    chave_selecionada = st.radio(
        "Selecione a Chave de API:",
        ["Chave Padrão", "Chave Reserva"],
        index=0
    )

# DEFINIÇÃO DA CHAVE API
nome_secret = "GEMINI_API_KEY" if chave_selecionada == "Chave Padrão" else "GEMINI_API_KEY_RESERVA"

try:
    api_key = st.secrets[nome_secret]
except KeyError:
    st.error(f"⚠️ API Key não encontrada! Configure a variável '{nome_secret}' no arquivo secrets.toml.")
    api_key = None

# INSTRUÇÕES MANUAIS
st.markdown("### 🧠 Contexto do Cardápio (Opcional)")
contexto_manual = st.text_area(
    "Digite regras específicas para este cardápio (Ex: 'A pizza grande aceita 3 sabores e não mistura doce com salgada', 'Ignore a categoria de promoções', etc):", 
    height=80, 
    key=f"contexto_{st.session_state.reset_key}"
)

st.markdown("### 📎 Envio do Cardápio")
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
imagens_cardapio = [] 

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
        if not texto_cardapio.strip():
            st.error("❌ O sistema não encontrou texto neste PDF. Isso geralmente acontece quando o arquivo é um 'PDF de Imagem'. Por favor, tire prints do cardápio e envie pela opção 'Imagem (Print/Foto)'.")
        else:
            st.success("✅ PDF lido e texto extraído com sucesso! ⚠️ Em caso de imagens anexadas no PDF, pode ocorrer de não terem sido lidas. Revise!")

elif tipo_entrada == "Imagem (Print/Foto)":
    st.info("💡 Dica: Se a ordem estiver incorreta, use as setas abaixo das imagens para ajustá-la.")
    
    arquivos_img = st.file_uploader("Faça o upload de até 5 imagens", type=["jpg", "jpeg", "png"], accept_multiple_files=True, key=f"img_{st.session_state.reset_key}")
    
    if arquivos_img:
        if len(arquivos_img) > 5:
            st.warning("⚠️ Você enviou mais de 5 imagens. Apenas as 5 primeiras serão analisadas.")
            arquivos_img = arquivos_img[:5] 
        
        # ORDENAÇÃO
        if 'ordem_imagens' not in st.session_state or len(st.session_state.ordem_imagens) != len(arquivos_img):
            st.session_state.ordem_imagens = list(range(len(arquivos_img))) 
            
        st.markdown("**Ordem de leitura da IA:**")
        
        tamanho_colunas = [2, 2, 2, 2, 2, 4] 
        
        # IMAGENS
        cols_img = st.columns(tamanho_colunas) 
        
        for visual_idx, real_idx in enumerate(st.session_state.ordem_imagens):
            img_file = arquivos_img[real_idx]
            
            with cols_img[visual_idx]: 
                img = Image.open(img_file)
                imagens_cardapio.append(img)
                st.image(img, use_container_width=True, caption=f"Pág {visual_idx+1}") 
                
        # BOTÕES
        cols_btn = st.columns(tamanho_colunas)
        
        for visual_idx, real_idx in enumerate(st.session_state.ordem_imagens):
            with cols_btn[visual_idx]:
                espaco_esq, btn_esq, btn_dir, espaco_dir = st.columns([1, 1.2, 1.2, 1])
                
                with btn_esq:
                    if st.button("❮", key=f"left_{visual_idx}_{st.session_state.reset_key}", disabled=(visual_idx == 0), use_container_width=True):
                        st.session_state.ordem_imagens[visual_idx], st.session_state.ordem_imagens[visual_idx-1] = \
                        st.session_state.ordem_imagens[visual_idx-1], st.session_state.ordem_imagens[visual_idx]
                        st.rerun()
                        
                with btn_dir:
                    if st.button("❯", key=f"right_{visual_idx}_{st.session_state.reset_key}", disabled=(visual_idx == len(arquivos_img) - 1), use_container_width=True):
                        st.session_state.ordem_imagens[visual_idx], st.session_state.ordem_imagens[visual_idx+1] = \
                        st.session_state.ordem_imagens[visual_idx+1], st.session_state.ordem_imagens[visual_idx]
                        st.rerun()
        
        st.success(f"✅ {len(imagens_cardapio)} imagem(ns) pronta(s) para análise na sequência acima!")

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
                st.success("✅ Texto do site extraído com sucesso! ⚠️ Importante: Adicionais podem ter sido bloqueados na leitura.")
        except Exception as e:
            st.error(f"❌ Erro ao acessar o link: {e}")

# PROCESSAMENTO
if st.button("Gerar Planilhas"):
    if tipo_negocio == "Selecione...":
        st.error("⚠️ Atenção: É obrigatório selecionar o 'Tipo de restaurante' no topo da página antes de continuar.")
    elif not api_key:
        st.error("⚠️ A API Key não está configurada nos Secrets.")
    elif not texto_cardapio.strip() and len(imagens_cardapio) == 0:
        st.warning("⚠️ Por favor, forneça o cardápio (PDF, Imagem, HTML, Link ou Texto).")
    else:
        with st.spinner(f"Analisando com a {chave_selecionada}..."):
            try:
                client = genai.Client(api_key=api_key)

                prompt_sistema = """
                Você é um especialista em estruturação de dados de sistemas de delivery para a empresa de sistema para restaurante.
                Sua tarefa é extrair as informações do cardápio fornecido e estruturar rigorosamente conforme o schema JSON exigido.

                [REGRA DE CARDÁPIO ÚNICO E CONSISTÊNCIA]
                ATENÇÃO: Você pode receber múltiplas imagens ou textos. Considere TUDO como um ÚNICO cardápio contínuo. Mantenha a consistência absoluta do início ao fim. O critério usado para classificar um produto na página 1 DEVE ser o mesmo na página 3.
                
                MUITO IMPORTANTE: Utilize o campo 'raciocinio_interno' para pensar passo a passo. Analise o contexto geral (todas as imagens) ANTES de preencher as listas.

                [1. REGRAS DA TABELA DE PRODUTOS]
                - Tipo: DEVE ser exatamente 'Comida', 'Bebida' ou 'Pizza'.
                - Preço: Use sempre ponto (.) para decimais. GARANTA duas casas decimais. Nunca herde ou copie o preço do vizinho. Se depender de escolha, preço é 0.00.
                - Descrição: Se não houver, deixe VAZIO (""). Não invente descrições genéricas.
                - VARIAÇÕES x ADICIONAIS: NÃO agrupe produtos distintos por nomes semelhantes. Ex: 'Água com gás' e 'Água sem gás' são PRODUTOS SEPARADOS. Adicionais são para acompanhamentos (ex: molhos, bordas).

                [2. REGRAS DE NOMENCLATURA]
                - CONCATENE categoria com produto APENAS em: Nomes genéricos (ex: 'Pastel de Carne') ou Recipientes (ex: 'Dose Aperol').
                - Nomes próprios ('X-Bacon') não concatenar.

                [3. REGRAS DA TABELA DE ADICIONAIS E CHAVES DE LIGAÇÃO]
                - Tipo: 'Outro', 'Sabor Pizza', 'Borda Pizza' ou 'Massa Pizza'. 
                - Chaves de Ligação: Conecte coluna 'Adicional' do Produto com a segunda tabela.
                - REAPROVEITAMENTO (ANTI-DUPLICAÇÃO): Se vários produtos compartilham EXATAMENTE o mesmo grupo de adicionais (mesmas opções, preços e limites min/max), NÃO DUPLIQUE o grupo na tabela de Adicionais. Crie a lista de opções apenas UMA VEZ com um nome genérico (Ex: 'Acompanhamentos Padrão', 'Escolha seu Molho') e use essa MESMA chave na coluna 'Adicional' de todos os produtos correspondentes.
                - MÚLTIPLOS ADICIONAIS (REGRA DA VÍRGULA E ESPAÇO): Se o produto possuir mais de um grupo de opções, você DEVE colocar TODAS as chaves na coluna 'Adicional' separadas por vírgula seguida de UM ESPAÇO. (Exemplo CERTO: "Sabores Pizza Padrão, Escolha de Borda". Exemplo ERRADO: "Sabores,Bordas").
                - ESCOLHAS OCULTAS: Se descrição tiver "OU" (ex: "fritas ou salada"), crie chave e coloque na Tabela de Adicionais com Mínimo 1.

                [4. REGRAS ESPECÍFICAS PARA PIZZAS (BLINDAGEM TOTAL E PROIBIÇÃO)]
                - GATILHO DE ATIVAÇÃO: Aplique estas regras a QUALQUER categoria que seja de pizzas, independente do nome no cardápio.
                - PROIBIÇÃO ABSOLUTA: Nomes de SABORES de pizza (ex: Calabresa, Marguerita) JAMAIS podem ser listados como 'Produtos' na tabela principal. Eles pertencem EXCLUSIVAMENTE à tabela de 'Adicionais'.
                - SEPARAÇÃO DOCE/SALGADA: Se o usuário informar nas instruções manuais que "não mistura doce com salgada", você DEVE dividir as Cascas. Crie produtos separados (Ex: "Pizza Grande Salgada" e "Pizza Grande Doce") e chaves separadas (Ex: "Sabores Salgados Pizza Grande" e "Sabores Doces Pizza Grande").
                
                Siga EXATAMENTE a estrutura de "Casca e Sabores":

                A) TABELA DE PRODUTOS (A "Casca"):
                - Você DEVE criar apenas os TAMANHOS como produtos (Ex: "Pizza Pequena", "Pizza Grande Salgada"). 
                - Categoria: "Pizzas". Tipo: "Pizza".
                - Preço: OBRIGATORIAMENTE "0.00". O valor está nos sabores.
                - Descrição: DEIXE VAZIO (""). Em hipótese alguma escreva textos genéricos como "Escolha um sabor".
                - Adicional (Chaves de Ligação): Crie a chave para os sabores. Separe OBRIGATORIAMENTE por vírgula e UM ESPAÇO se houver bordas (Ex: "Sabores Salgados Pizza Grande, Escolha sua Borda").

                B) TABELA DE ADICIONAIS (Os Sabores):
                - Tipo: Estritamente "Sabor Pizza".
                - Adicional: A mesma chave criada na Casca.
                - Mínimo: 1. 
                - Máximo: Limite de sabores permitidos para aquele tamanho (Assuma 1 se não houver).
                - Preço: Valor específico do sabor.
                
                C) TABELA DE ADICIONAIS (Bordas e Massas):
                - Tipo: "Borda Pizza" ou "Massa Pizza". 
                - Mínimo: 0 (pois é opcional). 
                - Máximo: OBRIGATORIAMENTE 1 pelo menos (NUNCA coloque 0, senão o cliente não consegue selecionar).
                - NOME DA OPÇÃO (MUITO IMPORTANTE): Adicione OBRIGATORIAMENTE o prefixo "Borda de " ou "Massa " no nome da opção. (Exemplo: em vez de extrair apenas "Cheddar" ou "Catupiry", escreva "Borda de Cheddar" e "Borda de Catupiry". Em vez de "Pan", escreva "Massa Pan"). Isso evita que a cozinha confunda a borda com um sabor de pizza.
                """

                if contexto_manual.strip():
                    prompt_sistema += f"\n\n[INSTRUÇÕES MANUAIS ESPECÍFICAS PARA ESTE CLIENTE]\n{contexto_manual}\nVocê DEVE seguir estas instruções acima de tudo."

                conteudo_ia = [prompt_sistema]
                if len(imagens_cardapio) > 0:
                    conteudo_ia.extend(imagens_cardapio)
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
                # Espaço após todas as vírgulas na coluna Adicional
                df_produtos['Adicional'] = df_produtos['Adicional'].str.replace(r',\s*', ', ', regex=True)
                df_adicionais = pd.DataFrame([a.model_dump() for a in cardapio.adicionais])

                if not df_produtos.empty:
                    ordem_categorias = df_produtos['Categoria'].unique()
                    df_produtos['Categoria'] = pd.Categorical(df_produtos['Categoria'], categories=ordem_categorias, ordered=True)
                    df_produtos = df_produtos.sort_values(by=['Categoria'], kind='mergesort').reset_index(drop=True)
                
                if not df_adicionais.empty:
                    ordem_chaves = df_adicionais['Adicional'].unique()
                    df_adicionais['Adicional'] = pd.Categorical(df_adicionais['Adicional'], categories=ordem_chaves, ordered=True)
                    df_adicionais = df_adicionais.sort_values(by=['Tipo', 'Adicional'], kind='mergesort').reset_index(drop=True)
                
                    colunas_corretas = ['Tipo', 'Adicional', 'Minimo', 'Maximo', 'Nome', 'Preco', 'Descricao']
                    df_adicionais = df_adicionais[colunas_corretas]

                st.success("✅ Dados estruturados e ordenados com sucesso!")

                st.subheader("Planilha de Produtos")
                st.dataframe(df_produtos)

                st.subheader("Planilha de Adicionais")
                st.dataframe(df_adicionais)

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
                mensagem_erro = str(e)
                if "429" in mensagem_erro or "RESOURCE_EXHAUSTED" in mensagem_erro or "quota" in mensagem_erro.lower():
                    st.warning("⏳ **Limite do Google atingido.**\n\nAbra o menu lateral esquerdo (clique na setinha '>'), mude para a 'Chave Reserva' e tente novamente!")
                else:
                    st.error(f"❌ Erro inesperado ao processar com a IA: {e}")
