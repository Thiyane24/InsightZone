import pandas as pd
import pdfplumber
import os

from pipeline.metrics import _parse_numero_pt, _parse_datas_robusto


# Palavras-chave para cada coluna esperada
MAPA_HEURISTICA = {
    "data": [
        "data", "date", "fecha", "dt", "dia", "day", "periodo", "period",
        "data_venda", "data venda", "sale date", "transaction date", "data_transacao"
    ],
    "produto": [
        "produto", "product", "item", "descricao", "description", "desc",
        "artigo", "article", "nome", "name", "mercadoria", "goods", "servico", "service"
    ],
    "quantidade": [
        "quantidade", "quantity", "qty", "qtd", "qtde", "unidades", "units",
        "amount", "count", "volume", "num", "numero"
    ],
    "valor": [
    "valor", "value", "total", "preco", "price", "revenue", "receita",
    "montante", "subtotal", "gross", "net",
    "total_venda", "total venda", "sale value",   "faturacao", "faturacao_total", "faturacao total"
    ],
}


def _mapear_colunas_heuristica(colunas: list) -> dict:
    """
    Tenta mapear as colunas do ficheiro para data, produto, quantidade, valor
    usando palavras-chave. Devolve dict de rename.
    """
    mapeamento = {}
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
    Normaliza o DataFrame para ter as colunas: data, produto, quantidade, valor.
    Usa heurística para mapear colunas desconhecidas.
    """
    colunas_esperadas = {"data", "produto", "quantidade", "valor"}
    
    df = df.loc[:, df.columns.notna()]
    colunas_lower = {str(c).lower().strip(): c for c in df.columns}

    # Se já tem todas as colunas certas (case insensitive)
    if colunas_esperadas.issubset(set(colunas_lower.keys())):
        df = df.rename(columns={v: k for k, v in colunas_lower.items()})
        df = df[list(colunas_esperadas)].copy()
    else:
        # Tenta mapear por heurística
        mapeamento = _mapear_colunas_heuristica(list(df.columns))
        print(f"Mapeamento de colunas: {mapeamento}")

        if mapeamento:
            df = df.rename(columns=mapeamento)

        # Verifica se ficaram as colunas necessárias
        missing = colunas_esperadas - set(df.columns)
        if missing:
            # Tenta uma última vez com colunas em lowercase
            df.columns = df.columns.str.lower().str.strip()
            missing = colunas_esperadas - set(df.columns)
            if missing:
                raise ValueError(
                    f"Nao foi possivel identificar as colunas: {missing}. "
                    f"Colunas encontradas: {list(df.columns)}"
                )
        
        df = df[list(colunas_esperadas)].copy()

    try:
        # Datas — múltiplos formatos sem ambiguidade (PT, ISO, EN)
        df['data'] = _parse_datas_robusto(df['data'])

        # Quantidade e valor — formato PT, NaN preservado para rejeição
        # posterior pelo _validar_silver em metrics.py (não usar fillna aqui)
        df['quantidade'] = _parse_numero_pt(df['quantidade'])
        df['valor']      = _parse_numero_pt(df['valor'])
    except Exception as e:
        print(f"Erro na conversao de tipos: {e}")

    return df


def ingest(filepath: str) -> pd.DataFrame:
    """Extracts a file and converts it into a pandas DataFrame."""
    extension = os.path.splitext(filepath)[1].lstrip(".").lower()

    if extension == 'csv':
        df = pd.read_csv(filepath)
    elif extension in ['xlsx', 'xls']:
        df = pd.read_excel(filepath)
    elif extension == 'pdf':
        df = read_pdf(filepath)
    else:
        raise ValueError(f'Formato nao suportado: {extension}')

    if df.empty:
        raise ValueError("O ficheiro enviado esta vazio.")

    # Normaliza as colunas
    df = _normalizar_df(df)

    # Salva os dados brutos extraidos
    os.makedirs('data/bronze', exist_ok=True)
    filename = os.path.splitext(os.path.basename(filepath))[0]
    dest = f'data/bronze/{filename}.parquet'
    df.to_parquet(dest, index=False)
    print(f'Bronze: {len(df)} linhas extraidas de {filepath} → {dest}')
    return df


def read_pdf(filepath: str) -> pd.DataFrame:
    """Extrai tabelas de um PDF com texto seleccionavel."""
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
                data = table[1:]
                headers = [h if h else f"coluna_{i}" for i, h in enumerate(headers)]
                frames.append(pd.DataFrame(data, columns=headers))

    if frames:
        return pd.concat(frames, ignore_index=True)

    return pd.DataFrame()