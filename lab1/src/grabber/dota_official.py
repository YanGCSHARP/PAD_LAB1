"""Источник 1: официальный сайт dota2.com.

Страницы героев/предметов на сайте рендерятся JavaScript'ом, но данные
приходят из JSON-эндпоинтов /datafeed/*, которые и используем:
  herolist, herodata?hero_id=  — герои, способности, таланты, биография
  itemlist, itemdata?item_id=  — предметы
  abilitylist                  — словарь id → название способности (для патчей)
  patchnoteslist, patchnotes   — описания патчей
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from src.grabber.base import ItemRef, Source
from src.models import Document, Section

PRIMARY_ATTR = {0: "Сила", 1: "Ловкость", 2: "Интеллект", 3: "Универсальный"}
ATTACK = {1: "ближний бой", 2: "дальний бой"}
ROLES = ["Керри", "Саппорт", "Нюкер", "Дизейблер", "Лесник", "Танк", "Эскейпер", "Пушер", "Инициатор"]
TALENT_LEVELS = [10, 10, 15, 15, 20, 20, 25, 25]

_PLACEHOLDER = re.compile(r"%(\w*)%|\{s:(\w+)\}")

# бонусы предметов приходят как heading_loc="+$str" — переводим в читаемый текст
STAT_BONUS = {
    "str": "к силе", "agi": "к ловкости", "int": "к интеллекту", "all": "ко всем атрибутам",
    "damage": "к урону", "attack": "к скорости атаки", "armor": "к броне", "health": "к здоровью",
    "mana": "к мане", "hp_regen": "к восстановлению здоровья", "mana_regen": "к восстановлению маны",
    "move_speed": "к скорости передвижения", "spell_resist": "к сопротивлению магии",
    "cast_range": "к дальности применения", "spell_lifesteal": "к вампиризму заклинаний",
    "evasion": "к уклонению", "lifesteal": "к вампиризму", "restoration_amp": "к усилению восстановления",
    "cooldown_reduction": "к снижению перезарядки", "attack_range": "к дальности атаки",
    "attack_range_melee": "к дальности атаки (ближний бой)", "attack_range_all": "к дальности атаки",
    "aoe_bonus": "к радиусу действия способностей", "status_resist": "к сопротивлению эффектам",
    "slow_resistance": "к сопротивлению замедлению", "projectile_speed": "к скорости снарядов",
    "primary_attribute": "к основному атрибуту", "max_mana_percentage": "к максимальному запасу маны",
    "debuff_amp": "к длительности негативных эффектов", "selected_attrib": "к выбранному атрибуту",
    "manacost_reduction": "к снижению затрат маны", "healing_amp": "к усилению лечения",
    "attack_pct": "к урону от атаки", "spell_amp": "к усилению заклинаний",
}


def fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}".replace(".", ",")


def fmt_levels(values: list) -> str:
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    if len(set(vals)) == 1:
        return fmt_num(vals[0])
    return " / ".join(fmt_num(v) for v in vals)


def pick_values(sv: dict, context: str | None = None) -> list:
    """Значения параметра. В тексте улучшения от Scepter/Shard базовые значения
    обычно нулевые, а реальные лежат в values_scepter / values_shard."""
    base = sv.get("values_float") or []
    upgrade = {"scepter": sv.get("values_scepter"), "shard": sv.get("values_shard")}
    if context in upgrade and upgrade[context]:
        return upgrade[context]
    if not any(base):
        return sv.get("values_scepter") or sv.get("values_shard") or base
    return base


def fill_placeholders(text: str, special_values: list[dict], context: str | None = None) -> str:
    """'%blink_range%' / '{s:value}' → числа из special_values; '%%' → '%'."""
    values = {sv["name"]: sv for sv in special_values or []}

    def repl(m: re.Match) -> str:
        key = m.group(1) if m.group(1) is not None else m.group(2)
        if key == "":
            return "%"
        sv = values.get(key)
        if not sv:
            return key
        v = fmt_levels(pick_values(sv, context))
        return v if v else key

    return _PLACEHOLDER.sub(repl, text or "")


class DotaOfficialSource(Source):
    name = "official"

    def __init__(self, http, raw_dir, cfg: dict):
        super().__init__(http, raw_dir)
        self.base = cfg["base_url"].rstrip("/")
        self.lang = cfg.get("language", "russian")
        self.cfg = cfg
        self._abilities: dict[int, str] | None = None
        self._items: dict[int, str] | None = None
        self._heroes: dict[int, str] | None = None

    # ---------- справочники ----------
    def _feed(self, endpoint: str, **params) -> dict:
        return self.http.get_json(f"{self.base}/{endpoint}", {"language": self.lang, **params})

    def hero_names(self) -> dict[int, str]:
        if self._heroes is None:
            data = self._feed("herolist")["result"]["data"]["heroes"]
            self._heroes = {h["id"]: h["name_english_loc"] for h in data}
        return self._heroes

    def item_names(self) -> dict[int, str]:
        if self._items is None:
            data = self._feed("itemlist")["result"]["data"]["itemabilities"]
            self._items = {i["id"]: i["name_loc"] for i in data if i["name_loc"]}
            self._item_rows = data
        return self._items

    def ability_names(self) -> dict[int, str]:
        if self._abilities is None:
            data = self._feed("abilitylist")["result"]["data"]["itemabilities"]
            self._abilities = {a["id"]: a["name_loc"] for a in data if a["name_loc"]}
        return self._abilities

    # ---------- листинг ----------
    def list_items(self) -> list[ItemRef]:
        refs: list[ItemRef] = []
        if self.cfg.get("heroes", True):
            for hid, name in sorted(self.hero_names().items()):
                slug = name.lower().replace(" ", "").replace("-", "").replace("'", "")
                refs.append(ItemRef(f"official:hero:{hid}", name, f"https://www.dota2.com/hero/{slug}",
                                    meta={"kind": "hero", "id": hid}))
        if self.cfg.get("items", True):
            self.item_names()
            for row in self._item_rows:
                if not row["name_loc"] or row["name"].startswith("item_recipe"):
                    continue
                refs.append(ItemRef(f"official:item:{row['id']}", row["name_loc"],
                                    "https://www.dota2.com/items", meta={"kind": "item", "id": row["id"]}))
        n = self.cfg.get("patches_last", 0)
        if n:
            patches = self.http.get_json(f"{self.base}/patchnoteslist", {"language": self.lang})["patches"]
            for p in patches[-n:]:
                num = p["patch_number"]
                # патчноуты после публикации почти не меняются → номер патча служит версией
                refs.append(ItemRef(f"official:patch:{num}", f"Патч {num}",
                                    f"https://www.dota2.com/patches/{num}", version_hint=num,
                                    meta={"kind": "patch", "id": num, "ts": p["patch_timestamp"]}))
        return refs

    def download(self, ref: ItemRef) -> dict:
        kind = ref.meta["kind"]
        if kind == "hero":
            return self._feed("herodata", hero_id=ref.meta["id"])
        if kind == "item":
            return self._feed("itemdata", item_id=ref.meta["id"])
        return self.http.get_json(f"{self.base}/patchnotes", {"version": ref.meta["id"], "language": self.lang})

    def parse(self, ref: ItemRef, raw: dict) -> Document:
        kind = ref.meta["kind"]
        if kind == "hero":
            return self._parse_hero(ref, raw)
        if kind == "item":
            return self._parse_item(ref, raw)
        return self._parse_patch(ref, raw)

    # ---------- герои ----------
    def _parse_hero(self, ref: ItemRef, raw: dict) -> Document:
        h = raw["result"]["data"]["heroes"][0]
        name = h["name_loc"]
        sections: list[Section] = []

        roles = [f"{ROLES[i]} ({lvl})" for i, lvl in enumerate(h.get("role_levels") or []) if lvl and i < len(ROLES)]
        overview = [
            h.get("npe_desc_loc", ""),
            h.get("hype_loc", ""),
            f"Основной атрибут: {PRIMARY_ATTR.get(h['primary_attr'], '?')}. "
            f"Тип атаки: {ATTACK.get(h['attack_capability'], '?')}. Сложность: {h['complexity']} из 3.",
            f"Роли: {', '.join(roles)}." if roles else "",
        ]
        sections.append(Section("Обзор", "\n".join(x for x in overview if x)))

        stats = (
            f"Сила: {fmt_num(h['str_base'])} (+{fmt_num(h['str_gain'])} за уровень). "
            f"Ловкость: {fmt_num(h['agi_base'])} (+{fmt_num(h['agi_gain'])} за уровень). "
            f"Интеллект: {fmt_num(h['int_base'])} (+{fmt_num(h['int_gain'])} за уровень).\n"
            f"Урон: {h['damage_min']}–{h['damage_max']}. Интервал атаки: {fmt_num(h['attack_rate'])}. "
            f"Дальность атаки: {h['attack_range']}. Скорость снаряда: {h['projectile_speed']}.\n"
            f"Броня: {fmt_num(h['armor'])}. Сопротивление магии: {h['magic_resistance']}%. "
            f"Скорость передвижения: {h['movement_speed']}. Скорость поворота: {fmt_num(h['turn_rate'])}.\n"
            f"Обзор днём/ночью: {h['sight_range_day']}/{h['sight_range_night']}.\n"
            f"Здоровье: {h['max_health']} (реген {fmt_num(h['health_regen'])}). "
            f"Мана: {h['max_mana']} (реген {fmt_num(h['mana_regen'])})."
        )
        sections.append(Section("Характеристики", stats))

        for a in h.get("abilities", []):
            sections.append(Section(f"Способность: {a['name_loc']}", self._ability_text(a)))

        talents = h.get("talents") or []
        if talents:
            # значения талантов хранятся в bonuses параметров способностей:
            # талант X меняет параметр P способности на value → в тексте "{s:bonus_P}"
            bonus: dict[str, list[dict]] = {}
            for a in [x for x in h.get("abilities", []) + (h.get("facet_abilities") or []) if isinstance(x, dict)]:
                for sv in a.get("special_values") or []:
                    for b in sv.get("bonuses") or []:
                        bonus.setdefault(b["name"], []).append(
                            {"name": f"bonus_{sv['name']}", "values_float": [b["value"]]})
            lines = []
            for i, t in enumerate(talents):
                lvl = TALENT_LEVELS[i] if i < len(TALENT_LEVELS) else "?"
                sv = (t.get("special_values") or []) + bonus.get(t["name"], [])
                lines.append(f"Уровень {lvl}: {fill_placeholders(t['name_loc'], sv)}")
            sections.append(Section("Таланты", "\n".join(lines)))

        for f in h.get("facets") or []:
            title = f.get("title_loc") or f.get("name", "")
            sections.append(Section(f"Аспект: {title}", fill_placeholders(f.get("description_loc", ""), [])))

        if h.get("bio_loc"):
            sections.append(Section("Биография", h["bio_loc"]))

        return Document(ref.doc_id, self.name, "ru", name, ref.url, "hero", sections,
                        updated_at=_today(), extra={"hero_id": h["id"], "internal_name": h["name"]})

    def _ability_text(self, a: dict) -> str:
        sv = a.get("special_values") or []
        parts = []
        if a.get("ability_is_innate"):
            parts.append("Врождённая способность.")
        if a.get("ability_is_granted_by_scepter"):
            parts.append("Способность от Aghanim's Scepter.")
        if a.get("ability_is_granted_by_shard"):
            parts.append("Способность от Aghanim's Shard.")
        parts.append(fill_placeholders(a.get("desc_loc", ""), sv))
        # значения с подписью (как в тултипе на сайте)
        for v in sv:
            vals = v.get("values_float") or []
            head = (v.get("heading_loc") or "").rstrip(":").strip()
            if not head or not any(vals):
                continue
            val = fmt_levels(vals) + ("%" if v.get("is_percentage") else "")
            m = re.fullmatch(r"([+-]?)\$(\w+)", head)
            if m:                                           # бонус предмета: "+10 к силе"
                sign = m.group(1) or "+"
                parts.append(f"Бонус: {sign}{val} {STAT_BONUS.get(m.group(2), m.group(2).replace('_', ' '))}")
            else:
                parts.append(f"{head.capitalize()}: {val}")
        cd, mana = fmt_levels(a.get("cooldowns") or []), fmt_levels(a.get("mana_costs") or [])
        if cd and cd != "0":
            parts.append(f"Перезарядка: {cd} сек.")
        if mana and mana != "0":
            parts.append(f"Затраты маны: {mana}.")
        for note in a.get("notes_loc") or []:
            parts.append(f"Примечание: {fill_placeholders(note, sv)}")
        if a.get("scepter_loc"):
            parts.append(f"Улучшение от Aghanim's Scepter: {fill_placeholders(a['scepter_loc'], sv, 'scepter')}")
        if a.get("shard_loc"):
            parts.append(f"Улучшение от Aghanim's Shard: {fill_placeholders(a['shard_loc'], sv, 'shard')}")
        if a.get("lore_loc"):
            parts.append(f"Лор: {a['lore_loc']}")
        return "\n".join(p for p in parts if p)

    # ---------- предметы ----------
    def _parse_item(self, ref: ItemRef, raw: dict) -> Document:
        it = raw["result"]["data"]["items"][0]
        info = []
        if it.get("item_cost"):
            info.append(f"Стоимость: {it['item_cost']} золота.")
        tier = it.get("item_neutral_tier", -1)
        if 0 <= tier < 10:                    # -1 приходит как 4294967295 (беззнаковое)
            info.append(f"Нейтральный предмет, уровень {tier + 1}.")
        sections = [Section("Описание", "\n".join(info + [self._ability_text(it)]))]
        return Document(ref.doc_id, self.name, "ru", it["name_loc"], ref.url, "item", sections,
                        updated_at=_today(), extra={"item_id": it["id"], "internal_name": it["name"]})

    # ---------- патчи ----------
    def _parse_patch(self, ref: ItemRef, raw: dict) -> Document:
        heroes, items, abilities = self.hero_names(), self.item_names(), self.ability_names()
        sections: list[Section] = []

        def notes(lst) -> list[str]:
            out = []
            for n in lst or []:
                text = n.get("note", "")
                if text and text != "<br>":
                    out.append(("  " * (n.get("indent_level", 1) - 1)) + "- " + text
                               + (f" ({n['info']})" if n.get("info") else ""))
            return out

        for g in raw.get("general_notes") or []:
            sections.append(Section(f"Общие изменения: {g.get('title', '')}", "\n".join(notes(g.get("generic")))))

        for key, label in (("items", "Предметы"), ("neutral_items", "Нейтральные предметы")):
            lines = []
            for it in raw.get(key) or []:
                name = items.get(it.get("ability_id"), it.get("title", ""))
                body = notes(it.get("ability_notes"))
                if body:
                    lines.append(f"{name}:\n" + "\n".join(body))
            if lines:
                sections.append(Section(label, "\n".join(lines)))

        for hero in raw.get("heroes") or []:
            lines = notes(hero.get("hero_notes"))
            for ab in hero.get("abilities") or []:
                body = notes(ab.get("ability_notes"))
                if body:
                    lines.append(f"{abilities.get(ab.get('ability_id'), 'Способность')}:\n" + "\n".join(body))
            tal = notes(hero.get("talent_notes"))
            if tal:
                lines.append("Таланты:\n" + "\n".join(tal))
            for fct in hero.get("facets") or []:
                body = notes(fct.get("facet_notes") or fct.get("notes"))
                if body:
                    lines.append(f"Аспект {fct.get('title_loc', '')}:\n" + "\n".join(body))
            if lines:
                sections.append(Section(f"Изменения героя {heroes.get(hero['hero_id'], hero['hero_id'])}",
                                        "\n".join(lines)))

        ts = datetime.fromtimestamp(ref.meta["ts"], tz=timezone.utc).date().isoformat()
        return Document(ref.doc_id, self.name, "ru", ref.title, ref.url, "patch", sections,
                        updated_at=ts, version=ref.meta["id"])


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()
