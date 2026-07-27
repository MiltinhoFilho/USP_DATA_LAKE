"""Web scraper for Jornal da USP — extracts raw news data for Bronze layer."""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://jornal.usp.br"
ALL_NEWS_LISTING_PATH = "/todas-as-noticias/"
LISTING_URL = f"{BASE_URL}{ALL_NEWS_LISTING_PATH}"
USER_AGENT = "Mozilla/5.0 (compatible; USP-DataLake/1.0; academic research)"
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 1

CATEGORY_MAP = {
    "ciencias": "Ciências",
    "universidade": "Universidade",
    "cultura": "Cultura",
    "diversidade": "Diversidade",
    "institucional": "Institucional",
    "atualidades": "Atualidades",
    "podcasts": "Podcasts",
    "artigos": "Artigos",
    "colunistas": "Colunistas",
}


def fetch_html(url: str, *, allow_404: bool = False) -> str | None:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    if allow_404 and response.status_code == 404:
        return None
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def normalize_url(href: str) -> str:
    return urljoin(BASE_URL, href.split("#")[0].split("?")[0])


def is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and "jornal.usp.br" not in parsed.netloc:
        return False

    path = parsed.path.strip("/")
    if not path:
        return False

    skip_segments = {
        "editorias",
        "tag",
        "category",
        "author",
        "page",
        "wp-content",
        "feed",
        "home-atualidades",
        "todas-as-noticias",
        "noticias",
    }
    segments = path.split("/")
    if any(segment in skip_segments for segment in segments):
        return False

    return len(segments) >= 2


def collect_article_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()

    main = soup.find("main") or soup
    articles = main.select("article.post")

    for article in articles:
        anchor = article.find("a", href=True)
        if not anchor:
            continue

        url = normalize_url(anchor["href"])
        if not is_article_url(url) or url in seen:
            continue

        seen.add(url)
        links.append(url)

    if links:
        return links

    for heading in soup.find_all("h3"):
        anchor = heading.find("a", href=True)
        if not anchor:
            continue

        url = normalize_url(anchor["href"])
        if not is_article_url(url) or url in seen:
            continue

        seen.add(url)
        links.append(url)

    return links


def listing_page_url(page: int) -> str:
    """URL da listagem paginada (WordPress: página 1 sem /page/1/)."""
    if page < 1:
        raise ValueError("page deve ser >= 1")
    if page == 1:
        return LISTING_URL
    return f"{BASE_URL}{ALL_NEWS_LISTING_PATH}page/{page}/"


def collect_article_links_paginated(
    limit: int | None = None,
    max_pages: int | None = None,
) -> list[str]:
    """Percorre /todas-as-noticias/ até o limite ou até acabar as páginas."""
    collected: list[str] = []
    seen: set[str] = set()
    page = 1

    while limit is None or len(collected) < limit:
        if max_pages is not None and page > max_pages:
            break

        url = listing_page_url(page)
        print(f"  Listagem página {page}: {url}", flush=True)
        html = fetch_html(url, allow_404=True)
        if html is None:
            print(
                f"  Página {page} inexistente (404); encerrando paginação.",
                flush=True,
            )
            break

        page_links = collect_article_links(html)

        if not page_links:
            print(
                f"  Nenhum link na página {page}; encerrando paginação.",
                flush=True,
            )
            break

        new_on_page = 0
        for link in page_links:
            if link in seen:
                continue
            seen.add(link)
            collected.append(link)
            new_on_page += 1
            if limit is not None and len(collected) >= limit:
                break

        print(
            f"  +{new_on_page} novos ({len(page_links)} na página, "
            f"{len(collected)} acumulados)",
            flush=True,
        )

        if new_on_page == 0:
            print("  Página sem links novos; encerrando paginação.", flush=True)
            break

        if limit is not None and len(collected) >= limit:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return collected


def extract_title(soup: BeautifulSoup) -> str:
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    title_tag = soup.find("title")
    return title_tag.get_text(strip=True) if title_tag else ""


def _content_root(soup: BeautifulSoup):
    return soup.select_one("main") or soup.select_one("article") or soup


def extract_date(soup: BeautifulSoup) -> str:
    for meta_name in ("article:published_time", "og:updated_time"):
        meta = soup.find("meta", property=meta_name)
        if meta and meta.get("content"):
            return meta["content"].strip()

    root = _content_root(soup)
    for selector in (
        ".elementor-post-date",
        ".entry-date",
        ".post-date",
        ".published",
        ".meta-post",
    ):
        element = root.select_one(selector)
        if element:
            text = element.get_text(strip=True)
            if text:
                return text

    time_tag = root.find("time")
    if time_tag:
        if time_tag.get("datetime"):
            return time_tag["datetime"].strip()
        text = time_tag.get_text(strip=True)
        if text:
            return text

    page_text = root.get_text(" ", strip=True)
    match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", page_text)
    return match.group(1) if match else ""


def _clean_author(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^Por\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip("*").strip()


def extract_author(soup: BeautifulSoup) -> str:
    root = _content_root(soup)

    for selector in (
        ".autor",
        ".elementor-post-author",
        ".author",
        ".post-author",
        ".entry-author",
        ".meta-author",
        "a[rel='author']",
        ".entry-meta .author",
    ):
        element = root.select_one(selector)
        if element:
            text = _clean_author(element.get_text(strip=True))
            if text:
                return text

    meta_author = soup.find("meta", attrs={"name": "author"})
    if meta_author and meta_author.get("content"):
        return _clean_author(meta_author["content"])

    for selector in (".entry-meta", ".meta-post", ".post-meta"):
        element = root.select_one(selector)
        if element:
            text = element.get_text(" ", strip=True)
            match = re.match(r"^Por\s*(.+?)\*?\s+\d{2}/\d{2}/\d{4}", text, re.IGNORECASE)
            if match:
                return _clean_author(match.group(1))

    return ""


def extract_category(soup: BeautifulSoup, url: str) -> str:
    for selector in (
        "a[rel='category tag']",
        ".category",
        ".cat-links a",
        ".breadcrumb a",
    ):
        element = soup.select_one(selector)
        if element:
            text = element.get_text(strip=True)
            if text and text.lower() not in ("home", "notícias", "noticias"):
                return text

    path_segment = urlparse(url).path.strip("/").split("/")[0]
    return CATEGORY_MAP.get(path_segment, path_segment.replace("-", " ").title())


def extract_content_html(soup: BeautifulSoup) -> str:
    root = _content_root(soup)

    for selector in (
        ".entry-content",
        ".post-content",
        "article .content",
        ".content",
    ):
        element = root.select_one(selector)
        if element and len(element.get_text(strip=True)) > 200:
            return str(element)

    elementor = soup.select_one("main .elementor")
    if elementor:
        fragments = []
        for element in elementor.select(
            ".elementor-widget-heading, "
            ".elementor-widget-text-editor, "
            "figcaption"
        ):
            container = element.select_one(":scope > .elementor-widget-container")
            fragments.append(str(container or element))
        combined = '<div class="entry-content clr">' + "".join(fragments) + "</div>"
        if len(BeautifulSoup(combined, "html.parser").get_text(strip=True)) > 200:
            return combined

    main = soup.find("main")
    if main and len(main.get_text(strip=True)) > 100:
        return str(main)

    return ""


def scrape_article(url: str) -> dict:
    html = fetch_html(url)
    if html is None:
        raise requests.HTTPError(f"404 ao acessar {url}")
    soup = BeautifulSoup(html, "lxml")

    return {
        "titulo": extract_title(soup),
        "autor": extract_author(soup),
        "data": extract_date(soup),
        "categoria": extract_category(soup, url),
        "conteudo": extract_content_html(soup),
        "url": url,
    }


def _output_dirs(project_root: Path) -> tuple[Path, Path]:
    data_dir = project_root / "data"
    bronze_dir = project_root / "bronze" / "raw"
    data_dir.mkdir(parents=True, exist_ok=True)
    bronze_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, bronze_dir


def save_article_file(article: dict, index: int, bronze_dir: Path) -> Path:
    filename = f"usp_news_{index:06d}.json"
    output_path = bronze_dir / filename
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(article, file, ensure_ascii=False, indent=2)
    return output_path


def save_outputs(articles: list[dict], project_root: Path) -> None:
    data_dir, bronze_dir = _output_dirs(project_root)
    aggregated_path = data_dir / "raw_news.json"

    with aggregated_path.open("w", encoding="utf-8") as file:
        json.dump(articles, file, ensure_ascii=False, indent=2)

    for index, article in enumerate(articles, start=1):
        save_article_file(article, index, bronze_dir)

    print(
        f"Salvos {len(articles)} artigos em {aggregated_path}",
        flush=True,
    )
    print(f"Arquivos individuais em {bronze_dir}", flush=True)


def run(
    limit: int | None,
    project_root: Path,
    max_pages: int | None = None,
) -> list[dict]:
    if limit is None:
        print(
            f"Coletando todas as notícias (listagem paginada): {LISTING_URL}",
            flush=True,
        )
    else:
        print(f"Coletando até {limit} notícias: {LISTING_URL}", flush=True)
    article_links = collect_article_links_paginated(limit, max_pages=max_pages)

    if not article_links:
        raise RuntimeError(
            "Nenhum link de notícia encontrado em /todas-as-noticias/."
        )

    print(
        f"Encontrados {len(article_links)} links. Extraindo artigos...",
        flush=True,
    )
    data_dir, bronze_dir = _output_dirs(project_root)
    if limit is None:
        old_files = list(bronze_dir.glob("usp_news_*.json"))
        for path in old_files:
            path.unlink()
        if old_files:
            print(
                f"Removidos {len(old_files)} arquivos bronze anteriores.",
                flush=True,
            )
    aggregated_path = data_dir / "raw_news.json"
    articles: list[dict] = []

    for index, url in enumerate(article_links, start=1):
        try:
            print(f"[{index}/{len(article_links)}] {url}", flush=True)
            article = scrape_article(url)
            articles.append(article)
            save_article_file(article, index, bronze_dir)
            if index % 50 == 0:
                with aggregated_path.open("w", encoding="utf-8") as file:
                    json.dump(articles, file, ensure_ascii=False, indent=2)
                print(f"  Checkpoint: {index} artigos salvos.", flush=True)
        except requests.RequestException as error:
            print(f"Erro ao extrair {url}: {error}", flush=True)
        except Exception as error:
            print(f"Erro inesperado em {url}: {error}", flush=True)

        if index < len(article_links):
            time.sleep(REQUEST_DELAY)

    save_outputs(articles, project_root)
    return articles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scraper do Jornal da USP")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Máximo de notícias (padrão: todas). Ex.: --limit 50",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Raiz do projeto usp-data-lake",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Máximo de páginas de listagem a percorrer (padrão: sem limite)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    articles = run(
        limit=args.limit,
        project_root=args.project_root,
        max_pages=args.max_pages,
    )
    print(f"Concluído: {len(articles)} notícias extraídas.")


if __name__ == "__main__":
    main()
