import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS clientes (
        numero            TEXT PRIMARY KEY,
        nome              TEXT,
        negocio           TEXT,
        frequencia        TEXT DEFAULT 'semanal',
        ultimo_ficheiro   TEXT,
        onboarding_passo  INTEGER DEFAULT 1,
        historico         TEXT DEFAULT '[]',
        criado_em         TIMESTAMP DEFAULT NOW()
    )
""")

conn.commit()
cursor.close()
conn.close()

print("Tabela criada com sucesso!")