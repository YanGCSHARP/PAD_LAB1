from collections import Counter

from src.grabber.base import ItemRef, Source, run_source
from src.grabber.dota_official import fill_placeholders, fmt_levels
from src.grabber.fandom import html_to_sections
from src.grabber.manifest import Manifest
from src.models import Document, Section


# ---------- парсинг официального источника ----------
def test_placeholders_basic():
    sv = [{"name": "blink_range", "values_float": [1200]}]
    assert fill_placeholders("до %blink_range%.", sv) == "до 1200."


def test_placeholders_percent_and_talent_format():
    sv = [{"name": "value", "values_float": [15]}]
    assert fill_placeholders("%value%%% урона", sv) == "15% урона"
    assert fill_placeholders("+{s:value} к броне", sv) == "+15 к броне"


def test_placeholders_scepter_values():
    sv = [{"name": "dur", "values_float": [0], "values_scepter": [5]}]
    assert fill_placeholders("%dur% сек.", sv, "scepter") == "5 сек."
    assert fill_placeholders("%dur% сек.", sv) == "5 сек."          # базовое значение нулевое


def test_fmt_levels():
    assert fmt_levels([10.5, 9, 7.5, 6]) == "10,5 / 9 / 7,5 / 6"
    assert fmt_levels([60, 60, 60]) == "60"


# ---------- парсинг Fandom ----------
HTML = """
<div class="mw-parser-output">
  <p>Intro text about the hero that is long enough.</p>
  <h2><span class="mw-headline">Abilities</span></h2>
  <p>Ability overview text, long enough to keep.<strong class="error">Lua error in Module:X</strong></p>
  <h3><span class="mw-headline">Mana Break</span></h3>
  <table><tr><th>Level</th><th>Burn</th></tr><tr><td>1</td><td>25</td></tr><tr><td>2</td><td>30</td></tr></table>
  <h2><span class="mw-headline">Gallery</span></h2>
  <p>Should be skipped completely, it is gallery text.</p>
</div>"""


def test_fandom_sections_and_noise():
    secs = html_to_sections(HTML, skip_sections={"Gallery"})
    titles = [s.title for s in secs]
    assert titles == ["Введение", "Abilities", "Abilities / Mana Break"]
    assert "Lua error" not in secs[1].text
    assert "Level | Burn" in secs[2].text and "1 | 25" in secs[2].text


# ---------- инкрементальность и дубликаты ----------
class FakeHttp:
    requests_made = 0


class FakeSource(Source):
    name = "fake"

    def __init__(self, tmp_path, pages: dict, versions: dict):
        super().__init__(FakeHttp(), tmp_path / "raw")
        self.pages, self.versions, self.fetched = pages, versions, Counter()

    def list_items(self):
        return [ItemRef(k, "Same title", "u", self.versions.get(k)) for k in self.pages]

    def download(self, ref):
        return {}

    def parse(self, ref, raw):
        return self.fetch(ref)

    def fetch(self, ref, reparse=False):
        self.fetched[ref.doc_id] += 1
        if self.pages[ref.doc_id] is None:
            raise RuntimeError("network down")
        return Document(ref.doc_id, "fake", "en", ref.title, "u", "mechanic",
                        [Section("s", self.pages[ref.doc_id])], "2026-01-01", ref.version_hint or "")


def test_incremental_run(tmp_path):
    m = Manifest(tmp_path / "m.db")
    docs = tmp_path / "docs"
    src = FakeSource(tmp_path, {"a": "text A", "b": "text B", "c": "text A", "d": None}, {"a": "1", "b": "1"})
    s1 = run_source(src, m, docs)
    assert s1["new"] == 2 and s1["duplicate"] == 1 and s1["failed"] == 1   # c — копия a

    s2 = run_source(src, m, docs)
    assert s2["skipped"] == 2                  # a, b: версия не менялась → не скачиваем
    assert src.fetched["a"] == 1

    src.pages["b"], src.versions["b"] = "text B v2", "2"
    del src.pages["a"]
    s3 = run_source(src, m, docs)
    assert s3["updated"] == 1 and s3["removed"] == 1
    assert not (docs / "a.json").exists()
