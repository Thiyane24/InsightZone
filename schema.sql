-- Schema InsightZone

CREATE TABLE IF NOT EXISTS clientes (
    numero               TEXT PRIMARY KEY,
    nome                 TEXT,
    negocio              TEXT,
    frequencia           TEXT DEFAULT 'semanal',
    ultimo_relatorio_url TEXT,          -- URL público do Cloudinary do último relatório gerado
    onboarding_passo     INTEGER DEFAULT 1,
    historico            TEXT DEFAULT '[]',
    criado_em            TIMESTAMP DEFAULT NOW()
);