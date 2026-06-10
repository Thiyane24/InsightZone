import gc
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime

import httpx
import pandas as pd
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
from pipeline.storage import upload_pdf, upload_ficheiro_vendas, download_ficheiro

load_dotenv()

_mensagens_vistas: set = set()

MENU = """Ola! Sou o InsightZone.
Modo atual: {frequencia}

1. Enviar ficheiro de vendas em formato CSV, Excel ou PDF para receber o relatorio.
2. Ver relatorio anterior
3. Resumo rapido
4. Top 5 {top_label}
5. Introduzir vendas por texto
6. Mudar frequencia dos relatorios"""

AJUDA = """Comandos disponiveis:
- Envia um ficheiro CSV, Excel ou PDF para receber o teu relatorio
- 'relatorio' ou '2' - ver ultimo relatorio
- 'resumo' ou '3' - 3 KPIs rapidos
- 'top' ou '4' - top 5 produtos/servicos
- 'vendas' ou '5' - introduzir vendas por texto
- 'frequencia' ou '6' - mudar frequencia dos relatorios"""

INSTRUCOES_VENDAS = """Envia as tuas vendas no formato:
produto, quantidade, valor

Exemplo:
Frango, 3, 250
Arroz, 5, 150
Feijao, 2, 80

Envia 'cancelar' para sair."""

INSTRUCOES_VENDAS_SERVICOS = """Envia os teus servicos no formato:
servico, quantidade, valor

Exemplo:
Consultoria, 1, 5000
Instalacao, 2, 2500
Manutencao, 3, 1200

Envia 'cancelar' para sair."""

INSTRUCOES_FREQUENCIA = """Com que frequencia queres receber os teus relatorios?

1. Diariamente (todos os dias as 20h)
2. Semanalmente (segunda-feira as 8h)
3. Mensalmente (1 dia do mes as 8h)

Envia 'cancelar' para manter a opcao actual."""


# ── UTILITARIOS ───────────────────────────────────────────────────────────────

def _e_servicos(tipo_negocio: str) -> bool:
    return (tipo_negocio or "").lower() in ("servicos", "servico")


def _top_label(tipo_negocio: str) -> str:
    return "servicos" if _e_servicos(tipo_negocio) else "produtos"


# ── SEGURANCA SHA-256 ─────────────────────────────────────────────────────────

def verificar_assinatura_meta(payload_bytes: bytes, signature_header: str) -> bool:
    secret = os.getenv("META_APP_SECRET", "")
    if not secret:
        print("Aviso: META_APP_SECRET nao configurado no .env")
        return False
    mac      = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    expected = mac.hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


# ── BASE DE DADOS ─────────────────────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def limpar_numero(phone_number: str) -> str:
    if not phone_number:
        return ""
    return str(phone_number).replace("+", "").strip()


def carregar_cliente(phone_number: str) -> dict | None:
    numero_limpo = limpar_numero(phone_number)
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT numero, nome, negocio, frequencia, ultimo_relatorio_url, onboarding_passo, historico, ultimo_ficheiro_url, modo "
            "FROM clientes WHERE numero = %s",
            (numero_limpo,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return None
        return {
            "numero":               row[0],
            "nome":                 row[1],
            "negocio":              row[2] or "retalho",
            "frequencia":           row[3] or "semanal",
            "ultimo_relatorio_url": row[4],
            "onboarding_passo":     row[5],
            "historico":            json.loads(row[6]) if row[6] else [],
            "ultimo_ficheiro_url":  row[7],
            "modo":                 row[8],
        }
    except Exception as e:
        print(f"Erro ao carregar cliente: {e}")
        return None


def criar_cliente(numero_limpo: str):
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
    if not campos:
        return
    try:
        conn       = get_conn()
        cursor     = conn.cursor()
        set_clause = ", ".join(f"{k} = %s" for k in campos)
        valores    = list(campos.values()) + [numero_limpo]
        cursor.execute(f"UPDATE clientes SET {set_clause} WHERE numero = %s", valores)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Erro ao actualizar cliente: {e}")


def carregar_todos_clientes() -> list:
    try:
        conn   = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT numero, nome, negocio, frequencia, ultimo_relatorio_url, onboarding_passo, historico, ultimo_ficheiro_url, modo "
            "FROM clientes"
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [
            {
                "numero":               r[0],
                "nome":                 r[1],
                "negocio":              r[2] or "retalho",
                "frequencia":           r[3] or "semanal",
                "ultimo_relatorio_url": r[4],
                "onboarding_passo":     r[5],
                "historico":            json.loads(r[6]) if r[6] else [],
                "ultimo_ficheiro_url":  r[7],
                "modo":                 r[8],
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
        nome = texto.strip()
        if not nome:
            enviar_mensagem(numero_limpo, "Por favor envia o nome do teu negocio.")
            return
        actualizar_cliente(numero_limpo, {"nome": nome, "onboarding_passo": 2})
        enviar_mensagem(numero_limpo, "Que tipo de negocio tens?\n1. Servicos\n2. Retalho (Alimentar, Vestuario, Electronica)\n3. Agropecuaria\n4. Outro")

    elif passo == 2:
        tipos   = {"1": "servicos", "2": "retalho", "3": "agropecuaria", "4": "outro"}
        negocio = tipos.get(texto.strip(), texto.strip().lower() or "retalho")
        actualizar_cliente(numero_limpo, {"negocio": negocio, "onboarding_passo": 3})
        enviar_mensagem(numero_limpo, "Como preferes receber os relatorios?\n1. Diariamente (todos os dias as 20h)\n2. Semanalmente (segunda-feira as 8h)\n3. Mensalmente (1 dia do mes as 8h)")

    elif passo == 3:
        freq_map   = {"1": "diario", "2": "semanal", "3": "mensal"}
        frequencia = freq_map.get(texto.strip(), "semanal")
        actualizar_cliente(numero_limpo, {"frequencia": frequencia, "onboarding_passo": 0})
        enviar_mensagem(
            numero_limpo,
            f"Perfeito! Onboarding completo. Configurado para envio {frequencia}.\n"
            "Envia agora o teu ficheiro CSV, Excel ou PDF com os teus dados."
        )


# ── PARSER DE VENDAS/SERVICOS POR TEXTO ───────────────────────────────────────

def parsear_vendas_texto(texto: str, tipo_negocio: str = "retalho") -> pd.DataFrame | None:
    """
    Converte texto livre no formato "item, quantidade, valor" num DataFrame.
    A coluna de item usa 'produto' para retalho e 'servico' para servicos,
    para que o detector de colunas do metrics.py a reconheca correctamente.
    """
    linhas = texto.strip().splitlines()
    vendas = []
    hoje   = datetime.now().strftime("%Y-%m-%d")

    # ALTERADO: nome da coluna adapta-se ao tipo de negocio
    col_item = "servico" if _e_servicos(tipo_negocio) else "produto"

    for linha in linhas:
        if not linha.strip():
            continue
        partes = [p.strip() for p in linha.split(",")]
        if len(partes) != 3:
            continue
        try:
            item       = partes[0]
            quantidade = float(partes[1])
            valor      = float(partes[2])
            vendas.append({"data": hoje, col_item: item, "quantidade": quantidade, "valor": valor})
        except ValueError:
            continue

    if not vendas:
        return None

    return pd.DataFrame(vendas)


def processar_vendas_texto_background(
    numero_limpo: str, texto: str, nome_cliente: str,
    frequencia: str, tipo_negocio: str = "retalho"        # NOVO: recebe tipo_negocio
):
    filepath_temp = None
    try:
        # ALTERADO: passa tipo_negocio ao parser para nomear a coluna correctamente
        df = parsear_vendas_texto(texto, tipo_negocio=tipo_negocio)

        if df is None:
            # Mensagem de erro adapta-se ao tipo de negocio
            if _e_servicos(tipo_negocio):
                enviar_mensagem(numero_limpo, "Nao consegui ler os servicos. Usa o formato:\nservico, quantidade, valor\n\nExemplo:\nConsultoria, 1, 5000")
            else:
                enviar_mensagem(numero_limpo, "Nao consegui ler as vendas. Usa o formato:\nproduto, quantidade, valor\n\nExemplo:\nFrango, 3, 250")
            actualizar_cliente(numero_limpo, {"modo": None})
            return

        os.makedirs("data/uploads", exist_ok=True)
        timestamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath_temp = f"data/uploads/vendas_texto_{numero_limpo}_{timestamp}.csv"
        df.to_csv(filepath_temp, index=False)

        periodo  = "hoje" if frequencia == "diario" else None
        # ALTERADO: passa tipo_negocio ao pipeline
        metricas = calcular_metricas(
            df, frequencia_cliente=frequencia,
            periodo=periodo, tipo_negocio=tipo_negocio
        )
        del df
        gc.collect()

        timestamp_label    = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico         = uuid.uuid4().hex[:6]
        pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"

        is_diario = (frequencia == "diario")
        # ALTERADO: passa tipo_negocio ao report
        pdf_path  = gerar_relatorio(
            metricas, nome_negocio=nome_cliente,
            semana_label=pdf_filename_limpo, is_diario=is_diario,
            tipo_negocio=tipo_negocio
        )
        pdf_url = upload_pdf(pdf_path)

        ficheiro_url = upload_ficheiro_vendas(filepath_temp)

        actualizar_cliente(numero_limpo, {
            "ultimo_relatorio_url": pdf_url,
            "ultimo_ficheiro_url":  ficheiro_url,
            "modo":                 None,
        })

        main_function(numero_limpo, pdf_url, pdf_filename_limpo, mensagem=f"O teu relatorio {frequencia} esta pronto:")
        print(f"Vendas/servicos por texto processados com sucesso para {numero_limpo}")

    except Exception as e:
        print(f"Erro ao processar vendas por texto: {e}")
        actualizar_cliente(numero_limpo, {"modo": None})

    finally:
        if filepath_temp and os.path.exists(filepath_temp):
            try:
                os.remove(filepath_temp)
            except Exception:
                pass


# ── BACKGROUND TASKS ──────────────────────────────────────────────────────────

def gerar_relatorio_background(phone_number: str, pdf_url: str, nome_cliente: str, frequencia_atual: str):
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

        df      = ingest(filepath)
        cliente = carregar_cliente(numero_limpo)

        frequencia   = cliente.get("frequencia",   "semanal")  if cliente else "semanal"
        # ALTERADO: le tipo_negocio da BD
        tipo_negocio = cliente.get("negocio",      "retalho")  if cliente else "retalho"
        nome_empresa = cliente.get("nome") or "O meu negocio"  if cliente else "O meu negocio"

        periodo  = "hoje" if frequencia == "diario" else None
        # ALTERADO: passa tipo_negocio ao pipeline
        metricas = calcular_metricas(
            df, frequencia_cliente=frequencia,
            periodo=periodo, tipo_negocio=tipo_negocio
        )

        timestamp_label    = datetime.now().strftime('%Y%m%d_%H%M%S')
        hash_unico         = uuid.uuid4().hex[:6]
        pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"

        is_diario = (frequencia == "diario")
        # ALTERADO: passa tipo_negocio ao report
        pdf_path  = gerar_relatorio(
            metricas, nome_negocio=nome_empresa,
            semana_label=pdf_filename_limpo, is_diario=is_diario,
            tipo_negocio=tipo_negocio
        )

        pdf_url      = upload_pdf(pdf_path)
        ficheiro_url = upload_ficheiro_vendas(filepath)

        actualizar_cliente(numero_limpo, {
            "ultimo_relatorio_url": pdf_url,
            "ultimo_ficheiro_url":  ficheiro_url,
        })

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
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"Ficheiro temporario removido: {filepath}")
            except Exception as cleanup_err:
                print(f"Aviso: nao foi possivel remover {filepath}: {cleanup_err}")


# ── RESUMO E TOP (background) ─────────────────────────────────────────────────

def _carregar_df_cliente(numero_limpo: str, ficheiro_url: str):
    import tempfile
    ext = ficheiro_url.split(".")[-1].lower()
    if ext not in ("csv", "xlsx", "xls", "pdf"):
        ext = "xlsx"
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
        tmp_path = tmp.name
    download_ficheiro(ficheiro_url, tmp_path)
    df = ingest(tmp_path)
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    return df


def _resumo_background(numero_limpo: str, ficheiro_url: str, frequencia_atual: str, tipo_negocio: str = "retalho"):
    try:
        if not ficheiro_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        df       = _carregar_df_cliente(numero_limpo, ficheiro_url)
        periodo  = "hoje" if frequencia_atual == "diario" else None
        # ALTERADO: passa tipo_negocio
        metricas = calcular_metricas(
            df, frequencia_cliente=frequencia_atual,
            periodo=periodo, tipo_negocio=tipo_negocio
        )
        # ALTERADO: labels adaptativos no texto do resumo
        e_serv       = _e_servicos(tipo_negocio)
        label_itens  = "Transaccoes" if e_serv else "Itens vendidos"
        label_ticket = "Valor medio/servico" if e_serv else "Ticket medio"

        if frequencia_atual == "mensal":
            resumo = (
                f"Resumo do Mes ({metricas['mes_nome']}):\n"
                f"Faturacao total: {metricas['total_mensal']:.2f} MZN\n"
                f"Transacoes: {metricas['transacoes_mensal']}\n"
                f"{label_ticket}: {metricas['ticket_medio_mensal']:.2f} MZN\n"
                f"Melhor dia: {metricas['melhor_dia_mes']}"
            )
        elif frequencia_atual == "diario":
            linhas = [
                f"Resumo de hoje ({datetime.now().strftime('%d/%m/%Y')}):",
                f"Faturacao: {metricas['total']:.2f} MZN",
                f"{label_itens}: {metricas['total_transacoes']}",
                f"{label_ticket}: {metricas['ticket_medio']:.2f} MZN",
            ]
            if metricas.get("produto_do_dia"):
                p      = metricas["produto_do_dia"]
                rotulo = "Servico do dia" if e_serv else "Produto do dia"
                linhas.append(f"{rotulo}: {p['nome']} ({p['quantidade']} un)")
            if metricas.get("hora_pico"):
                linhas.append(f"Hora de pico: {metricas['hora_pico']}")
            if metricas.get("variacao_ontem") is not None:
                v     = metricas["variacao_ontem"]
                sinal = "+" if v >= 0 else ""
                linhas.append(f"Vs ontem: {sinal}{v:.1f}%")
            resumo = "\n".join(linhas)
        else:
            resumo = (
                f"Resumo da semana:\n"
                f"Faturacao total: {metricas['total']:.2f} MZN\n"
                f"{label_itens}: {metricas['total_transacoes']}\n"
                f"{label_ticket}: {metricas['ticket_medio']:.2f} MZN\n"
                f"Melhor dia: {metricas['melhor_dia']}"
            )
        enviar_mensagem(numero_limpo, resumo)
    except Exception as e:
        print(f"Erro ao gerar resumo: {e}")
        enviar_mensagem(numero_limpo, "Erro ao calcular o resumo. Tenta novamente.")


def _top_background(numero_limpo: str, ficheiro_url: str, frequencia_atual: str, tipo_negocio: str = "retalho"):
    try:
        if not ficheiro_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        df       = _carregar_df_cliente(numero_limpo, ficheiro_url)
        periodo  = "hoje" if frequencia_atual == "diario" else None
        # ALTERADO: passa tipo_negocio
        metricas = calcular_metricas(
            df, frequencia_cliente=frequencia_atual,
            periodo=periodo, tipo_negocio=tipo_negocio
        )
        top = metricas["top_produtos_mes"] if frequencia_atual == "mensal" else metricas["top_produtos"]

        sem_dados = not top or list(top.keys())[0] in (
            "Nenhum produto detetado", "Nenhum servico detetado", "Sem dados validos"
        )
        if sem_dados:
            label = "servicos" if _e_servicos(tipo_negocio) else "produtos"
            enviar_mensagem(numero_limpo, f"Nao foi possivel identificar {label} no teu ficheiro.")
            return

        # ALTERADO: label adapta-se ao tipo de negocio
        label_titulo = "servicos" if _e_servicos(tipo_negocio) else "produtos"
        linhas = [f"{i+1}. {item} - {int(qty)} ocorrencias" for i, (item, qty) in enumerate(top.items())]
        enviar_mensagem(numero_limpo, f"Top 5 {label_titulo} ({frequencia_atual}):\n" + "\n".join(linhas))
    except Exception as e:
        print(f"Erro ao gerar top: {e}")
        enviar_mensagem(numero_limpo, "Erro ao calcular o top. Tenta novamente.")


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

    frequencia_atual     = cliente.get("frequencia",           "semanal")
    tipo_negocio         = cliente.get("negocio",              "retalho")   # NOVO: lido da BD
    nome_cliente         = cliente.get("nome")              or "O meu negocio"
    ultimo_relatorio_url = cliente.get("ultimo_relatorio_url")
    ultimo_ficheiro_url  = cliente.get("ultimo_ficheiro_url")

    # Modo aguardar_vendas
    if cliente.get("modo") == "aguardar_vendas":
        if texto == "cancelar":
            actualizar_cliente(numero_limpo, {"modo": None})
            enviar_mensagem(numero_limpo, "Operacao cancelada.")
            return
        background_tasks.add_task(
            processar_vendas_texto_background,
            numero_limpo, texto_original, nome_cliente,
            frequencia_atual, tipo_negocio                    # ALTERADO: passa tipo_negocio
        )
        return

    # Modo aguardar_frequencia
    if cliente.get("modo") == "aguardar_frequencia":
        if texto == "cancelar":
            actualizar_cliente(numero_limpo, {"modo": None})
            enviar_mensagem(numero_limpo, f"Operacao cancelada. Frequencia mantida: {frequencia_atual}.")
            return

        freq_map  = {"1": "diario", "2": "semanal", "3": "mensal"}
        nova_freq = freq_map.get(texto.strip())

        if not nova_freq:
            enviar_mensagem(numero_limpo, "Opcao invalida. Envia 1, 2 ou 3.\n\n" + INSTRUCOES_FREQUENCIA)
            return

        actualizar_cliente(numero_limpo, {"frequencia": nova_freq, "modo": None})
        enviar_mensagem(
            numero_limpo,
            f"Frequencia actualizada para: {nova_freq.upper()}.\n"
            f"Vais passar a receber os teus relatorios {nova_freq}."
        )
        return

    if texto in ["ola", "olá", "oi", "hello", "hi", "bom dia", "boa tarde", "boa noite"]:
        # ALTERADO: label do item 4 adapta-se ao tipo de negocio
        enviar_mensagem(
            numero_limpo,
            MENU.format(
                frequencia=frequencia_atual.upper(),
                top_label=_top_label(tipo_negocio)
            )
        )
        return

    if texto in ["relatorio", "relatório", "2"]:
        if not ultimo_relatorio_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens nenhum relatorio. Envia um ficheiro CSV, Excel ou PDF para comecar.")
            return
        enviar_mensagem(numero_limpo, "A preparar o teu documento estrategico. Aguarda um momento...")
        background_tasks.add_task(
            gerar_relatorio_background,
            numero_limpo, ultimo_relatorio_url, nome_cliente, frequencia_atual
        )
        return

    if texto in ["resumo", "rapido", "rápido", "3"]:
        if not ultimo_ficheiro_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        # ALTERADO: passa tipo_negocio
        background_tasks.add_task(
            _resumo_background, numero_limpo, ultimo_ficheiro_url,
            frequencia_atual, tipo_negocio
        )
        return

    if texto in ["top", "top cinco", "top 5", "4"]:
        if not ultimo_ficheiro_url:
            enviar_mensagem(numero_limpo, "Ainda nao tens dados. Envia um ficheiro CSV ou Excel primeiro.")
            return
        # ALTERADO: passa tipo_negocio
        background_tasks.add_task(
            _top_background, numero_limpo, ultimo_ficheiro_url,
            frequencia_atual, tipo_negocio
        )
        return

    if texto in ["vendas", "5"]:
        actualizar_cliente(numero_limpo, {"modo": "aguardar_vendas"})
        # ALTERADO: instrucoes adaptam-se ao tipo de negocio
        instrucoes = INSTRUCOES_VENDAS_SERVICOS if _e_servicos(tipo_negocio) else INSTRUCOES_VENDAS
        enviar_mensagem(numero_limpo, instrucoes)
        return

    if texto in ["frequencia", "frequência", "6"]:
        actualizar_cliente(numero_limpo, {"modo": "aguardar_frequencia"})
        enviar_mensagem(numero_limpo, INSTRUCOES_FREQUENCIA)
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