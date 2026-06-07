import gc
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime

import httpx
import psycopg2
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from pipeline.metrics import calcular_metricas
from pipeline.reader import ingest
from pipeline.report import gerar_relatorio
from pipeline.sender import enviar_mensagem, main_function
from pipeline.storage import upload_pdf

load_dotenv()

# Deduplicação de mensagens — evita processar o mesmo webhook duas vezes
# (o Meta faz retry automático se não recebe 200 a tempo)
_mensagens_vistas: set = set()

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
    # BUG CORRIGIDO: hmac.new() não existe em Python — usar hmac.new é alias de hmac.HMAC
    # A forma correcta é hmac.new(key, msg, digestmod)
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    expected = mac.hexdigest()
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
        cursor.execute(
            "SELECT numero, nome, negocio, frequencia, ultimo_relatorio_url, onboarding_passo, historico "
            "FROM clientes WHERE numero = %s",
            (numero_limpo,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return None
        return {
            "numero":              row[0],
            "nome":                row[1],
            "negocio":             row[2],
            "frequencia":          row[3] or "semanal",
            "ultimo_relatorio_url": row[4],   # URL do Cloudinary, não path local
            "onboarding_passo":    row[5],
            "historico":           json.loads(row[6]) if row[6] else [],
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
            INSERT INTO clientes (numero, nome, negocio, frequencia, ultimo_relatorio_url, onboarding_passo, historico)
            VALUES (%s, NULL, NULL, 'semanal', NULL, 1, '[]')
            ON CONFLICT (numero) DO NOTHING
        """, (numero_limpo,))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Erro ao criar cliente: {e}")


def actualizar_cliente(numero_limpo: str, campos: dict):
    """Actualiza campos específicos de um cliente."""
    if not campos:
        return
    try:
        conn   = get_conn()
        cursor = conn.cursor()
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
        cursor.execute(
            "SELECT numero, nome, negocio, frequencia, ultimo_relatorio_url, onboarding_passo, historico "
            "FROM clientes"
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [
            {
                "numero":              r[0],
                "nome":                r[1],
                "negocio":             r[2],
                "frequencia":          r[3] or "semanal",
                "ultimo_relatorio_url": r[4],
                "onboarding_passo":    r[5],
                "historico":           json.loads(r[6]) if r[6] else [],
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
        # BUG CORRIGIDO: guardar o nome E avançar o passo numa só operação
        nome = texto.strip()
        if not nome:
            enviar_mensagem(numero_limpo, "Por favor envia o nome do teu negocio.")
            return
        actualizar_cliente(numero_limpo, {"nome": nome, "onboarding_passo": 2})
        enviar_mensagem(numero_limpo, "Que tipo de negocio tens?\n1. Servicos\n2. Retalho (Alimentar, Vestuario, Electronica)\n3. Agropecuaria\n4. Outro")

    elif passo == 2:
        tipos   = {"1": "servicos", "2": "retalho", "3": "agropecuaria", "4": "outro"}
        negocio = tipos.get(texto.strip(), texto.strip())
        actualizar_cliente(numero_limpo, {"negocio": negocio, "onboarding_passo": 3})
        enviar_mensagem(numero_limpo, "Como preferes receber os relatorios?\n1. Semanalmente\n2. Mensalmente")

    elif passo == 3:
        freq_map   = {"1": "semanal", "2": "mensal"}
        frequencia = freq_map.get(texto.strip(), "semanal")
        actualizar_cliente(numero_limpo, {"frequencia": frequencia, "onboarding_passo": 0})
        enviar_mensagem(
            numero_limpo,
            f"Perfeito! Onboarding completo. Configurado para envio {frequencia}.\n"
            "Envia agora o teu ficheiro CSV, Excel ou PDF com os teus dados de vendas."
        )


# ── BACKGROUND TASKS ──────────────────────────────────────────────────────────

def gerar_relatorio_background(phone_number: str, pdf_url: str, nome_cliente: str, frequencia_atual: str):
    """
    BUG CORRIGIDO: já não tenta re-processar ficheiro local (que foi apagado).
    Reenvia o último PDF guardado no Cloudinary directamente.
    """
    try:
        numero_limpo = limpar_numero(phone_number)
        if not pdf_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens nenhum relatorio. Envia um ficheiro CSV, Excel ou PDF para comecar.")
            return
        pdf_filename = pdf_url.split("/")[-1]
        main_function(
            numero_limpo, pdf_url, pdf_filename,
            mensagem=f"Aqui tens o teu relatorio {frequencia_atual} mais recente:"
        )
    except Exception as e:
        print(f"Erro ao reenviar relatorio: {e}")


def processar_ficheiro(phone_number: str, document_id: str, filename: str):
    filepath = None
    try:
        token        = os.getenv("META_ACCESS_TOKEN")
        numero_limpo = limpar_numero(phone_number)

        meta_url     = f"https://graph.facebook.com/v25.0/{document_id}"
        r            = httpx.get(meta_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        download_url = r.json().get("url")

        if not download_url:
            print(f"Erro: URL de download nao obtida. Resposta: {r.text}")
            enviar_mensagem(numero_limpo, "Nao consegui descarregar o ficheiro. Tenta novamente.")
            return

        ficheiro = httpx.get(download_url, headers={"Authorization": f"Bearer {token}"}, timeout=60)
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

        # storage.py faz upload E apaga o ficheiro pdf local — não apagar aqui também
        pdf_url = upload_pdf(pdf_path)

        # BUG CORRIGIDO: guardar o URL do Cloudinary, não o path local do ficheiro de vendas
        actualizar_cliente(numero_limpo, {"ultimo_relatorio_url": pdf_url})

        main_function(numero_limpo, pdf_url, pdf_filename_limpo, mensagem=f"O teu relatorio {frequencia} esta pronto:")
        print("Pipeline concluido com sucesso!")

    except Exception as e:
        print(f"Erro ao processar ficheiro em background: {e}")
        try:
            numero_limpo = limpar_numero(phone_number)
            enviar_mensagem(numero_limpo, "Ocorreu um erro ao processar o ficheiro. Verifica se o formato e valido (CSV, Excel ou PDF).")
        except Exception:
            pass

    finally:
        # Apaga apenas o ficheiro de vendas temporário (o PDF é apagado pelo storage.py)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"Ficheiro temporario removido: {filepath}")
            except Exception as cleanup_err:
                print(f"Aviso: nao foi possivel remover {filepath}: {cleanup_err}")


# ── RESUMO E TOP (background) ─────────────────────────────────────────────────

def _resumo_background(numero_limpo: str, pdf_url: str, frequencia_atual: str):
    """
    BUG CORRIGIDO: resumo rápido baseado no último PDF URL (não num ficheiro local apagado).
    Envia o URL do último relatório com uma mensagem de resumo contextual.
    """
    try:
        if not pdf_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        # Envia o último relatório guardado como "resumo rápido"
        pdf_filename = pdf_url.split("/")[-1]
        main_function(
            numero_limpo, pdf_url, pdf_filename,
            mensagem=f"Aqui tens o teu ultimo relatorio {frequencia_atual}:"
        )
    except Exception as e:
        print(f"Erro ao enviar resumo: {e}")


def _top_background(numero_limpo: str, pdf_url: str, frequencia_atual: str):
    """Reenvia o último relatório como resposta ao comando 'top'."""
    _resumo_background(numero_limpo, pdf_url, frequencia_atual)


# ── MOTOR DE COMANDOS ─────────────────────────────────────────────────────────

def tratar_comando(phone_number: str, texto: str, background_tasks: BackgroundTasks):
    texto_original = texto
    texto          = texto.lower().strip()
    numero_limpo   = limpar_numero(phone_number)
    cliente        = carregar_cliente(numero_limpo)

    if not cliente:
        criar_cliente(numero_limpo)
        cliente = carregar_cliente(numero_limpo)

    if not cliente:
        print(f"Erro critico: nao foi possivel criar/carregar cliente {numero_limpo}")
        return

    # Passo 1: sem nome ainda
    # - saudação → envia boas-vindas e aguarda próxima mensagem com o nome
    # - qualquer outro texto → já é o nome, processa directamente
    if cliente["onboarding_passo"] == 1 and not cliente.get("nome"):
        saudacoes = {"ola", "olá", "oi", "hello", "hi", "bom dia", "boa tarde", "boa noite", "novo"}
        if texto in saudacoes or len(texto.strip()) <= 2:
            enviar_mensagem(numero_limpo, "Bem-vindo ao InsightZone! Qual e o nome do teu negocio?")
            return
        tratar_onboarding(numero_limpo, texto_original, cliente)
        return

    if cliente["onboarding_passo"] > 0:
        tratar_onboarding(numero_limpo, texto_original, cliente)
        return

    frequencia_atual    = cliente.get("frequencia", "semanal")
    ultimo_relatorio_url = cliente.get("ultimo_relatorio_url")

    if texto in ["ola", "olá", "oi", "hello", "hi", "bom dia", "boa tarde", "boa noite"]:
        enviar_mensagem(numero_limpo, MENU.format(frequencia=frequencia_atual.upper()))
        return

    if texto in ["relatorio", "relatório", "2"]:
        if not ultimo_relatorio_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens nenhum relatorio. Envia um ficheiro CSV, Excel ou PDF para comecar.")
            return
        enviar_mensagem(numero_limpo, "A preparar o teu documento estrategico. Aguarda um momento...")
        background_tasks.add_task(
            gerar_relatorio_background,
            numero_limpo, ultimo_relatorio_url, cliente["nome"], frequencia_atual
        )
        return

    if texto in ["resumo", "rapido", "rápido", "3"]:
        if not ultimo_relatorio_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        background_tasks.add_task(
            _resumo_background, numero_limpo, ultimo_relatorio_url, frequencia_atual
        )
        return

    if texto in ["top", "top cinco", "top 5", "4"]:
        if not ultimo_relatorio_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        background_tasks.add_task(
            _top_background, numero_limpo, ultimo_relatorio_url, frequencia_atual
        )
        return

    enviar_mensagem(numero_limpo, AJUDA)


# ── FASTAPI ───────────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.api_route("/", methods=["GET", "HEAD"])
def read_root():
    return {"status": "healthy", "service": "InsightZone"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/webhook")
def verificar_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("WEBHOOK_VERIFY_TOKEN"):
        return Response(content=str(hub_challenge), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Token invalido")


@app.post("/webhook")
@limiter.limit("20/minute")
async def receber_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verificar_assinatura_meta(body, signature):
        raise HTTPException(status_code=403, detail="Assinatura invalida")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return Response(content="OK", status_code=200)

    try:
        entry    = payload.get("entry", [])[0]
        changes  = entry.get("changes", [])[0]
        value    = changes.get("value", {})

        if "messages" not in value:
            return Response(content="OK", status_code=200)

        mensagem     = value["messages"][0]
        phone_number = limpar_numero(mensagem.get("from"))
        tipo         = mensagem.get("type")
        message_id   = mensagem.get("id", "")

    except (KeyError, IndexError, TypeError):
        return Response(content="OK", status_code=200)

    # Ignora mensagens já processadas
    if message_id and message_id in _mensagens_vistas:
        return Response(content="OK", status_code=200)
    if message_id:
        _mensagens_vistas.add(message_id)
        if len(_mensagens_vistas) > 1000:
            _mensagens_vistas.clear()

    if tipo == "text":
        texto = mensagem.get("text", {}).get("body", "")
        tratar_comando(phone_number, texto, background_tasks)

    elif tipo == "document":
        cliente = carregar_cliente(phone_number)

        # se ainda em onboarding, tratar como texto "documento" não "novo"
        if not cliente or cliente.get("onboarding_passo", 0) > 0:
            enviar_mensagem(
                limpar_numero(phone_number),
                "Por favor completa o registo primeiro. Qual e o nome do teu negocio?"
            )
            if not cliente:
                criar_cliente(limpar_numero(phone_number))
            return Response(content="OK", status_code=200)

        doc_data    = mensagem.get("document", {})
        document_id = doc_data.get("id")
        filename    = doc_data.get("filename", f"vendas_{int(datetime.now().timestamp())}.xlsx")

        if document_id:
            background_tasks.add_task(processar_ficheiro, phone_number, document_id, filename)

    return Response(content="OK", status_code=200)