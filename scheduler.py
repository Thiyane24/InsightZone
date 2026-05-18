from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()

#scheduled para todas segundas as 8h00

scheduler.add_job(
    func=enviar_relatorio_todos_clientes,
    trigger="cron",
    day_of_week="mon",
    hour=8,
    minute=0
)

scheduler.start()