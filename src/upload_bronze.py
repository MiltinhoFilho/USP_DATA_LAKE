"""Upload Bronze layer JSON files to MinIO."""

import argparse
from pathlib import Path
from urllib3.exceptions import MaxRetryError

from minio_client import ensure_bucket, get_minio_client, upload_file

BRONZE_RAW_DIR = Path(__file__).resolve().parent.parent / "bronze" / "raw"


def upload_bronze_files(bronze_dir: Path = BRONZE_RAW_DIR) -> tuple[int, int]:
    json_files = sorted(bronze_dir.glob("usp_news_*.json"))

    if not json_files:
        raise FileNotFoundError(
            f"Nenhum arquivo JSON encontrado em {bronze_dir}. "
            "Execute primeiro: python src/scraper.py"
        )

    try:
        client = get_minio_client()
        bucket_name = ensure_bucket(client)
    except MaxRetryError as error:
        raise ConnectionError(
            "Não foi possível conectar ao MinIO em localhost:9000. "
            "Suba o serviço com: cd docker && docker compose up -d"
        ) from error

    uploaded = 0
    failed = 0

    print(f"Enviando {len(json_files)} arquivos para bucket '{bucket_name}'...")

    for file_path in json_files:
        object_name = f"raw/{file_path.name}"
        try:
            upload_file(file_path, object_name, client=client, bucket_name=bucket_name)
            print(f"  OK  {object_name}")
            uploaded += 1
        except RuntimeError as error:
            print(f"  ERRO  {file_path.name}: {error}")
            failed += 1

    print(f"\nResumo: {uploaded} enviados, {failed} falhas.")
    print(f"Console MinIO: http://localhost:9001")
    print(f"Bucket: {bucket_name} | Prefixo: raw/")

    return uploaded, failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload Bronze para MinIO")
    parser.add_argument(
        "--bronze-dir",
        type=Path,
        default=BRONZE_RAW_DIR,
        help="Diretório com arquivos JSON da camada Bronze",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uploaded, failed = upload_bronze_files(args.bronze_dir)

    if failed:
        raise SystemExit(1)

    print(f"Upload concluído: {uploaded} arquivos na camada Bronze.")


if __name__ == "__main__":
    main()
