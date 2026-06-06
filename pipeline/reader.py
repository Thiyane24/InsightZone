import pandas as pd
import pdfplumber
import os

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
            for table in page.extract_tables():
                if not table:
                    continue
                headers = table[0]
                data = table[1:]
                frames.append(pd.DataFrame(data, columns=headers))  

    if frames:
        return pd.concat(frames, ignore_index=True)

    return pd.DataFrame()