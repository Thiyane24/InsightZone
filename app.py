from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Response
from fastapi.staticfiles import StaticFiles
import os
import httpx
from datetime import datetime, date
import time
import uuid  # INCLUSÃO: Para garantir unicidade matemática e imutabilidade dos relatórios
from dotenv import load_dotenv
import json
import urllib.parse
from pipeline.reader import ingest
from pipeline.metrics import calcular_metricas
from pipeline.report import gerar_relatorio
from pipeline.sender import main_function, enviar_mensagem

# Carrega as variáveis de ambiente declaradas no ficheiro .env (ex: tokens, URLs base)
load_dotenv()

# Definição de templates de texto estáticos para interação com o utilizador no WhatsApp
MENU = """Ola! Sou o InsightZone.
Modo atual: {frequencia}

1. Enviar ficheiro de vendas em formato CSV, Excel ou PDF para receber o relatorio.
2. Ver relatorio anterior
3. Resumo rapido
4. Top 5 produtos"""

AJUDA = """Comandos disponiveis:
- Envia um ficheiro CSV, Excel ou PDF para receber o teu relatorio
- 'relatorio' ou '2' — ver ultimo relatorio
- 'resumo' ou '3' — 3 KPIs rapidos
- 'top' ou '4' — top 5 produtos"""


# ── JSON HELPERS (PERSISTÊNCIA LOCAL DE CLIENTES) ─────────────────────────────

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
    """Procura e retorna o perfil de um cliente específico com base no número de telefone."""
    for cliente in carregar_todos_clientes():
        if cliente["numero"] == phone_number:
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

    if passo == 1:
        for c in clientes:
            if c["numero"] == phone_number:
                c["nome"] = texto
                c["onboarding_passo"] = 2
                break
        guardar_clientes(clientes)
        enviar_mensagem(phone_number, "Que tipo de negocio tens?\n1. Servicos\n2. Retalho\n3. Agropecuaria\n4. Outro")

    elif passo == 2:
        tipos = {"1": "servicos", "2": "retalho", "3": "agropecuaria", "4": "outro"}
        negocio = tipos.get(texto.strip(), texto.strip())
        for c in clientes:
            if c["numero"] == phone_number:
                c["negocio"] = negocio
                c["onboarding_passo"] = 3
                break
        guardar_clientes(clientes)
        enviar_mensagem(phone_number, "Qual e o teu email para relatorios de backup? (envia 'skip' para ignorar)")

    elif passo == 3:
        email = None if texto.strip().lower() == "skip" else texto.strip()
        for c in clientes:
            if c["numero"] == phone_number:
                c["email"] = email
                c["onboarding_passo"] = 4
                break
        guardar_clientes(clientes)
        enviar_mensagem(phone_number, "Como preferes enviar os teus dados e receber os relatorios?\n1. Semanalmente\n2. Mensalmente")

    elif passo == 4:
        freq_map = {"1": "semanal", "2": "mensal"}
        frequencia = freq_map.get(texto.strip(), "semanal")
        for c in clientes:
            if c["numero"] == phone_number:
                c["frequencia"] = frequencia
                c["onboarding_passo"] = 0
                break
        guardar_clientes(clientes)
        enviar_mensagem(phone_number, f"Perfeito! Onboarding completo. Configurado para envio {frequencia}.\nEnvia agora o teu ficheiro CSV, Excel ou PDF com os teus dados de vendas.")


# ── TAREFAS ASSÍNCRONAS EM SEGUNDO PLANO (BACKGROUND TASKS) ────────────────────

def gerar_relatorio_background(phone_number: str, filepath: str, nome_cliente: str, frequencia_atual: str):
    """
    Executa o pipeline pesado de dados fora do fluxo principal da rota HTTP.
    Garante regeneração total contornando qualquer cache local ou na API do WhatsApp.
    """
    try:
        # Ingestão e cálculo das métricas avançadas (dados são sempre relidos do arquivo transiente)
        df = ingest(filepath)
        metricas = calcular_metricas(df, frequencia_cliente=frequencia_atual)
        
        # CORREÇÃO: Identificador único estrito usando Timestamp formatado e UUID truncado
        timestamp_label = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico = uuid.uuid4().hex[:6]
        pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"
        
        # O nome seguro e imutável é passado no contrato 'semana_label' para gravação direta no disco
        pdf_path = gerar_relatorio(metricas, nome_negocio=nome_cliente, semana_label=pdf_filename_limpo)
        
        # Constrói o URL público codificado e dispara o envio do PDF limpo
        base_url = os.getenv("BASE_URL")
        pdf_url = f"{base_url}/reports/{urllib.parse.quote(pdf_filename_limpo)}"
        
        msg_envio = f"Aqui tens o teu relatório {frequencia_atual} atualizado:"
        main_function(phone_number, pdf_url, pdf_filename_limpo, mensagem=msg_envio)
    except Exception as e:
        print(f"Erro ao processar relatório por texto em background: {e}")


def processar_ficheiro(phone_number: str, document_id: str, filename: str):
    """
    Descarrega o documento enviado pelo utilizador, isola o arquivo em disco utilizando
    um identificador temporal único, processa e devolve o novo PDF de forma determinística.
    """
    try:
        token = os.getenv("META_ACCESS_TOKEN")

        # Etapa A: Solicita o URL temporário de download à Graph API da Meta
        meta_url = f"https://graph.facebook.com/v15.0/{document_id}"
        r = httpx.get(meta_url, headers={"Authorization": f"Bearer {token}"})
        download_url = r.json()["url"]

        # Etapa B: Descarrega os bytes binários do ficheiro
        ficheiro = httpx.get(download_url, headers={"Authorization": f"Bearer {token}"})
        os.makedirs("data/uploads", exist_ok=True)
        
        # CORREÇÃO: Força o isolamento físico do upload injetando um carimbo temporal no nome do arquivo
        timestamp_upload = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename_seguro = f"{timestamp_upload}_{filename.replace(' ', '_')}"
        filepath = f"data/uploads/{filename_seguro}"
        
        with open(filepath, "wb") as f:
            f.write(ficheiro.content)

        # Etapa C: Inicia o processamento analítico a partir do novo arquivo isolado
        df = ingest(filepath)
        cliente = carregar_cliente(phone_number)
        frequencia = cliente.get("frequencia", "semanal") if cliente else "semanal"
        
        metricas = calcular_metricas(df, frequencia_cliente=frequencia)
        nome_empresa = cliente["nome"] if cliente and cliente.get("nome") else "O meu negocio"
        
        # CORREÇÃO: Formatação exata do nome do relatório de saída (report_YYYYMMDD_HHMMSS_uuid.pdf)
        timestamp_label = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico = uuid.uuid4().hex[:6]
        pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"
        
        # Aciona a geração do PDF passando o nome já higienizado, imutável e seguro
        pdf_path = gerar_relatorio(metricas, nome_negocio=nome_empresa, semana_label=pdf_filename_limpo)

        base_url = os.getenv("BASE_URL")
        pdf_url = f"{base_url}/reports/{urllib.parse.quote(pdf_filename_limpo)}"

        # Etapa D: Envia o documento recém-gerado de volta ao WhatsApp do cliente
        msg_envio = f"O teu relatório {frequencia} está pronto:"
        main_function(phone_number, pdf_url, pdf_filename_limpo, mensagem=msg_envio)

        # Etapa E: Vincula este ficheiro processado exclusivo como o 'ultimo_ficheiro' do cliente no JSON
        clientes = carregar_todos_clientes()
        for c in clientes:
            if c["numero"] == phone_number:
                c["ultimo_ficheiro"] = filepath
                break
        guardar_clientes(clientes)
    except Exception as e:
        print(f"Erro ao processar ficheiro em background: {e}")


# ── MOTOR DE COMANDOS DE TEXTO ────────────────────────────────────────────────

def tratar_comando(phone_number: str, texto: str, background_tasks: BackgroundTasks):
    """
    Roteador de intenções de texto. Analisa o que o cliente digitou
    e escolhe a ação ou resposta textual apropriada de forma imediata.
    """
    texto_original = texto
    texto = texto.lower().strip()
    cliente = carregar_cliente(phone_number)

    if not cliente:
        novo_cliente = {
            "numero": phone_number,
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
        enviar_mensagem(phone_number, "Bem-vindo ao InsightZone! Qual e o nome do teu negocio?")
        return

    if cliente["onboarding_passo"] > 0:
        tratar_onboarding(phone_number, texto_original, cliente)
        return

    frequencia_atual = cliente.get("frequencia", "semanal")

    if texto in ["ola", "olá", "oi", "hello", "hi", "bom dia", "boa tarde", "boa noite"]:
        enviar_mensagem(phone_number, MENU.format(frequencia=frequencia_atual.upper()))
        return

    if texto in ["relatorio", "relatório", "2"]:
        if not cliente.get("ultimo_ficheiro"):
            enviar_mensagem(phone_number, "Ainda nao tens nenhum relatorio. Envia um ficheiro CSV, Excel ou PDF para comecar.")
            return
        
        enviar_mensagem(phone_number, "A preparar o teu documento estratégico. Aguarda um momento...")
        background_tasks.add_task(
            gerar_relatorio_background, 
            phone_number, 
            cliente["ultimo_ficheiro"], 
            cliente["nome"], 
            frequencia_atual
        )
        return

    if texto in ["resumo", "rapido", "rápido", "3"]:
        if not cliente.get("ultimo_ficheiro"):
            enviar_mensagem(phone_number, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
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
        enviar_mensagem(phone_number, resumo)
        return

    if texto in ["top", "top cinco", "top 5", "4"]:
        if not cliente.get("ultimo_ficheiro"):
            enviar_mensagem(phone_number, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        df = ingest(cliente["ultimo_ficheiro"])
        metricas = calcular_metricas(df, frequencia_cliente=frequencia_atual)
        top = metricas["top_produtos_mes"] if frequencia_atual == "mensal" else metricas["top_produtos"]
        linhas = [f"{i+1}. {produto} — {int(qty)} unidades" for i, (produto, qty) in enumerate(top.items())]
        enviar_mensagem(phone_number, f"Top 5 produtos ({frequencia_atual}):\n" + "\n".join(linhas))
        return

    enviar_mensagem(phone_number, AJUDA)


# ── FASTAPI APPLICATION E ENDPOINTS ───────────────────────────────────────────

app = FastAPI()

# Serve publicamente a pasta de relatórios gerados para que a Meta consiga aceder e descarregar os PDFs
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
    """Rota de validação obrigatória exigida pela Meta para ativar o Webhook."""
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("WEBHOOK_VERIFY_TOKEN"):
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token inválido")


@app.post("/webhook")
def receber_webhook(payload: dict, background_tasks: BackgroundTasks):
    """
    Ponto de entrada central de eventos do WhatsApp Cloud API.
    Processa mensagens de texto e uploads de documentos em background sem travar o canal.
    """
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        
        if "messages" not in value:
            return Response(content="OK", status_code=200)
            
        mensagem = value["messages"][0]
        phone_number = mensagem.get("from")
        tipo = message_type = mensagem.get("type")
        
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
            
        document_id = mensagem.get("document", {}).get("id")
        filename = mensagem.get("document", {}).get("filename", f"vendas_{int(datetime.now().timestamp())}.csv")
        
        background_tasks.add_task(processar_ficheiro, phone_number, document_id, filename)

    return Response(content="OK", status_code=200)