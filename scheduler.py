import gc
import json
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from pipeline.metrics import calcular_metricas
from pipeline.reader import ingest
from pipeline.report import gerar_relatorio
from pipeline.sender import main_function

load_dotenv()


def enviar_relatorios_periodicos():
    """
    Corre de acordo com a cadência configurada.
    Gera e envia relatório a cada cliente que tenha dados disponíveis.
    """
    with open("clientes.json", "r", encoding="utf-8") as f:
        clientes = json.load(f)

    base_url = os.getenv("BASE_URL")
    clientes_actualizados = False

    for cliente in clientes:
        try:
            numero         = cliente["numero"]
            nome           = cliente.get("nome") or "Cliente"
            ultimo_ficheiro = cliente.get("ultimo_ficheiro")
            frequencia     = cliente.get("frequencia", "semanal")

            if not ultimo_ficheiro or not os.path.exists(ultimo_ficheiro):
                main_function(
                    numero, None, None,
                    mensagem=f"Ola {nome}! Ainda nao recebi os teus dados. Envia o ficheiro para receberes o teu relatorio!"
                )
                continue

            df       = ingest(ultimo_ficheiro)
            metricas = calcular_metricas(df, frequencia_cliente=frequencia)
            # df libertado dentro de calcular_metricas

            pdf_path    = gerar_relatorio(metricas, nome_negocio=nome)
            pdf_filename = os.path.basename(pdf_path)
            pdf_url     = f"{base_url}/reports/{pdf_filename}"

            main_function(numero, pdf_url, pdf_filename)

            # Guarda parquet para histórico e liberta imediatamente
            semana_parquet = f"data/silver/{nome.replace(' ', '_')}_latest.parquet"
            df_novo = ingest(ultimo_ficheiro)   # releitura limpa para persistência
            df_novo.to_parquet(semana_parquet, index=False)
            del df_novo
            gc.collect()

            cliente["historico"].append(semana_parquet)
            clientes_actualizados = True

        except Exception as e:
            print(f"Erro ao processar cliente {cliente.get('nome')}: {e}")

    if clientes_actualizados:
        with open("clientes.json", "w", encoding="utf-8") as f:
            json.dump(clientes, f, ensure_ascii=False, indent=2)


def iniciar_scheduler():
    """Inicia o scheduler — chamado no lifespan do FastAPI."""
    scheduler = BackgroundScheduler()

    # Relatórios semanais — segunda-feira às 8h
    scheduler.add_job(
        enviar_relatorios_periodicos,
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="relatorios_semanais",
        max_instances=1,          # impede sobreposição de jobs se o anterior ainda estiver a correr
        misfire_grace_time=3600,  # tolera até 1h de atraso (ex: restart do servidor)
    )

    scheduler.start()
    return scheduler