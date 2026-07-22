"""Valida somente URLs previamente registradas no manifesto do recorte."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "recorte_manifest.json"
REPORT_PATH = ROOT / "data" / "recorte_url_report.json"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _validate(url: str, timeout: int = 20) -> dict:
    request = Request(
        url,
        headers={"User-Agent": "USP-Data-Lake-PoC/1.0 (URL validation only)"},
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=timeout) as response:
            body = response.read(512_000).decode("utf-8", errors="replace")
            status = response.status
            headers = response.headers
    except HTTPError as error:
        body = error.read(512_000).decode("utf-8", errors="replace")
        status = error.code
        headers = error.headers
    except (URLError, TimeoutError, OSError) as error:
        return {"url": url, "status_http": None, "erro": str(error)}

    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    canonical_match = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
        body,
        re.I,
    )
    if not canonical_match:
        canonical_match = re.search(
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
            body,
            re.I,
        )
    return {
        "url": url,
        "status_http": status,
        "location": headers.get("Location"),
        "titulo_observado": re.sub(r"\s+", " ", title_match.group(1)).strip()
        if title_match
        else None,
        "url_canonica_declarada": canonical_match.group(1) if canonical_match else None,
        "erro": "",
    }


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    urls = sorted(
        {
            item["url"]
            for item in manifest["documentos"]
            if item.get("url", "").startswith(("https://jornal.usp.br/", "http://jornal.usp.br/"))
        }
    )
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_validate, url): url for url in urls}
        for future in as_completed(futures):
            results.append(future.result())
    results = [
        _validate(item["url"], timeout=60) if item["status_http"] is None else item
        for item in results
    ]
    results.sort(key=lambda item: item["url"])
    report = {
        "escopo": "Somente URLs já presentes no manifesto; sem seguir redirecionamentos ou links",
        "total": len(results),
        "sucesso_2xx": sum(200 <= (item["status_http"] or 0) < 300 for item in results),
        "redirecionamentos_3xx": sum(300 <= (item["status_http"] or 0) < 400 for item in results),
        "erros_http": sum((item["status_http"] or 0) >= 400 for item in results),
        "erros_conexao": sum(item["status_http"] is None for item in results),
        "resultados": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "resultados"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
