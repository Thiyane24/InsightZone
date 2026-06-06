import json
import os
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from pipeline.reader import ingest
from pipeline.metrics import calcular_metricas
from pipeline.report import gerar_relatorio
from pipeline.sender import main_function

load_dotenv()

def enviar_relatorios_semanais():
    """Corre todas segunda-feiras às 8h  gera e envia relatório a cada cliente."""
    
    # 1. Carregar lista de clientes
    with open("clientes.json", "r", encoding="utf-8") as f:
        clientes = json.load(f)

    base_url = os.getenv("BASE_URL")

    for cliente in clientes:
        try:
            numero = cliente["numero"]
            nome = cliente["nome"]
            ultimo_ficheiro = cliente.get("ultimo_ficheiro")

            # 2. Verificar se o cliente enviou dados esta semana
            if not ultimo_ficheiro or not os.path.exists(ultimo_ficheiro):
                main_function(
                    numero,
                    None,
                    None,
                    mensagem=f"Ola {nome}! Ainda nao recebi os teus dados desta semana. Envia o ficheiro para receberes o teu relatorio!"
                )
                continue

            # 3. Pipeline completo
            df = ingest(ultimo_ficheiro)

            # 4. Carregar semana anterior se existir
            df_anterior = None
            if cliente["historico"]:
                ultimo_historico = cliente["historico"][-1]
                if os.path.exists(ultimo_historico):
                    df_anterior = pd.read_parquet(ultimo_historico)

            metricas = calcular_metricas(df, df_anterior)
            pdf_path = gerar_relatorio(metricas, nome_negocio=nome)

            # 5. Construir URL público
            pdf_filename = os.path.basename(pdf_path)
            pdf_url = f"{base_url}/reports/{pdf_filename}"

            # 6. Enviar ao cliente
            main_function(numero, pdf_url, pdf_filename)

            # 7. Atualizar histórico do cliente
            semana_parquet = f"data/silver/{nome.replace(' ', '_')}_latest.parquet"
            df.to_parquet(semana_parquet, index=False)
            cliente["historico"].append(semana_parquet)

        except Exception as e:
            print(f"Erro ao processar cliente {cliente.get('nome')}: {e}")

    # 8. Guardar clientes.json atualizado
    with open("clientes.json", "w", encoding="utf-8") as f:
        json.dump(clientes, f, ensure_ascii=False, indent=2)


def iniciar_scheduler():
    """Inicia o scheduler — chamado no lifespan do FastAPI."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        enviar_relatorios_semanais,
        CronTrigger(day_of_week="mon", hour=8, minute=0)
    )
    scheduler.start()
    return scheduler