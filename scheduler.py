import os
import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUD_NAME"),
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("API_SECRET")
)


def _upload_raw(local_path: str, public_id: str, apagar_local: bool = True) -> str:
    """Upload genérico de ficheiro raw para o Cloudinary. Devolve URL público."""
    try:
        result = cloudinary.uploader.upload(
            local_path,
            resource_type="raw",
            public_id=public_id,
            overwrite=True,
            access_mode="public",
            type="upload"
        )
        url = result["secure_url"]
        print(f"Cloudinary upload: {url}")
        return url
    except Exception as e:
        print(f"Erro ao fazer upload para Cloudinary ({public_id}): {e}")
        raise
    finally:
        if apagar_local and os.path.exists(local_path):
            try:
                os.remove(local_path)
                print(f"Ficheiro local apagado: {local_path}")
            except Exception as e:
                print(f"Aviso: nao foi possivel apagar {local_path}: {e}")


def upload_pdf(pdf_path: str) -> str:
    """Faz upload do PDF e apaga o ficheiro local. Devolve URL público."""
    filename = os.path.splitext(os.path.basename(pdf_path))[0]
    return _upload_raw(pdf_path, f"insightzone/pdfs/{filename}", apagar_local=True)


def upload_ficheiro_vendas(filepath: str) -> str:
    """
    Faz upload do ficheiro de vendas (CSV/XLSX) para o Cloudinary.
    NÃO apaga o ficheiro local — quem chama decide quando apagar.
    Devolve URL público.
    """
    filename = os.path.basename(filepath)
    public_id = f"insightzone/vendas/{os.path.splitext(filename)[0]}"
    return _upload_raw(filepath, public_id, apagar_local=False)


def download_ficheiro(url: str, dest_path: str) -> str:
    """
    Descarrega um ficheiro do Cloudinary para um path local.
    Devolve o path local.
    """
    import httpx
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    with httpx.stream("GET", url, timeout=60) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    print(f"Ficheiro descarregado: {dest_path}")
    return dest_path