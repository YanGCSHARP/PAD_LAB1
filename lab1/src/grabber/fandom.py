"""Источник 2: Dota 2 Fandom Wiki (MediaWiki API).

Листинг:  названия героев (из официального herolist) + категории механик.
Версия:   lastrevid страницы — берётся пачками по 50 через prop=info,
          поэтому неизменённые страницы вообще не скачиваются.
Контент:  action=parse → HTML → парсинг по заголовкам h2/h3 в секции.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from src.grabber.base import ItemRef, Source
from src.models import Document, Section

# элементы, которые не несут знаний: ошибки Lua-модулей вики, навигация,
# медиа, звуки, вкладки страницы, формулы в TeX, сноски, инфобоксы
NOISE_SELECTORS = [
    "strong.error", ".scribunto-error", "script", "style", "noscript",
    ".navbox", "table.notanavbox", ".toc", ".mw-editsection", "sup.reference",
    "audio", ".ext-audiobutton", ".gallery", "figure", ".thumb", ".cosmetic-label",
    ".page-tabber-tab", ".page-tabber-separator", ".page-tabber", ".noprint",
    ".mwe-math-element", "table.infobox", ".metadata", "img", ".relics",
]
BLOCK_TAGS = {"p", "div", "li", "dd", "dt", "tr", "br", "ul", "ol", "dl", "table", "blockquote", "h4", "h5", "h6"}
HEADINGS = {"h2": 2, "h3": 3}


def html_to_sections(html: str, skip_sections: set[str]) -> list[Section]:
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one(".mw-parser-output") or soup.body or soup
    # способности героя свёрстаны блоками div.ability-background без заголовков;
    # имя способности есть только в alt иконки — запоминаем до удаления картинок
    for box in root.select("div.ability-background"):
        img = box.select_one(".ability-head img[alt]")
        if img:
            box["data-ability"] = re.sub(r"\s+icon$", "", img["alt"]).strip()
    for sel in NOISE_SELECTORS:
        for el in root.select(sel):
            el.decompose()
    # ссылки на несуществующие файлы превращаются в текст "File:..."
    for a in root.find_all("a", href=True):
        if a.get_text(strip=True).startswith("File:"):
            a.decompose()

    sections: list[Section] = []
    current = Section("Введение", "", 1)
    buf: list[str] = []
    skipping = False
    skip_level = 0
    ability: Section | None = None          # последняя встреченная способность героя

    def flush():
        text = "\n".join(buf).strip()
        if text and not skipping:
            sections.append(Section(current.title, text, current.level))

    for el in root.children:
        if not isinstance(el, Tag):
            if isinstance(el, NavigableString) and el.strip():
                buf.append(el.strip())
            continue
        if el.name == "div" and "mw-heading" in (el.get("class") or []):   # новый формат MediaWiki
            el = el.find(list(HEADINGS)) or el
        if el.name in HEADINGS:
            level = HEADINGS[el.name]
            title = el.get_text(" ", strip=True)
            flush()
            buf = []
            ability = None
            if skipping and level > skip_level:     # подсекция пропускаемой секции
                continue
            skipping = title in skip_sections
            skip_level = level
            # h3 получает контекст родительской h2: "Abilities / Mana Break"
            if level == 3 and sections_parent(sections, current):
                title = f"{sections_parent(sections, current)} / {title}"
            current = Section(title, "", level)
            continue
        if skipping:
            continue
        if el.has_attr("data-ability") or el.select_one("div[data-ability]"):
            # каждая способность → подсекция "Abilities / Mana Break"; идущие за блоком
            # заметки (отдельные div'ы) прикрепляем к этой же способности
            parent = current.title.split(" / ")[0]
            for child in ([el] if el.has_attr("data-ability") else list(el.children)):
                if not isinstance(child, Tag):
                    continue
                inner = [child] if child.has_attr("data-ability") else child.select("div[data-ability]")
                if inner:
                    for box in inner:
                        ability = Section(f"{parent} / {box['data-ability']}", block_text(box), 3)
                        sections.append(ability)
                elif ability is not None:
                    ability.text += "\n" + block_text(child)
                else:
                    buf.append(block_text(child))
            continue
        if ability is not None:
            ability.text += "\n" + block_text(el)
            continue
        buf.append(block_text(el))
    flush()
    return [s for s in sections if len(s.text) > 20]


def sections_parent(sections: list[Section], current: Section) -> str:
    if current.level == 2:
        return current.title
    if current.level == 3 and " / " in current.title:
        return current.title.split(" / ")[0]
    return ""


def block_text(el: Tag) -> str:
    """Текст с сохранением блочной структуры: строки таблиц → 'a | b | c'."""
    for table in el.find_all("table") if el.name != "table" else [el]:
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            cells = [c for c in cells if c]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with(NavigableString("\n" + "\n".join(rows) + "\n"))
        if el.name == "table":
            return "\n".join(rows)
    for br in el.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for tag in el.find_all(BLOCK_TAGS):
        tag.insert_before(NavigableString("\n"))
        tag.insert_after(NavigableString("\n"))
    text = el.get_text("")
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


class FandomSource(Source):
    name = "fandom"

    def __init__(self, http, raw_dir, cfg: dict, official_base: str):
        super().__init__(http, raw_dir)
        self.api = cfg["api_url"]
        self.page_url = cfg["page_url"]
        self.cfg = cfg
        self.official_base = official_base
        self.skip_sections = set(cfg.get("skip_sections", []))

    def _api(self, **params) -> dict:
        return self.http.get_json(self.api, {"format": "json", "formatversion": 2, **params})

    def _hero_titles(self) -> list[str]:
        data = self.http.get_json(f"{self.official_base}/herolist", {"language": "english"})
        return [h["name_english_loc"] for h in data["result"]["data"]["heroes"]]

    def _category_titles(self, category: str) -> list[str]:
        titles, cont = [], {}
        while True:
            d = self._api(action="query", list="categorymembers", cmtitle=f"Category:{category}",
                          cmnamespace=0, cmlimit=500, **cont)
            titles += [m["title"] for m in d["query"]["categorymembers"]]
            if "continue" not in d:
                return titles
            cont = d["continue"]

    def list_items(self) -> list[ItemRef]:
        wanted: dict[str, str] = {}                       # title → entity_type
        if self.cfg.get("heroes_from_official", True):
            for t in self._hero_titles():
                wanted[t] = "hero"
        for cat in self.cfg.get("categories", []):
            for t in self._category_titles(cat):
                if self.cfg.get("skip_subpages", True) and "/" in t:
                    continue
                wanted.setdefault(t, "mechanic")

        refs, titles = [], list(wanted)
        for i in range(0, len(titles), 50):               # prop=info принимает до 50 названий
            batch = titles[i:i + 50]
            d = self._api(action="query", prop="info", titles="|".join(batch), redirects=1)
            redirects = {r["to"]: r["from"] for r in d["query"].get("redirects", [])}
            normalized = {n["to"]: n["from"] for n in d["query"].get("normalized", [])}
            for p in d["query"]["pages"]:
                if p.get("missing") or "pageid" not in p:
                    continue
                orig = redirects.get(p["title"], p["title"])
                orig = normalized.get(orig, orig)
                refs.append(ItemRef(
                    doc_id=f"fandom:{p['pageid']}", title=p["title"],
                    url=self.page_url + p["title"].replace(" ", "_"),
                    version_hint=str(p["lastrevid"]),
                    meta={"pageid": p["pageid"], "entity_type": wanted.get(orig, "mechanic"),
                          "touched": p.get("touched", "")},
                ))
        return refs

    def download(self, ref: ItemRef) -> dict:
        d = self._api(action="parse", pageid=ref.meta["pageid"], prop="text|revid",
                      disableeditsection=1, disabletoc=1, disablelimitreport=1)["parse"]
        return {"title": d["title"], "revid": d["revid"], "html": d["text"]}

    def parse(self, ref: ItemRef, parse: dict) -> Document:
        sections = html_to_sections(parse["html"], self.skip_sections)
        if not sections:
            raise ValueError("пустая страница после очистки")
        return Document(
            doc_id=ref.doc_id, source=self.name, lang="en", title=parse["title"], url=ref.url,
            entity_type=ref.meta["entity_type"], sections=sections,
            updated_at=(ref.meta.get("touched") or "")[:10], version=str(parse["revid"]),
        )
