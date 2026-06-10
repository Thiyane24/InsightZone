import gc
import pandas as pd
from datetime import datetime, timedelta


def _parse_numero_pt(serie: pd.Series) -> pd.Series:
    """
    Converte uma coluna de texto com formato PT (ponto de milhar, vírgula decimal)
    para float. Valores que não sejam convertíveis tornam-se NaN.
    Exemplo: "1.500,00" -> 1500.0 | "vinte" -> NaN | "N/A" -> NaN
    """
    return (
        serie.astype(str)
             .str.strip()
             .str.replace(r'\.(?=\d{3})', '', regex=True)
             .str.replace(',', '.', regex=False)
             .pipe(lambda s: pd.to_numeric(s, errors='coerce'))
    )


def _parse_datas_robusto(serie: pd.Series) -> pd.Series:
    """
    Tenta multiplos formatos de data em sequencia, sem ambiguidade.
    Formatos suportados:
      YYYY-MM-DD  (ISO)
      DD/MM/YYYY  (PT)
      Month D, YYYY  (EN: "June 3, 2026")
      DD-MM-YYYY
    Datas invalidas ficam NaT.
    """
    s = serie.astype(str).str.strip()
    resultado = pd.Series([pd.NaT] * len(s), dtype='datetime64[ns]', index=serie.index)

    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%B %d, %Y', '%d-%m-%Y'):
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
    # Vocabulario de retalho (produtos fisicos)
    vocab_retalho = ('prod', 'item', 'mercador', 'artigo', 'sku')

    # Vocabulario de servicos
    vocab_servicos = ('servic', 'descri', 'obra', 'tarefa', 'activid', 'activ',
                      'servico', 'prestac', 'trabalho', 'job', 'tipo_serv')

    tipo = (tipo_negocio or "retalho").lower()

    if tipo in ("servicos", "servico"):
        # Para servicos: tenta primeiro vocabulario de servico, depois retalho
        ordens = (vocab_servicos, vocab_retalho)
    elif tipo in ("retalho", "agropecuaria"):
        # Para retalho: tenta primeiro vocabulario de produto, depois servico
        ordens = (vocab_retalho, vocab_servicos)
    else:
        # "outro" ou desconhecido: tenta os dois sem preferencia
        ordens = (vocab_retalho + vocab_servicos,)

    for vocab in ordens:
        col = next((c for c in colunas if any(k in c for k in vocab)), None)
        if col:
            return col

    return None


def _validar_silver(df: pd.DataFrame, col_total: str, col_qtd: str | None) -> pd.DataFrame:
    """
    Rejeita linhas sujas ANTES de qualquer agregacao.
    Chamado uma vez, logo apos a deteccao de colunas.
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

    # ALTERADO: deteccao de produto/servico agora usa tipo_negocio
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

    # VALIDACAO SILVER
    df = _validar_silver(df, col_total, col_qtd)

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
    # A chave do dicionario usa "produto" internamente o report.py adapta o label
    # conforme tipo_negocio para nao precisar de renomear as chaves do dict.
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
        # Label do placeholder adapta-se ao tipo de negocio
        placeholder = "Nenhum servico detetado" if _e_servicos(tipo_negocio) else "Nenhum produto detetado"
        top_produtos_dict = {placeholder: 0}

    # 9. METRICAS AVANCADAS
    mes_nome     = datetime.now().strftime('%B')
    ticket_medio = total_faturado / total_transacoes if total_transacoes > 0 else 0.0

    # METRICAS DIARIAS
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

        # Aliases mensais
        "total_mensal":        total_faturado,
        "transacoes_mensal":   total_transacoes,
        "ticket_medio_mensal": ticket_medio,
        "melhor_dia_mes":      melhor_dia_str,
        "top_produtos_mes":    top_produtos_dict,
        "mes_nome":            mes_nome,

        "variacao_pct":        None,

        # Metricas diarias
        "hora_pico":           hora_pico,
        "variacao_ontem":      variacao_ontem,
        "produto_do_dia":      produto_do_dia,

        # NOVO: tipo_negocio propagado para o report.py
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