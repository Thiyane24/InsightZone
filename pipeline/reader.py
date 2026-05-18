import pandas as pd 
import pdfplumber

def ler_ficheiro(caminho):
    if caminho.endswith('.csv'):
        return pd.read_csv(caminho)
    elif caminho.endswith('.xlsx', '.xls'):
        return pd.read_excel(caminho)
    elif caminho.endswith('.pdf'):
        return ler_pdf(caminho)
    return None

def ler_pdf(caminho):
    with pdfplumber.open(caminho) as pdf:
        texto = pdf.pages[0].extract_text()
        if not texto or len(texto)<50:
            return None
        tabelas = []
        for pagina in paginas:
            tabelas.extend(pagina.extract_tables())
    if not tabelas:
        return None
    return pd.DataFrame(tabelas[0][1:], columns=tabelas[0][0])