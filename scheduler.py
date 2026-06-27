import gc
import json
import os
import uuid
from datetime import datetime

import psycopg2
import psycopg2.extras
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from pipeline.metrics import calcular_metricas
from pipeline.reader import ingest
from pipeline.report import gerar_relatorio
from pipeline.sender import main_function
from pipeline.storage import download_ficheiro, upload_pdf

load_dotenv()


# ── CONNECTION POOL ────────────────────────────────────────────────────────
# Criado uma vez no arranque. O Render free tier suporta até ~10 ligações
# simultâneas no PostgreSQL — minconn=1, maxconn=5 é seguro.
_db_pool: psycopg2.pool.SimpleConnectionPool | None = None


def _get_pool() -> psycopg2.pool.SimpleConnectionPool:
    global _db_pool
    if _db_pool is None or _db_pool.closed:
        _db_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=os.getenv("DATABASE_URL"),
        )
    return _db_pool


def get_conn():
    """Obtém uma ligação do pool. Usar sempre dentro de try/finally com put_conn()."""
    return _get_pool().getconn()


def put_conn(conn):
    """Devolve a ligação ao pool. Chamar sempre no finally."""
    try:
        _get_pool().putconn(conn)
    except Exception:
        pass


def _processar_cliente(cliente: dict, frequencia_filtro: str):
    """
    Gera e envia o relatório para um cliente individual.
    Separado em função própria para que um erro num cliente
    não interrompa o loop dos restantes.

    Parâmetros:
      cliente          — dict com os dados do cliente (vem do SELECT)
      frequencia_filtro — "semanal" | "mensal" | "diario"
                          usado para filtrar período e gerar o PDF correcto
    """
    numero     = cliente["numero"]
    nome       = cliente.get("nome") or "Cliente"
    frequencia = cliente.get("frequencia", "semanal")

    # Só processa clientes cuja frequência bate com o job que está a correr.
    # Assim o job semanal não envia relatórios a clientes diários e vice-versa.
    if frequencia != frequencia_filtro:
        return

    # Usa ultimo_ficheiro_url (Cloudinary) em vez de ultimo_ficheiro
    # (path local que não existe no Render após restart).
    ultimo_ficheiro_url = cliente.get("ultimo_ficheiro_url")

    if not ultimo_ficheiro_url:
        main_function(
            numero, None, None,
            mensagem=f"Ola {nome}! Ainda nao recebi os teus dados. Envia o ficheiro para receberes o teu relatorio!"
        )
        return

    # Descarrega o ficheiro do Cloudinary para um path temporário local
    ext      = ultimo_ficheiro_url.split(".")[-1].lower()
    if ext not in ("csv", "xlsx", "xls", "pdf"):
        ext = "xlsx"
    tmp_path = f"/tmp/scheduler_{numero}_{uuid.uuid4().hex[:6]}.{ext}"

    df = None
    try:
        download_ficheiro(ultimo_ficheiro_url, tmp_path)
        df = ingest(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    if df is None:
        print(f"Erro: ingest falhou para {numero} — df é None")
        return

    tipo_negocio = cliente.get("negocio") or "retalho"   # CORRIGIDO: lido da BD

    periodo   = "hoje" if frequencia == "diario" else None
    metricas  = calcular_metricas(
        df, frequencia_cliente=frequencia,
        periodo=periodo, tipo_negocio=tipo_negocio         # CORRIGIDO: passa tipo_negocio
    )
    del df
    gc.collect()

    timestamp_label    = datetime.now().strftime('%Y%m%d_%H%M%S')
    hash_unico         = uuid.uuid4().hex[:6]
    pdf_filename_limpo = f"report_{timestamp_label}_{hash_unico}.pdf"

    is_diario = (frequencia == "diario")
    pdf_path  = gerar_relatorio(
        metricas,
        nome_negocio=nome,
        semana_label=pdf_filename_limpo,
        is_diario=is_diario,
        tipo_negocio=tipo_negocio,
        frequencia=frequencia,
    )

    # Upload para Cloudinary em vez de construir URL local BASE_URL/reports/
    pdf_url = upload_pdf(pdf_path)

    # Actualiza o último relatório na BD
    conn   = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE clientes SET ultimo_relatorio_url = %s WHERE numero = %s",
            (pdf_url, numero)
        )
        conn.commit()
        cursor.close()
    finally:
        put_conn(conn)

    main_function(
        numero, pdf_url, pdf_filename_limpo,
        mensagem=f"O teu relatorio {frequencia} esta pronto:"
    )


def enviar_relatorios_periodicos(frequencia_filtro: str):
    """
    Corre de acordo com a cadência configurada.
    Gera e envia relatório a cada cliente com a frequência correspondente.

    Parâmetro frequencia_filtro: "semanal" | "mensal" | "diario"
    """
    conn   = get_conn()
    try:
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Só busca clientes que completaram o onboarding
        cursor.execute("SELECT * FROM clientes WHERE onboarding_passo = 0")
        clientes = cursor.fetchall()
    finally:
        put_conn(conn)

    for cliente in clientes:
        try:
            _processar_cliente(cliente, frequencia_filtro)
        except Exception as e:
            print(f"Erro ao processar cliente {cliente.get('nome')}: {e}")


def iniciar_scheduler():
    """Inicia o scheduler — chamado no lifespan do FastAPI."""
    scheduler = BackgroundScheduler()

    # Relatórios semanais — segunda-feira às 8h
    scheduler.add_job(
        enviar_relatorios_periodicos,
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="relatorios_semanais",
        kwargs={"frequencia_filtro": "semanal"},
        max_instances=1,
        misfire_grace_time=3600,
    )

    # Relatórios mensais — 1º dia do mês às 8h
    scheduler.add_job(
        enviar_relatorios_periodicos,
        CronTrigger(day=1, hour=8, minute=0),
        id="relatorios_mensais",
        kwargs={"frequencia_filtro": "mensal"},
        max_instances=1,
        misfire_grace_time=3600,
    )

    # Relatórios diários — todos os dias às 20h
    # NOVO: job diário para clientes com frequencia = 'diario'
    scheduler.add_job(
        enviar_relatorios_periodicos,
        CronTrigger(hour=20, minute=0),
        id="relatorios_diarios",
        kwargs={"frequencia_filtro": "diario"},
        max_instances=1,
        misfire_grace_time=3600,
    )

    scheduler.start()
    return scheduler