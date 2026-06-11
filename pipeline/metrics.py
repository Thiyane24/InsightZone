import gc
import pandas as pd
from datetime import datetime, timedelta


def _parse_numero_pt(serie: pd.Series) -> pd.Series:
    return (
        serie.astype(str)
             .str.strip()
             .str.replace(r'\s(?=\d{3}(?!\d))', '', regex=True)  # ← linha nova
             .str.replace(r'\.(?=\d{3})', '', regex=True)
             .str.replace(',', '.', regex=False)
             .pipe(lambda s: pd.to_numeric(s, errors='coerce'))
    )


def _parse_datas_robusto(serie: pd.Series) -> pd.Series:
    """
    Tenta multiplos formatos de data em sequencia, sem ambiguidade.
    Formatos suportados:
      YYYY-MM-DD  (ISO)
      YYYY/MM/DD  (variante ISO com barras)
      DD/MM/YYYY  (PT)
      Month D, YYYY  (EN: "June 3, 2026")
      DD-MM-YYYY
    Datas invalidas ficam NaT.
    """
    s = serie.astype(str).str.strip()
    resultado = pd.Series([pd.NaT] * len(s), dtype='datetime64[ns]', index=serie.index)

    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%B %d, %Y', '%d-%m-%Y'):
        mask = resultado.isna()
        if not mask.any():
            break
        tentativa = pd.to_datetime(s.where(mask), format=fmt, errors='coerce')
        resultado = resultado.fillna(tentativa)

    return resultado


def _detectar_col_produto(colunas: list[str], tipo_negocio: str) -> str | None:
    """
    Detecta a coluna de produto/servico conforme o tipo de negocio.

    Para retalho/agropecuaria: prioriza vocabulario de produto fisico.
    Para servicos: prioriza vocabulario de servico/descricao.
    Para outro: tenta os dois vocabularios.

    Retorna o nome da coluna ou None se nao encontrar.
    """
    vocab_retalho  = ('prod', 'item', 'mercador', 'artigo', 'sku')
    vocab_servicos = ('servic', 'descri', 'obra', 'tarefa', 'activid', 'activ',
                      'servico', 'prestac', 'trabalho', 'job', 'tipo_serv')

    tipo = (tipo_negocio or "retalho").lower()

    if tipo in ("servicos", "servico"):
        ordens = (vocab_servicos, vocab_retalho)
    elif tipo in ("retalho", "agropecuaria"):
        ordens = (vocab_retalho, vocab_servicos)
    else:
        ordens = (vocab_retalho + vocab_servicos,)

    for vocab in ordens:
        col = next((c for c in colunas if any(k in c for k in vocab)), None)
        if col:
            return col

    return None


def _remover_outliers_total(
    df: pd.DataFrame,
    col_total: str,
    col_qtd: str | None,
    col_preco: str | None,
) -> pd.DataFrame:
    """
    Remove linhas cujo valor de Total é inconsistente ou anómalo.

    Estratégia em duas camadas:

    Camada 1 — Validação cruzada Qtd × Preço (quando ambas as colunas existem):
        Rejeita linhas onde |Total - (Qtd × Preço)| > 10% do valor calculado.
        Apanha placeholders como 99999 sem tocar em descontos ou arredondamentos
        legítimos.

    Camada 2 — IQR fence (sempre aplicada após a camada 1):
        Calcula Q1 e Q3 da coluna Total. Define o limite superior como
        Q3 + 3 × IQR (fence alargada para não rejeitar transacções grandes
        legítimas). Remove apenas valores acima desse limite.
        Com IQR × 3 em vez do clássico × 1.5, só outliers extremos são
        removidos — adequado para dados de PMEs com alta variância natural.
    """
    if col_total not in df.columns or df.empty:
        return df

    n_antes = len(df)

    # --- Camada 1: Qtd × Preço ---
    if (
        col_qtd and col_preco
        and col_qtd in df.columns
        and col_preco in df.columns
    ):
        qtd   = pd.to_numeric(df[col_qtd],   errors='coerce').fillna(0)
        preco = pd.to_numeric(df[col_preco], errors='coerce').fillna(0)
        total_calc = qtd * preco

        # Só aplica a linhas onde temos Qtd e Preço válidos (> 0)
        mascara_valida = (qtd > 0) & (preco > 0)
        if mascara_valida.any():
            desvio = (df[col_total] - total_calc).abs()
            # Tolerância de 10% — absorve descontos e arredondamentos
            tolerancia = total_calc.replace(0, 1) * 0.10
            inconsistente = mascara_valida & (desvio > tolerancia)
            n_rejeitados = inconsistente.sum()
            if n_rejeitados > 0:
                df = df[~inconsistente].reset_index(drop=True)

    # --- Camada 2: IQR fence (Q3 + 3 × IQR) ---
    if len(df) >= 4:  # IQR não é fiável com menos de 4 pontos
        q1  = df[col_total].quantile(0.25)
        q3  = df[col_total].quantile(0.75)
        iqr = q3 - q1
        if iqr > 0:
            limite_superior = q3 + 3 * iqr
            n_antes_iqr = len(df)
            df = df[df[col_total] <= limite_superior].reset_index(drop=True)

    return df


def _validar_silver(
    df: pd.DataFrame,
    col_total: str,
    col_qtd: str | None,
    col_preco: str | None = None,
) -> pd.DataFrame:
    """
    Rejeita linhas sujas ANTES de qualquer agregacao.

    Passos:
    1. Remove linhas completamente vazias.
    2. Remove linhas cujo campo ID é igual ao nome da coluna (cabeçalhos duplicados).
    3. Converte e valida col_total — NaN e valores <= 0 são rejeitados.
    4. Converte e valida col_qtd — NaN e valores <= 0 são rejeitados.
    5. Remove linhas sem produto/total quando ambas as colunas existem.
    6. Remove outliers de Total via _remover_outliers_total.
    """
    df = df.dropna(how='all')

    col_id_raw = next((c for c in df.columns if c in ('id', 'fatura', 'recibo', 'order_id', 'invoice')), None)
    if col_id_raw:
        df = df[df[col_id_raw].astype(str).str.lower() != col_id_raw.lower()]

    if col_total and col_total in df.columns:
        df[col_total] = _parse_numero_pt(df[col_total])
        df = df[df[col_total].notna()]
        df = df[df[col_total] > 0]

    if col_qtd and col_qtd in df.columns:
        df[col_qtd] = _parse_numero_pt(df[col_qtd])
        df = df[df[col_qtd].notna()]
        df = df[df[col_qtd] > 0]

    col_prod = next((c for c in df.columns if 'prod' in c or 'item' in c
                     or 'servic' in c or 'descri' in c), None)
    if col_prod and col_total:
        df = df.dropna(subset=[col_prod, col_total])

    # Remoção de outliers — camada 1 (Qtd×Preço) + camada 2 (IQR fence)
    df = _remover_outliers_total(df, col_total, col_qtd, col_preco)

    return df.reset_index(drop=True)


def _hora_de_pico(df: pd.DataFrame, col_data: str) -> str | None:
    """
    Detecta a hora com mais vendas/servicos no DataFrame.
    So funciona se a coluna de data tiver componente de hora (ex: "2026-06-10 14:30").
    Devolve string "14h-15h" ou None se nao houver informacao de hora.
    """
    try:
        horas = df[col_data].dt.hour
        if horas.nunique() <= 1:
            return None
        hora_pico = int(horas.value_counts().idxmax())
        return f"{hora_pico:02d}h-{hora_pico + 1:02d}h"
    except Exception:
        return None


def _variacao_ontem(df: pd.DataFrame, col_data: str, col_total: str) -> float | None:
    """
    Compara a faturacao de hoje com a de ontem.
    Devolve a variacao em percentagem (positivo = crescimento, negativo = queda).
    Devolve None se nao houver dados de ontem no DataFrame.
    """
    try:
        hoje  = datetime.now().date()
        ontem = hoje - timedelta(days=1)

        vendas_por_dia = df.groupby(df[col_data].dt.date)[col_total].sum()

        total_hoje  = vendas_por_dia.get(hoje, None)
        total_ontem = vendas_por_dia.get(ontem, None)

        if total_hoje is None or total_ontem is None or total_ontem == 0:
            return None

        return round(((total_hoje - total_ontem) / total_ontem) * 100, 1)
    except Exception:
        return None


def calcular_metricas(
    df: pd.DataFrame,
    frequencia_cliente: str = "semanal",
    periodo: str | None = None,
    tipo_negocio: str = "retalho",
) -> dict:
    """
    Calcula metricas de vendas/servicos a partir de um DataFrame.

    Parametro `tipo_negocio`:
      - "retalho"      -> detecta produtos, usa vocabulario de retalho
      - "servicos"     -> detecta servicos/descricoes, adapta labels
      - "agropecuaria" -> tratado como retalho para deteccao de colunas
      - "outro"        -> tenta os dois vocabularios

    Parametro `periodo`:
      - None    -> comportamento anterior (filtra pelo ano mais recente)
      - "hoje"  -> so as linhas de hoje
      - "semana"-> semana corrente (segunda a domingo)
      - "mes"   -> mes corrente
    """

    # 1. NORMALIZACAO DE COLUNAS
    df.columns = [col.lower().strip() for col in df.columns]

    # 2. MAPEAMENTO DINAMICO DE COLUNAS
    col_data    = next((c for c in df.columns if 'data' in c or 'date' in c), None)
    col_total   = next((c for c in df.columns if 'total' in c or 'revenue' in c
                        or 'faturac' in c or 'valor' in c), None)
    col_qtd     = next((c for c in df.columns if 'qtd' in c or 'quant' in c or 'qty' in c), None)
    col_produto = _detectar_col_produto(list(df.columns), tipo_negocio)

    # 3. PRECO UNITARIO
    col_preco = next((c for c in df.columns if 'prec' in c or 'price' in c), None)
    if col_preco:
        df[col_preco] = _parse_numero_pt(df[col_preco])

    # 4. CALCULO DO TOTAL REAL
    if col_qtd:
        qtd_serie = _parse_numero_pt(df[col_qtd])
        if not col_total and col_preco:
            df['total_calculado'] = df[col_preco].fillna(0) * qtd_serie.fillna(0)
            col_total = 'total_calculado'

    # VALIDACAO SILVER (inclui remoção de outliers)
    df = _validar_silver(df, col_total, col_qtd, col_preco)

    if df.empty:
        return _resultado_vazio(tipo_negocio)

    # 5. PARSING DE DATAS
    if col_data:
        df[col_data] = _parse_datas_robusto(df[col_data])
        df = df.dropna(subset=[col_data])

        hoje = datetime.now().date()

        if periodo == "hoje":
            df = df[df[col_data].dt.date == hoje]
        elif periodo == "semana":
            inicio_semana = hoje - timedelta(days=hoje.weekday())
            df = df[(df[col_data].dt.date >= inicio_semana) & (df[col_data].dt.date <= hoje)]
        elif periodo == "mes":
            df = df[
                (df[col_data].dt.year  == hoje.year) &
                (df[col_data].dt.month == hoje.month)
            ]
        else:
            ano_mais_recente = int(df[col_data].dt.year.max())
            df = df[df[col_data].dt.year == ano_mais_recente]

        if df.empty:
            col_data = None

    if not col_data:
        df['data_fallback'] = pd.Timestamp(datetime.now().date())
        col_data = 'data_fallback'

    # 6. TIPOS NUMERICOS FINAIS
    if not col_total:
        df['total_zero'] = 0.0
        col_total = 'total_zero'

    if not col_qtd:
        df['qtd_um'] = 1
        col_qtd = 'qtd_um'

    # 7. KPIs CORE
    total_faturado = float(df[col_total].sum())

    col_id       = next((c for c in df.columns if c in ('id', 'fatura', 'recibo', 'order_id', 'invoice')), None)
    col_vendedor = next((c for c in df.columns if 'vend' in c or 'seller' in c or 'agent' in c), None)

    if col_id:
        total_transacoes = int(df[col_id].nunique())
    elif col_vendedor and col_data:
        total_transacoes = int(df.groupby([df[col_data].dt.date, col_vendedor]).ngroups)
    else:
        total_transacoes = int(len(df))

    vendas_por_dia = df.groupby(df[col_data].dt.date)[col_total].sum()
    melhor_dia_str = (
        vendas_por_dia.idxmax().strftime('%Y-%m-%d')
        if not vendas_por_dia.empty
        else datetime.now().strftime('%Y-%m-%d')
    )

    # 8. TOP PRODUTOS/SERVICOS
    if col_produto:
        top_produtos_dict = (
            df.groupby(col_produto)[col_qtd]
              .sum()
              .sort_values(ascending=False)
              .head(5)
              .to_dict()
        )
        top_produtos_dict = {str(k): int(v) for k, v in top_produtos_dict.items()}
    else:
        placeholder = "Nenhum servico detetado" if _e_servicos(tipo_negocio) else "Nenhum produto detetado"
        top_produtos_dict = {placeholder: 0}

    # 9. METRICAS AVANCADAS
    mes_nome     = datetime.now().strftime('%B')
    ticket_medio = total_faturado / total_transacoes if total_transacoes > 0 else 0.0

    hora_pico      = None
    variacao_ontem = None
    produto_do_dia = None

    if periodo == "hoje" or frequencia_cliente == "diario":
        hora_pico      = _hora_de_pico(df, col_data)
        variacao_ontem = _variacao_ontem(df, col_data, col_total)

        if col_produto and top_produtos_dict:
            primeiro = list(top_produtos_dict.keys())[0]
            placeholder = "Nenhum servico detetado" if _e_servicos(tipo_negocio) else "Nenhum produto detetado"
            if primeiro != placeholder:
                produto_do_dia = {
                    "nome":       primeiro,
                    "quantidade": top_produtos_dict[primeiro],
                    "faturacao":  float(
                        df[df[col_produto].astype(str) == primeiro][col_total].sum()
                    ),
                }

    # 10. LIBERTACAO DE MEMORIA
    del df
    gc.collect()

    return {
        "total":               total_faturado,
        "total_transacoes":    total_transacoes,
        "ticket_medio":        ticket_medio,
        "melhor_dia":          melhor_dia_str,
        "top_produtos":        top_produtos_dict,

        "total_mensal":        total_faturado,
        "transacoes_mensal":   total_transacoes,
        "ticket_medio_mensal": ticket_medio,
        "melhor_dia_mes":      melhor_dia_str,
        "top_produtos_mes":    top_produtos_dict,
        "mes_nome":            mes_nome,

        "variacao_pct":        None,

        "hora_pico":           hora_pico,
        "variacao_ontem":      variacao_ontem,
        "produto_do_dia":      produto_do_dia,

        "tipo_negocio":        (tipo_negocio or "retalho").lower(),
    }


def _e_servicos(tipo_negocio: str) -> bool:
    """True se o negocio e prestador de servicos."""
    return (tipo_negocio or "").lower() in ("servicos", "servico")


def _resultado_vazio(tipo_negocio: str = "retalho") -> dict:
    """Retorna estrutura vazia quando o ficheiro nao tem dados validos."""
    mes_nome    = datetime.now().strftime('%B')
    placeholder = "Sem dados validos"
    return {
        "total": 0.0, "total_transacoes": 0, "ticket_medio": 0.0,
        "melhor_dia": datetime.now().strftime('%Y-%m-%d'),
        "top_produtos": {placeholder: 0},
        "total_mensal": 0.0, "transacoes_mensal": 0, "ticket_medio_mensal": 0.0,
        "melhor_dia_mes": datetime.now().strftime('%Y-%m-%d'),
        "top_produtos_mes": {placeholder: 0},
        "mes_nome": mes_nome, "variacao_pct": None,
        "hora_pico": None, "variacao_ontem": None, "produto_do_dia": None,
        "tipo_negocio": (tipo_negocio or "retalho").lower(),
    }
