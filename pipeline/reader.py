import pandas as pd
import pdfplumber
import os

from pipeline.metrics import _parse_numero_pt, _parse_datas_robusto


# Palavras-chave para detectar colunas de data, quantidade e valor.
# Intencionalmente NÃO inclui produto/serviço — essas colunas são
# detectadas pelo metrics._detectar_col_produto() que conhece o tipo_negocio
# do cliente. Se renomearmos aqui perdemos o sinal "servic" -> "produto"
# e todos os clientes de serviços seriam tratados como retalho.
MAPA_HEURISTICA = {
    "data": [
        "data", "date", "fecha", "dt", "dia", "day", "periodo", "period",
        "data_venda", "data venda", "sale date", "transaction date", "data_transacao",
    ],
    "quantidade": [
        "quantidade", "quantity", "qty", "qtd", "qtde", "unidades", "units",
        "amount", "count", "volume", "num", "numero",
    ],
    "valor": [
        "valor", "value", "total", "preco", "price", "revenue", "receita",
        "montante", "subtotal", "gross", "net",
        "total_venda", "total venda", "sale value", "faturacao",
        "faturacao_total", "faturacao total",
    ],
}

# Colunas que o reader.py normaliza activamente.
# 'produto' foi removido intencionalmente — ver comentário acima.
COLUNAS_NORMALIZADAS = {"data", "quantidade", "valor"}


def _mapear_colunas_heuristica(colunas: list) -> dict:
    """
    Mapeia colunas do ficheiro para data, quantidade e valor usando palavras-chave.
    Não toca em colunas de produto/serviço — essas são responsabilidade do metrics.py.
    Devolve dict {coluna_original: nome_normalizado}.
    """
    mapeamento  = {}
    ja_mapeados = set()

    for coluna in colunas:
        if not coluna:
            continue
        coluna_lower = str(coluna).lower().strip()

        for campo, keywords in MAPA_HEURISTICA.items():
            if campo in ja_mapeados:
                continue
            if any(kw == coluna_lower or kw in coluna_lower for kw in keywords):
                mapeamento[coluna] = campo
                ja_mapeados.add(campo)
                break

    return mapeamento


def _normalizar_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza o DataFrame garantindo que as colunas data, quantidade e valor
    existem com esses nomes exactos. As colunas de produto/serviço são
    preservadas com os seus nomes originais para que metrics.py as detecte.

    Retorna DataFrame normalizado, ou DataFrame vazio se as colunas mínimas
    não forem encontradas (em vez de levantar excepção — o ingest() trata).
    """
    # Remove colunas sem nome (artefactos de leitura de PDF/Excel)
    df = df.loc[:, df.columns.notna()]
    df = df.loc[:, df.columns.astype(str).str.strip() != ""]

    # Remove colunas completamente vazias
    df = df.dropna(axis=1, how="all")

    # Guarda os nomes originais antes de qualquer transformação
    colunas_originais = list(df.columns)

    # Lowercase para comparação — usa dict para evitar colisões silenciosas
    colunas_lower_map = {}
    for c in colunas_originais:
        chave = str(c).lower().strip()
        if chave not in colunas_lower_map:
            colunas_lower_map[chave] = c

    # 1. Verifica se já tem data, quantidade, valor em lowercase
    rename_directo = {}
    for nome_normalizado in COLUNAS_NORMALIZADAS:
        if nome_normalizado in colunas_lower_map:
            col_original = colunas_lower_map[nome_normalizado]
            if col_original != nome_normalizado:
                rename_directo[col_original] = nome_normalizado

    if rename_directo:
        df = df.rename(columns=rename_directo)

    # 2. Para as que ainda faltam, tenta heurística
    faltam = COLUNAS_NORMALIZADAS - set(df.columns)
    if faltam:
        colunas_restantes = [c for c in df.columns if c not in COLUNAS_NORMALIZADAS]
        mapeamento = _mapear_colunas_heuristica(colunas_restantes)
        if mapeamento:
            print(f"Mapeamento heurístico de colunas: {mapeamento}")
            df = df.rename(columns=mapeamento)

    # 3. Verificação final — se ainda faltam colunas mínimas, devolve vazio
    faltam = COLUNAS_NORMALIZADAS - set(df.columns)
    if faltam:
        print(
            f"Aviso: não foi possível identificar as colunas {faltam}. "
            f"Colunas encontradas: {list(df.columns)}"
        )
        return pd.DataFrame()

    # 4. Conversão de tipos — erros não levantam excepção (NaN preservado para _validar_silver)
    try:
        df["data"]       = _parse_datas_robusto(df["data"])
        df["quantidade"] = _parse_numero_pt(df["quantidade"])
        df["valor"]      = _parse_numero_pt(df["valor"])
    except Exception as e:
        print(f"Aviso na conversão de tipos: {e}")

    return df


def ingest(filepath: str) -> pd.DataFrame:
    """
    Lê um ficheiro CSV, Excel ou PDF e devolve um DataFrame normalizado.
    As colunas data, quantidade e valor são sempre normalizadas.
    A coluna de produto/serviço é preservada com o nome original
    para que metrics._detectar_col_produto() a identifique correctamente.
    """
    extension = os.path.splitext(filepath)[1].lstrip(".").lower()

    if extension == "csv":
        df = pd.read_csv(filepath)
    elif extension in ("xlsx", "xls"):
        df = pd.read_excel(filepath)
    elif extension == "pdf":
        df = _read_pdf(filepath)
    else:
        raise ValueError(f"Formato não suportado: {extension}. Envia um ficheiro CSV, Excel ou PDF com texto seleccionável.")

    if df.empty:
        raise ValueError("O ficheiro enviado está vazio ou não tem tabelas com dados.")

    df = _normalizar_df(df)

    if df.empty:
        raise ValueError(
            "Não foi possível identificar as colunas necessárias no ficheiro. "
            "Verifica se o ficheiro tem colunas de data, quantidade e valor."
        )

    print(f"Ingest completo: {len(df)} linhas, colunas: {list(df.columns)}")
    return df


def _read_pdf(filepath: str) -> pd.DataFrame:
    """
    Extrai tabelas de um PDF com texto seleccionável.

    PDFs digitalizados (scanned/imagem) não têm camada de texto — nenhuma
    tabela é extraída e levantamos ValueError com mensagem clara para o
    utilizador, em vez de devolver DataFrame vazio silenciosamente.
    """
    frames = []

    with pdfplumber.open(filepath) as pdf:
        n_paginas = len(pdf.pages)
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables:
                continue
            for table in tables:
                if not table or len(table) < 2:
                    continue
                headers = table[0]
                data    = table[1:]
                headers = [h if h else f"coluna_{i}" for i, h in enumerate(headers)]
                frames.append(pd.DataFrame(data, columns=headers))

    if frames:
        return pd.concat(frames, ignore_index=True)

    # PDF sem tabelas — distingue scanned de PDF vazio para dar mensagem útil
    raise ValueError(
        "Não foi possível extrair dados do PDF enviado. "
        "O PDF parece ser uma imagem digitalizada (scan) e não tem texto seleccionável. "
        "Por favor envia um ficheiro CSV ou Excel com os teus dados de vendas."
    )