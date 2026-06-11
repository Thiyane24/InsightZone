import pandas as pd
import pdfplumber
import os

from pipeline.metrics import _parse_numero_pt, _parse_datas_robusto


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

# 'quantidade' removida das colunas obrigatórias — ficheiros de serviços
# tipicamente não têm essa coluna; o calcular_metricas já trata col_qtd=None
# criando qtd_um=1 para todas as linhas.
COLUNAS_NORMALIZADAS = {"data", "valor"}


def _mapear_colunas_heuristica(colunas: list) -> dict:
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
    df = df.loc[:, df.columns.notna()]
    df = df.loc[:, df.columns.astype(str).str.strip() != ""]
    df = df.dropna(axis=1, how="all")

    colunas_originais = list(df.columns)

    colunas_lower_map = {}
    for c in colunas_originais:
        chave = str(c).lower().strip()
        if chave not in colunas_lower_map:
            colunas_lower_map[chave] = c

    # 1. Rename directo para data, quantidade, valor (se existirem)
    rename_directo = {}
    for nome_normalizado in ("data", "quantidade", "valor"):
        if nome_normalizado in colunas_lower_map:
            col_original = colunas_lower_map[nome_normalizado]
            if col_original != nome_normalizado:
                rename_directo[col_original] = nome_normalizado

    if rename_directo:
        df = df.rename(columns=rename_directo)

    # 2. Heurística para colunas que ainda faltam
    faltam = COLUNAS_NORMALIZADAS - set(df.columns)
    if faltam:
        colunas_restantes = [c for c in df.columns if c not in COLUNAS_NORMALIZADAS]
        mapeamento = _mapear_colunas_heuristica(colunas_restantes)
        if mapeamento:
            print(f"Mapeamento heurístico de colunas: {mapeamento}")
            df = df.rename(columns=mapeamento)

    # 3. Verificação final — só data e valor são obrigatórias
    faltam = COLUNAS_NORMALIZADAS - set(df.columns)
    if faltam:
        print(
            f"Aviso: não foi possível identificar as colunas {faltam}. "
            f"Colunas encontradas: {list(df.columns)}"
        )
        return pd.DataFrame()

    # 4. Conversão de tipos
    try:
        df["data"]  = _parse_datas_robusto(df["data"])
        df["valor"] = _parse_numero_pt(df["valor"])
        if "quantidade" in df.columns:
            df["quantidade"] = _parse_numero_pt(df["quantidade"])
    except Exception as e:
        print(f"Aviso na conversão de tipos: {e}")

    return df


def ingest(filepath: str) -> pd.DataFrame:
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
            "Verifica se o ficheiro tem colunas de data e valor."
        )

    print(f"Ingest completo: {len(df)} linhas, colunas: {list(df.columns)}")
    return df


def _read_pdf(filepath: str) -> pd.DataFrame:
    frames = []

    with pdfplumber.open(filepath) as pdf:
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

    raise ValueError(
        "Não foi possível extrair dados do PDF enviado. "
        "O PDF parece ser uma imagem digitalizada (scan) e não tem texto seleccionável. "
        "Por favor envia um ficheiro CSV ou Excel com os teus dados de vendas."
    )