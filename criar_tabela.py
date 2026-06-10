import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cursor = conn.cursor()

# Cria a tabela com TODAS as colunas usadas pelo app.py.
# Se a tabela ja existir, adiciona as colunas que faltam (ALTER TABLE IF NOT EXISTS).
cursor.execute("""
    CREATE TABLE IF NOT EXISTS clientes (
        numero                TEXT PRIMARY KEY,
        nome                  TEXT,
        negocio               TEXT,
        frequencia            TEXT DEFAULT 'semanal',
        ultimo_ficheiro       TEXT,
        ultimo_ficheiro_url   TEXT,
        ultimo_relatorio_url  TEXT,
        onboarding_passo      INTEGER DEFAULT 1,
        historico             TEXT DEFAULT '[]',
        modo                  TEXT,
        criado_em             TIMESTAMP DEFAULT NOW()
    )
""")

# adiciona colunas que possam faltar em BDs existentes.
migracoes = [
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS ultimo_ficheiro_url  TEXT",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS ultimo_relatorio_url TEXT",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS modo                  TEXT",
]
for sql in migracoes:
    cursor.execute(sql)

conn.commit()
cursor.close()
conn.close()

print("Tabela criada/migrada com sucesso!")