import os
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUD_NAME"),
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("API_SECRET")
)


def upload_pdf(pdf_path: str) -> str:
    """Faz upload do PDF para o Cloudinary e apaga o ficheiro local. Devolve o URL público."""
    try:
        filename = os.path.splitext(os.path.basename(pdf_path))[0]
        result = cloudinary.uploader.upload(
            pdf_path,
            resource_type="raw",
            public_id=f"insightzone/{filename}",
            overwrite=True
        )
        url = result["secure_url"]
        print(f"PDF enviado para Cloudinary: {url}")
        return url
    except Exception as e:
        print(f"Erro ao fazer upload para Cloudinary: {e}")
        raise
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            print(f"Ficheiro local apagado: {pdf_path}")