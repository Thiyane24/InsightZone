import gc
import hashlib
import hmac
import json
import os
import urllib.parse
import uuid
from datetime import datetime

import httpx
import psycopg2
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from pipeline.metrics import calcular_metricas
from pipeline.reader import ingest
from pipeline.report import gerar_relatorio
from pipeline.sender import enviar_mensagem, main_function

load_dotenv()

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


# ── SEGURANÇA SHA-256 ─────────────────────────────────────────────────────────

def verificar_assinatura_meta(payload_bytes: bytes, signature_header: str) -> bool:
    secret = os.getenv("META_APP_SECRET", "")
    if not secret:
        print("Aviso: META_APP_SECRET não configurado no .env")
        return False
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


# ── BASE DE DADOS ─────────────────────────────────────────────────────────────

def get_conn():
    """Abre uma ligação à base de dados PostgreSQL."""
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def limpar_numero(phone_number: str) -> str:
    if not phone_number:
        return ""
    return str(phone_number).replace("+", "").strip()


def carregar_cliente(phone_number: str) -> dict | None:
    """Busca um cliente pelo número. Devolve dict ou None se não existir."""
    numero_limpo = limpar_numero(phone_number)
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT numero, nome, negocio, frequencia, ultimo_ficheiro, onboarding_passo, historico FROM clientes WHERE numero = %s", (numero_limpo,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return None
        return {
            "numero":           row[0],
            "nome":             row[1],
            "negocio":          row[2],
            "frequencia":       row[3] or "semanal",
            "ultimo_ficheiro":  row[4],
            "onboarding_passo": row[5],
            "historico":        json.loads(row[6]) if row[6] else [],
        }
    except Exception as e:
        print(f"Erro ao carregar cliente: {e}")
        return None


def criar_cliente(numero_limpo: str):
    """Insere um novo cliente na base de dados."""
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO clientes (numero, nome, negocio, frequencia, ultimo_ficheiro, onboarding_passo, historico)
            VALUES (%s, NULL, NULL, 'semanal', NULL, 1, '[]')
            ON CONFLICT (numero) DO NOTHING
        """, (numero_limpo,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Erro ao criar cliente: {e}")


def actualizar_cliente(numero_limpo: str, campos: dict):
    """
    Actualiza campos específicos de um cliente.
    Exemplo: actualizar_cliente(numero, {"nome": "Mercado X", "onboarding_passo": 2})
    """
    if not campos:
        return
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        # Constrói o SET dinamicamente só com os campos passados
        set_clause = ", ".join(f"{k} = %s" for k in campos)
        valores    = list(campos.values()) + [numero_limpo]
        cursor.execute(f"UPDATE clientes SET {set_clause} WHERE numero = %s", valores)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Erro ao actualizar cliente: {e}")


def carregar_todos_clientes() -> list:
    """Devolve todos os clientes — usado pelo scheduler."""
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT numero, nome, negocio, frequencia, ultimo_ficheiro, onboarding_passo, historico FROM clientes")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [
            {
                "numero":           r[0],
                "nome":             r[1],
                "negocio":          r[2],
                "frequencia":       r[3] or "semanal",
                "ultimo_ficheiro":  r[4],
                "onboarding_passo": r[5],
                "historico":        json.loads(r[6]) if r[6] else [],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"Erro ao carregar todos os clientes: {e}")
        return []


# ── ONBOARDING ────────────────────────────────────────────────────────────────

def tratar_onboarding(phone_number: str, texto: str, cliente: dict):
    passo        = cliente["onboarding_passo"]
    numero_limpo = limpar_numero(phone_number)

    if passo == 1:
        actualizar_cliente(numero_limpo, {"nome": texto, "onboarding_passo": 2})
        enviar_mensagem(numero_limpo, "Que tipo de negocio tens?\n1. Servicos\n2. Retalho (Alimentar, Vestuário, Eletrónica)\n3. Agropecuaria\n4. Outro")

    elif passo == 2:
        tipos   = {"1": "servicos", "2": "retalho", "3": "agropecuaria", "4": "outro"}
        negocio = tipos.get(texto.strip(), texto.strip())
        actualizar_cliente(numero_limpo, {"negocio": negocio, "onboarding_passo": 3})
        enviar_mensagem(numero_limpo, "Como preferes receber os relatorios?\n1. Semanalmente\n2. Mensalmente")

    elif passo == 3:
        freq_map  = {"1": "semanal", "2": "mensal"}
        frequencia = freq_map.get(texto.strip(), "semanal")
        actualizar_cliente(numero_limpo, {"frequencia": frequencia, "onboarding_passo": 0})
        enviar_mensagem(numero_limpo, f"Perfeito! Onboarding completo. Configurado para envio {frequencia}.\nEnvia agora o teu ficheiro CSV, Excel ou PDF com os teus dados de vendas.")


# ── BACKGROUND TASKS ──────────────────────────────────────────────────────────

def gerar_relatorio_background(phone_number: str, filepath: str, nome_cliente: str, frequencia_atual: str):
    try:
        numero_limpo       = limpar_numero(phone_number)
        df                 = ingest(filepath)
        metricas           = calcular_metricas(df, frequencia_cliente=frequencia_atual)
        timestamp_label    = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico         = uuid.uuid4().hex[:6]
        pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"
        pdf_path           = gerar_relatorio(metricas, nome_negocio=nome_cliente, semana_label=pdf_filename_limpo)
        base_url           = os.getenv("BASE_URL")
        pdf_url            = f"{base_url}/reports/{urllib.parse.quote(pdf_filename_limpo)}"
        main_function(numero_limpo, pdf_url, pdf_filename_limpo, mensagem=f"Aqui tens o teu relatório {frequencia_atual} atualizado:")
    except Exception as e:
        print(f"Erro ao gerar relatório em background: {e}")


def processar_ficheiro(phone_number: str, document_id: str, filename: str):
    filepath = None
    try:
        token        = os.getenv("META_ACCESS_TOKEN")
        numero_limpo = limpar_numero(phone_number)

        meta_url     = f"https://graph.facebook.com/v25.0/{document_id}"
        r            = httpx.get(meta_url, headers={"Authorization": f"Bearer {token}"})
        download_url = r.json().get("url")

        if not download_url:
            print(f"Erro: URL de download não obtida. Resposta: {r.text}")
            return

        ficheiro = httpx.get(download_url, headers={"Authorization": f"Bearer {token}"})
        os.makedirs("data/uploads", exist_ok=True)

        timestamp_upload = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename_seguro  = f"{timestamp_upload}_{filename.replace(' ', '_')}"
        filepath         = f"data/uploads/{filename_seguro}"

        with open(filepath, "wb") as f:
            f.write(ficheiro.content)

        del ficheiro
        gc.collect()

        df         = ingest(filepath)
        cliente    = carregar_cliente(numero_limpo)
        frequencia = cliente.get("frequencia", "semanal") if cliente else "semanal"

        metricas     = calcular_metricas(df, frequencia_cliente=frequencia)
        nome_empresa = cliente["nome"] if cliente and cliente.get("nome") else "O meu negocio"

        timestamp_label    = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico         = uuid.uuid4().hex[:6]
        pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"

        pdf_path = gerar_relatorio(metricas, nome_negocio=nome_empresa, semana_label=pdf_filename_limpo)

        base_url = os.getenv("BASE_URL")
        pdf_url  = f"{base_url}/reports/{urllib.parse.quote(pdf_filename_limpo)}"

        main_function(numero_limpo, pdf_url, pdf_filename_limpo, mensagem=f"O teu relatório {frequencia} está pronto:")

        # Guarda o caminho do último ficheiro na base de dados
        actualizar_cliente(numero_limpo, {"ultimo_ficheiro": filepath})
        print("Pipeline concluído com sucesso!")

    except Exception as e:
        print(f"Erro ao processar ficheiro em background: {e}")

    finally:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"Ficheiro temporário removido: {filepath}")
            except Exception as cleanup_err:
                print(f"Aviso: não foi possível remover {filepath}: {cleanup_err}")


# ── MOTOR DE COMANDOS ─────────────────────────────────────────────────────────

def tratar_comando(phone_number: str, texto: str, background_tasks: BackgroundTasks):
    texto_original = texto
    texto          = texto.lower().strip()
    numero_limpo   = limpar_numero(phone_number)
    cliente        = carregar_cliente(numero_limpo)

    if not cliente:
        criar_cliente(numero_limpo)
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
            numero_limpo, cliente["ultimo_ficheiro"], cliente["nome"], frequencia_atual
        )
        return

    if texto in ["resumo", "rapido", "rápido", "3"]:
        if not cliente.get("ultimo_ficheiro"):
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        background_tasks.add_task(
            _resumo_background, numero_limpo, cliente["ultimo_ficheiro"], frequencia_atual
        )
        return

    if texto in ["top", "top cinco", "top 5", "4"]:
        if not cliente.get("ultimo_ficheiro"):
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        background_tasks.add_task(
            _top_background, numero_limpo, cliente["ultimo_ficheiro"], frequencia_atual
        )
        return

    enviar_mensagem(numero_limpo, AJUDA)


def _resumo_background(numero_limpo: str, ultimo_ficheiro: str, frequencia_atual: str):
    try:
        df       = ingest(ultimo_ficheiro)
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
    except Exception as e:
        print(f"Erro ao gerar resumo: {e}")


def _top_background(numero_limpo: str, ultimo_ficheiro: str, frequencia_atual: str):
    try:
        df       = ingest(ultimo_ficheiro)
        metricas = calcular_metricas(df, frequencia_cliente=frequencia_atual)
        top      = metricas["top_produtos_mes"] if frequencia_atual == "mensal" else metricas["top_produtos"]
        linhas   = [f"{i+1}. {produto} — {int(qty)} unidades" for i, (produto, qty) in enumerate(top.items())]
        enviar_mensagem(numero_limpo, f"Top 5 produtos ({frequencia_atual}):\n" + "\n".join(linhas))
    except Exception as e:
        print(f"Erro ao gerar top produtos: {e}")


# ── FASTAPI ───────────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/reports", StaticFiles(directory="data/gold"), name="reports")


@app.get("/")
def read_root():
    return {"status": "healthy", "service": "InsightZone"}


@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("WEBHOOK_VERIFY_TOKEN"):
        return Response(content=str(hub_challenge), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token inválido")


@app.post("/webhook")
@limiter.limit("20/minute")
async def receber_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verificar_assinatura_meta(body, signature):
        raise HTTPException(status_code=403, detail="Assinatura inválida")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(content="OK", status_code=200)

    try:
        entry        = payload.get("entry", [])[0]
        changes      = entry.get("changes", [])[0]
        value        = changes.get("value", {})

        if "messages" not in value:
            return Response(content="OK", status_code=200)

        mensagem     = value["messages"][0]
        phone_number = limpar_numero(mensagem.get("from"))
        tipo         = mensagem.get("type")

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

        doc_data    = mensagem.get("document", {})
        document_id = doc_data.get("id")
        filename    = doc_data.get("filename", f"vendas_{int(datetime.now().timestamp())}.xlsx")

        if document_id:
            background_tasks.add_task(processar_ficheiro, phone_number, document_id, filename)

    return Response(content="OK", status_code=200)