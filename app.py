from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
import os
import httpx
from datetime import datetime, date
import time
import uuid  # Para garantir unicidade matemática e imutabilidade dos relatórios
from dotenv import load_dotenv
import json
import urllib.parse
from pipeline.reader import ingest
from pipeline.metrics import calcular_metricas
from pipeline.report import gerar_relatorio
from pipeline.sender import main_function, enviar_mensagem

# Carrega as variáveis de ambiente declaradas no ficheiro .env
load_dotenv()

# Definição de templates de texto estáticos para interação com o utilizador
MENU = """Ola! Sou o InsightZone.
Modo atual: {frequencia}

1. Enviar ficheiro de vendas in formato CSV, Excel ou PDF para receber o relatorio.
2. Ver relatorio anterior
3. Resumo rapido
4. Top 5 produtos"""

AJUDA = """Comandos disponiveis:
- Envia um ficheiro CSV, Excel ou PDF para receber o teu relatorio
- 'relatorio' ou '2' — ver ultimo relatorio
- 'resumo' ou '3' — 3 KPIs rapidos
- 'top' ou '4' — top 5 produtos"""


# ── JSON HELPERS (PERSISTÊNCIA LOCAL DE CLIENTES COM HIGIENIZAÇÃO) ───────────

def limpar_numero(phone_number: str) -> str:
    """Garante que o número contém apenas dígitos, eliminando o símbolo '+' ou espaços."""
    if not phone_number:
        return ""
    return str(phone_number).replace("+", "").strip()

def carregar_todos_clientes() -> list:
    """Carrega a base de dados local em JSON. Se não existir, cria um ficheiro vazio."""
    if not os.path.exists("clientes.json"):
        with open("clientes.json", "w", encoding="utf-8") as f:
            json.dump([], f)
    with open("clientes.json", "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def guardar_clientes(clientes: list):
    """Grava as atualizações do estado dos clientes de volta no ficheiro JSON."""
    with open("clientes.json", "w", encoding="utf-8") as f:
        json.dump(clientes, f, ensure_ascii=False, indent=2)

def carregar_cliente(phone_number: str) -> dict | None:
    """Procura e retorna o perfil de um cliente específico com base no número higienizado."""
    numero_limpo = limpar_numero(phone_number)
    for cliente in carregar_todos_clientes():
        if limpar_numero(cliente.get("numero")) == numero_limpo:
            return cliente
    return None


# ── MÁQUINA DE ESTADOS DO ONBOARDING ──────────────────────────────────────────

def tratar_onboarding(phone_number: str, texto: str, cliente: dict):
    """
    Gere o fluxo passo-a-passo de boas-vindas do cliente (Onboarding).
    Salva o progresso no JSON e envia a próxima pergunta correspondente.
    """
    clientes = carregar_todos_clientes()
    passo = cliente["onboarding_passo"]
    numero_limpo = limpar_numero(phone_number)

    if passo == 1:
        for c in clientes:
            if limpar_numero(c.get("numero")) == numero_limpo:
                c["nome"] = texto
                c["onboarding_passo"] = 2
                break
        guardar_clientes(clientes)
        enviar_mensagem(numero_limpo, "Que tipo de negocio tens?\n1. Servicos\n2. Retalho\n3. Agropecuaria\n4. Outro")

    elif passo == 2:
        tipos = {"1": "servicos", "2": "retalho", "3": "agropecuaria", "4": "outro"}
        negocio = tipos.get(texto.strip(), texto.strip())
        for c in clientes:
            if limpar_numero(c.get("numero")) == numero_limpo:
                c["negocio"] = negocio
                c["onboarding_passo"] = 3
                break
        guardar_clientes(clientes)
        enviar_mensagem(numero_limpo, "Qual e o teu email para relatorios de backup? (envia 'skip' para ignorar)")

    elif passo == 3:
        email = None if texto.strip().lower() == "skip" else texto.strip()
        for c in clientes:
            if limpar_numero(c.get("numero")) == numero_limpo:
                c["email"] = email
                c["onboarding_passo"] = 4
                break
        guardar_clientes(clientes)
        enviar_mensagem(numero_limpo, "Como preferes enviar os teus dados e receber os relatorios?\n1. Semanalmente\n2. Mensalmente")

    elif passo == 4:
        freq_map = {"1": "semanal", "2": "mensal"}
        frequencia = freq_map.get(texto.strip(), "semanal")
        for c in clientes:
            if limpar_numero(c.get("numero")) == numero_limpo:
                c["frequencia"] = frequencia
                c["onboarding_passo"] = 0
                break
        guardar_clientes(clientes)
        enviar_mensagem(numero_limpo, f"Perfeito! Onboarding completo. Configurado para envio {frequencia}.\nEnvia agora o teu ficheiro CSV, Excel ou PDF com os teus dados de vendas.")


# ── TAREFAS ASSÍNCRONAS EM SEGUNDO PLANO (BACKGROUND TASKS) ────────────────────

def gerar_relatorio_background(phone_number: str, filepath: str, nome_cliente: str, frequencia_atual: str):
    """
    Executa o pipeline pesado de dados fora do fluxo principal da rota HTTP.
    """
    try:
        numero_limpo = limpar_numero(phone_number)
        df = ingest(filepath)
        metricas = calcular_metricas(df, frequencia_cliente=frequencia_atual)
        
        timestamp_label = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico = uuid.uuid4().hex[:6]
        pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"
        
        pdf_path = gerar_relatorio(metricas, nome_negocio=nome_cliente, semana_label=pdf_filename_limpo)
        
        base_url = os.getenv("BASE_URL")
        pdf_url = f"{base_url}/reports/{urllib.parse.quote(pdf_filename_limpo)}"
        
        msg_envio = f"Aqui tens o teu relatório {frequencia_atual} atualizado:"
        main_function(numero_limpo, pdf_url, pdf_filename_limpo, mensagem=msg_envio)
    except Exception as e:
        print(f"Erro ao processar relatório por texto em background: {e}")


def processar_ficheiro(phone_number: str, document_id: str, filename: str):
    """
    Descarrega o documento da API Graph da Meta v25.0, roda o pipeline analítico
    e envia o PDF estratégico de volta ao utilizador de forma síncrona/segura.
    """
    try:
        token = os.getenv("META_ACCESS_TOKEN")
        numero_limpo = limpar_numero(phone_number)

        # Atualizado para v25.0 correspondente ao teu painel Meta developers
        meta_url = f"https://graph.facebook.com/v25.0/{document_id}"
        r = httpx.get(meta_url, headers={"Authorization": f"Bearer {token}"})
        download_url = r.json().get("url")

        if not download_url:
            print(f"Erro: Não foi possível obter a URL de download da Meta. Resposta: {r.text}")
            return

        ficheiro = httpx.get(download_url, headers={"Authorization": f"Bearer {token}"})
        os.makedirs("data/uploads", exist_ok=True)
        
        timestamp_upload = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename_seguro = f"{timestamp_upload}_{filename.replace(' ', '_')}"
        filepath = f"data/uploads/{filename_seguro}"
        
        with open(filepath, "wb") as f:
            f.write(ficheiro.content)

        df = ingest(filepath)
        cliente = carregar_cliente(numero_limpo)
        frequencia = cliente.get("frequencia", "semanal") if cliente else "semanal"
        
        metricas = calcular_metricas(df, frequencia_cliente=frequencia)
        nome_empresa = cliente["nome"] if cliente and cliente.get("nome") else "O meu negocio"
        
        timestamp_label = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico = uuid.uuid4().hex[:6]
        pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"
        
        pdf_path = gerar_relatorio(metricas, nome_negocio=nome_empresa, semana_label=pdf_filename_limpo)

        base_url = os.getenv("BASE_URL")
        pdf_url = f"{base_url}/reports/{urllib.parse.quote(pdf_filename_limpo)}"

        msg_envio = f"O teu relatório {frequencia} está pronto:"
        main_function(numero_limpo, pdf_url, pdf_filename_limpo, mensagem=msg_envio)

        clientes = carregar_todos_clientes()
        for c in clientes:
            if limpar_numero(c.get("numero")) == numero_limpo:
                c["ultimo_ficheiro"] = filepath
                break
        guardar_clientes(clientes)
        print("Pipeline executado com sucesso através de upload de ficheiro!")
    except Exception as e:
        print(f"Erro ao processar ficheiro em background: {e}")


# ── MOTOR DE COMANDOS DE TEXTO ────────────────────────────────────────────────

def tratar_comando(phone_number: str, texto: str, background_tasks: BackgroundTasks):
    """
    Roteador de intenções de texto. Identifica comandos analíticos base do chatbot.
    """
    texto_original = texto
    texto = texto.lower().strip()
    numero_limpo = limpar_numero(phone_number)
    cliente = carregar_cliente(numero_limpo)

    if not cliente:
        novo_cliente = {
            "numero": numero_limpo,
            "nome": None,
            "negocio": None,
            "email": None,
            "ultimo_ficheiro": None,
            "historico": [],
            "onboarding_passo": 1,
            "frequencia": "semanal"
        }
        clientes = carregar_todos_clientes()
        clientes.append(novo_cliente)
        guardar_clientes(clientes)
        enviar_mensagem(numero_limpo, "Bem-vindo ao InsightZone! Qual e o nome do teu negocio?")
        return

    if cliente["onboarding_passo"] > 0:
        tratar_onboarding(numero_limpo, texto_original, cliente)
        return

    frequencia_atual = cliente.get("frequencia", "semanal")

    if texto in ["ola", "olá", "oi", "hello", "hi", "bom dia", "boa tarde", "boa noite"]:
        enviar_mensagem(numero_limpo, MENU.format(frequencia=frequencia_atual.upper()))
        return

    if texto in ["relatorio", "relatório", "2"]:
        if not cliente.get("ultimo_ficheiro"):
            enviar_mensagem(numero_limpo, "Ainda nao tens nenhum relatorio. Envia um ficheiro CSV, Excel ou PDF para comecar.")
            return
        
        enviar_mensagem(numero_limpo, "A preparar o teu documento estratégico. Aguarda um momento...")
        background_tasks.add_task(
            gerar_relatorio_background, 
            numero_limpo, 
            cliente["ultimo_ficheiro"], 
            cliente["nome"], 
            frequencia_atual
        )
        return

    if texto in ["resumo", "rapido", "rápido", "3"]:
        if not cliente.get("ultimo_ficheiro"):
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        df = ingest(cliente["ultimo_ficheiro"])
        metricas = calcular_metricas(df, frequencia_cliente=frequencia_atual)
        
        if frequencia_atual == "mensal":
            resumo = (
                f"Resumo do Mes ({metricas['mes_nome']}):\n"
                f"Total de vendas: {metricas['total_mensal']:.2f}\n"
                f"Total de transacoes: {metricas['transacoes_mensal']}\n"
                f"Melhor dia: {metricas['melhor_dia_mes']}"
            )
        else:
            resumo = (
                f"Resumo da semana:\n"
                f"Total de vendas: {metricas['total']:.2f}\n"
                f"Total de transacoes: {metricas['total_transacoes']}\n"
                f"Melhor dia: {metricas['melhor_dia']}"
            )
        enviar_mensagem(numero_limpo, resumo)
        return

    if texto in ["top", "top cinco", "top 5", "4"]:
        if not cliente.get("ultimo_ficheiro"):
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        df = ingest(cliente["ultimo_ficheiro"])
        metricas = calcular_metricas(df, frequencia_cliente=frequencia_atual)
        top = metricas["top_produtos_mes"] if frequencia_atual == "mensal" else metricas["top_produtos"]
        linhas = [f"{i+1}. {produto} — {int(qty)} unidades" for i, (produto, qty) in enumerate(top.items())]
        enviar_mensagem(numero_limpo, f"Top 5 produtos ({frequencia_atual}):\n" + "\n".join(linhas))
        return

    enviar_mensagem(numero_limpo, AJUDA)


# ── FASTAPI APPLICATION E ENDPOINTS ───────────────────────────────────────────

app = FastAPI()

app.mount("/reports", StaticFiles(directory="data/gold"), name="reports")


@app.get("/")
def read_root():
    return {"status": "healthy", "service": "InsightZone"}


@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge")
):
    """Rota de validação obrigatória exigida pela Meta."""
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("WEBHOOK_VERIFY_TOKEN"):
        return Response(content=str(hub_challenge), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token inválido")


@app.post("/webhook")
def receber_webhook(payload: dict, background_tasks: BackgroundTasks):
    """
    Ponto de entrada central de eventos do WhatsApp Cloud API.
    """
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        
        if "messages" not in value:
            return Response(content="OK", status_code=200)
            
        mensagem = value["messages"][0]
        
        # Correção central: O número passa por limpeza assim que entra no webhook
        phone_number = limpar_numero(mensagem.get("from"))
        tipo = mensagem.get("type")
        
    except (KeyError, IndexError, TypeError):
        return Response(content="OK", status_code=200)

    if tipo == "text":
        texto = mensagem.get("text", {}).get("body", "")
        tratar_comando(phone_number, texto, background_tasks)

    elif tipo == "document":
        cliente = carregar_cliente(phone_number)
        if not cliente or cliente.get("onboarding_passo", 0) > 0:
            tratar_comando(phone_number, "novo", background_tasks)
            return Response(content="OK", status_code=200)
            
        doc_data = mensagem.get("document", {})
        document_id = doc_data.get("id")
        filename = doc_data.get("filename", f"vendas_{int(datetime.now().timestamp())}.xlsx")
        
        if document_id:
            background_tasks.add_task(processar_ficheiro, phone_number, document_id, filename)

    return Response(content="OK", status_code=200)