"""Мини-библиотека SVG-графиков без зависимостей (matplotlib на этой машине
блокируется Smart App Control). Сгруппированные столбцы и линии, одна ось Y.

Палитра — первые слоты проверенной категориальной палитры, серии в
фиксированном порядке; приглушённая сетка; подписи — цветом текста.
"""
from __future__ import annotations

from html import escape

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8983", "#e6e5e0", "#fcfcfb"
FONT = "Segoe UI, Inter, Arial, sans-serif"


def _nice_max(v: float) -> float:
    for m in (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if v <= m:
            return m
    return v


def _ticks(ymax: float, n: int = 5) -> list[float]:
    return [ymax * i / n for i in range(n + 1)]


def _fmt(v: float, fmt: str) -> str:
    return fmt.format(v).replace(".", ",")


class Chart:
    def __init__(self, title: str, width: int = 640, height: int = 340, subtitle: str = ""):
        self.title, self.subtitle, self.w, self.h = title, subtitle, width, height
        self.parts: list[str] = []
        self.left, self.right, self.top, self.bottom = 52, 16, 58 if subtitle else 44, 64

    # --- каркас ---------------------------------------------------------
    def _frame(self, ymax: float, yfmt: str, ylabel: str = "") -> None:
        pw, ph = self.w - self.left - self.right, self.h - self.top - self.bottom
        self.pw, self.ph, self.ymax = pw, ph, ymax
        for t in _ticks(ymax):
            y = self.y(t)
            self.parts.append(f'<line x1="{self.left}" x2="{self.left + pw}" y1="{y:.1f}" y2="{y:.1f}" '
                              f'stroke="{GRID}" stroke-width="1"/>')
            self.parts.append(f'<text x="{self.left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
                              f'fill="{MUTED}">{_fmt(t, yfmt)}</text>')
        if ylabel:
            self.parts.append(f'<text x="14" y="{self.top + ph / 2}" font-size="11" fill="{INK2}" '
                              f'transform="rotate(-90 14 {self.top + ph / 2})" text-anchor="middle">{escape(ylabel)}</text>')

    def y(self, v: float) -> float:
        return self.top + self.ph * (1 - min(v, self.ymax) / self.ymax)

    def _legend(self, names: list[str]) -> None:
        if len(names) < 2:
            return
        x, y = self.left, self.h - 14
        for i, n in enumerate(names):
            self.parts.append(f'<rect x="{x}" y="{y - 9}" width="10" height="10" rx="2" fill="{SERIES[i]}"/>')
            self.parts.append(f'<text x="{x + 15}" y="{y}" font-size="11.5" fill="{INK2}">{escape(n)}</text>')
            x += 15 + 7.2 * len(n) + 22

    # --- столбцы ----------------------------------------------------------
    def bars(self, groups: list[str], series: dict[str, list[float]], ymax: float | None = None,
             yfmt: str = "{:.1f}", vfmt: str = "{:.2f}", ylabel: str = "") -> "Chart":
        vals = [v for vs in series.values() for v in vs if v == v]
        self._frame(ymax or _nice_max(max(vals) * 1.1), yfmt, ylabel)
        n, gw = len(series), self.pw / len(groups)
        bw = min(34.0, gw * 0.8 / n)
        for gi, g in enumerate(groups):
            gx = self.left + gw * gi + (gw - bw * n - 2 * (n - 1)) / 2
            for si, (name, vs) in enumerate(series.items()):
                v = vs[gi]
                if v != v:                                  # NaN — нет данных
                    continue
                x, y0 = gx + si * (bw + 2), self.y(0)
                y = self.y(v)
                h = max(y0 - y, 0.5)
                r = min(4, h / 2, bw / 2)
                # скругление только у конца данных, основание — прямое
                self.parts.append(
                    f'<path d="M{x:.1f},{y0:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} '
                    f'H{x + bw - r:.1f} Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} V{y0:.1f} Z" '
                    f'fill="{SERIES[si]}"><title>{escape(name)} · {escape(g)}: {_fmt(v, vfmt)}</title></path>')
                self.parts.append(f'<text x="{x + bw / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle" '
                                  f'font-size="{9.5 if n > 2 else 10.5}" fill="{INK2}">{_fmt(v, vfmt)}</text>')
            self._xlabel(self.left + gw * gi + gw / 2, g)
        self._legend(list(series))
        return self

    # --- линии ------------------------------------------------------------
    def lines(self, xs: list, series: dict[str, list[float]], ymax: float | None = None, yfmt: str = "{:.1f}",
              xfmt: str = "{}", xlabel: str = "", ylabel: str = "", end_labels: bool = True) -> "Chart":
        vals = [v for vs in series.values() for v in vs if v == v]
        self._frame(ymax or _nice_max(max(vals) * 1.1), yfmt, ylabel)
        n = len(xs)
        px = [self.left + (self.pw * i / (n - 1) if n > 1 else self.pw / 2) for i in range(n)]
        for si, (name, vs) in enumerate(series.items()):
            pts = [(px[i], self.y(v)) for i, v in enumerate(vs) if v == v]
            d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
            self.parts.append(f'<path d="{d}" fill="none" stroke="{SERIES[si]}" stroke-width="2" '
                              f'stroke-linejoin="round" stroke-linecap="round"/>')
            for (x, y), v, xv in zip(pts, [v for v in vs if v == v], xs):
                self.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{SERIES[si]}" stroke="{SURFACE}" '
                                  f'stroke-width="2"><title>{escape(name)} · {xv}: {_fmt(v, "{:.3f}")}</title></circle>')
            if end_labels and pts:
                x, y = pts[-1]
                self.parts.append(f'<text x="{x - 6:.1f}" y="{y - 9:.1f}" text-anchor="end" font-size="11" '
                                  f'fill="{INK2}">{escape(name)}</text>')
        for x, xv in zip(px, xs):
            self._xlabel(x, xfmt.format(xv))
        if xlabel:
            self.parts.append(f'<text x="{self.left + self.pw / 2}" y="{self.h - 30}" text-anchor="middle" '
                              f'font-size="11" fill="{INK2}">{escape(xlabel)}</text>')
        self._legend(list(series))
        return self

    def _xlabel(self, x: float, text: str) -> None:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            self.parts.append(f'<text x="{x:.1f}" y="{self.top + self.ph + 16 + i * 13}" text-anchor="middle" '
                              f'font-size="11" fill="{INK2}">{escape(ln)}</text>')

    # --- вывод ------------------------------------------------------------
    def svg(self) -> str:
        head = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" font-family="{FONT}">',
                f'<rect width="100%" height="100%" fill="{SURFACE}"/>',
                f'<text x="{self.left - 36}" y="24" font-size="15" font-weight="600" fill="{INK}">{escape(self.title)}</text>']
        if self.subtitle:
            head.append(f'<text x="{self.left - 36}" y="42" font-size="11.5" fill="{INK2}">{escape(self.subtitle)}</text>')
        return "\n".join(head + self.parts + ["</svg>"])

    def save(self, path) -> None:
        path.write_text(self.svg(), encoding="utf-8")
        print("saved", path.name)
