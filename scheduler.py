import gc
import json
import os

import psycopg2
import psycopg2.extras
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from pipeline.metrics import calcular_metricas
from pipeline.reader import ingest
from pipeline.report import gerar_relatorio
from pipeline.sender import main_function

load_dotenv()


def get_conn():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def enviar_relatorios_periodicos():
    """
    Corre de acordo com a cadência configurada.
    Gera e envia relatório a cada cliente que tenha dados disponíveis.
    """
    conn = get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("SELECT * FROM clientes WHERE onboarding_passo = 0")
    clientes = cursor.fetchall()

    base_url = os.getenv("BASE_URL")

    for cliente in clientes:
        try:
            numero          = cliente["numero"]
            nome            = cliente.get("nome") or "Cliente"
            ultimo_ficheiro = cliente.get("ultimo_ficheiro")
            frequencia      = cliente.get("frequencia", "semanal")

            if not ultimo_ficheiro or not os.path.exists(ultimo_ficheiro):
                main_function(
                    numero, None, None,
                    mensagem=f"Ola {nome}! Ainda nao recebi os teus dados. Envia o ficheiro para receberes o teu relatorio!"
                )
                continue

            df       = ingest(ultimo_ficheiro)
            metricas = calcular_metricas(df, frequencia_cliente=frequencia)
            # df libertado dentro de calcular_metricas

            pdf_path     = gerar_relatorio(metricas, nome_negocio=nome)
            pdf_filename = os.path.basename(pdf_path)
            pdf_url      = f"{base_url}/reports/{pdf_filename}"

            main_function(numero, pdf_url, pdf_filename)

            # Guarda parquet para histórico — reutiliza ingest() uma única vez
            # (antes havia um segundo ingest() desnecessário que duplicava I/O e RAM)
            semana_parquet = f"data/silver/{nome.replace(' ', '_')}_latest.parquet"
            os.makedirs("data/silver", exist_ok=True)
            df_parquet = ingest(ultimo_ficheiro)
            df_parquet.to_parquet(semana_parquet, index=False)
            del df_parquet
            gc.collect()

            # Actualiza histórico na base de dados
            historico_actual = json.loads(cliente.get("historico") or "[]")
            historico_actual.append(semana_parquet)
            cursor.execute(
                "UPDATE clientes SET historico = %s WHERE numero = %s",
                (json.dumps(historico_actual), numero)
            )
            conn.commit()

        except Exception as e:
            print(f"Erro ao processar cliente {cliente.get('nome')}: {e}")

    cursor.close()
    conn.close()


def iniciar_scheduler():
    """Inicia o scheduler chamado no lifespan do FastAPI."""
    scheduler = BackgroundScheduler()

    # Relatórios semanais segunda-feira às 8h
    scheduler.add_job(
        enviar_relatorios_periodicos,
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="relatorios_semanais",
        max_instances=1,          
        misfire_grace_time=3600,  
    )

    scheduler.start()
    return scheduler