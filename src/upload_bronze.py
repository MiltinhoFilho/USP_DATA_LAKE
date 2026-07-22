"""Upload Bronze layer JSON/PDF files to MinIO."""

import argparse
from pathlib import Path

from urllib3.exceptions import MaxRetryError

from src.minio_client import (
    ensure_bucket,
    get_json_prefix,
    get_minio_client,
    get_pdf_prefix,
    upload_file,
)

BRONZE_RAW_DIR = Path(__file__).resolve().parent.parent / "bronze" / "raw"


def upload_bronze_file(file_path: Path) -> dict:
    """Envia um único objeto Bronze ao prefixo correspondente ao seu formato."""
    if not file_path.is_file() or file_path.stat().st_size <= 0:
        raise ValueError(f"Arquivo Bronze vazio ou inexistente: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix not in {".json", ".pdf"}:
        raise ValueError("Apenas arquivos JSON ou PDF podem ser enviados à Bronze")

    client = get_minio_client()
    bucket_name = ensure_bucket(client)
    prefix = get_pdf_prefix() if suffix == ".pdf" else get_json_prefix()
    object_name = f"{prefix}{file_path.name}"
    upload_file(file_path, object_name, client=client, bucket_name=bucket_name)
    stat = client.stat_object(bucket_name, object_name)
    return {
        "bucket": bucket_name,
        "object_key": object_name,
        "size_bytes": int(stat.size),
        "content_type": stat.content_type,
    }


def upload_bronze_files(bronze_dir: Path = BRONZE_RAW_DIR) -> tuple[int, int]:
    bronze_files = sorted(bronze_dir.glob("*.json")) + sorted(bronze_dir.glob("*.pdf"))

    if not bronze_files:
        raise FileNotFoundError(
            f"Nenhum arquivo Bronze (.json ou .pdf) encontrado em {bronze_dir}. "
            "Adicione arquivos PDF ou JSON e tente novamente."
        )

    try:
        client = get_minio_client()
        bucket_name = ensure_bucket(client)
    except MaxRetryError as error:
        raise ConnectionError(
            "Nao foi possivel conectar ao MinIO em localhost:9000. "
            "Suba o servico com: docker compose -f docker/docker-compose.yml up -d"
        ) from error

    uploaded = 0
    failed = 0

    print(f"Enviando {len(bronze_files)} arquivos para bucket '{bucket_name}'...")

    for file_path in bronze_files:
        try:
            prefix = get_pdf_prefix() if file_path.suffix.lower() == ".pdf" else get_json_prefix()
            object_name = f"{prefix}{file_path.name}"
            upload_file(file_path, object_name, client=client, bucket_name=bucket_name)
            print(f"  OK  {object_name}")
            uploaded += 1
        except RuntimeError as error:
            print(f"  ERRO  {file_path.name}: {error}")
            failed += 1

    print(f"\nResumo: {uploaded} enviados, {failed} falhas.")
    print("Console MinIO: http://localhost:9001")
    print(f"Bucket: {bucket_name} | Prefixo: raw/")

    return uploaded, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload Bronze para MinIO")
    parser.add_argument(
        "--bronze-dir",
        type=Path,
        default=BRONZE_RAW_DIR,
        help="Diretorio com arquivos Bronze (.json ou .pdf)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uploaded, failed = upload_bronze_files(args.bronze_dir)

    if failed:
        raise SystemExit(1)

    print(f"Upload concluido: {uploaded} arquivos na camada Bronze.")


if __name__ == "__main__":
    main()
