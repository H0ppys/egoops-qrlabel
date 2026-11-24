"""场景任务码标签渲染。

版式与飞书多维表格中已有的 42 张「场景任务码」保持一致：
A4 竖版 1190x1684 px（144 dpi），白底黑字，
从上到下依次为：任务名称（自动缩放、居中）、任务ID、二维码（438px）、采集点。
二维码内容为纯数字任务ID。
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_M, ERROR_CORRECT_Q

# ---------------------------------------------------------------- 版面常量
PAGE_W, PAGE_H = 1190, 1684  # A4 @ 144 dpi
DPI = 144

TITLE_MAX_W = 990
TITLE_MAX_SIZE = 111
TITLE_MIN_SIZE = 26
TITLE_CENTER_Y = 396

ID_SIZE = 62
BASELINE_GAP = 38  # 标题基线 → 任务ID 墨迹顶边

QR_SIZE = 438
QR_TOP = 682

SITE_SIZE = 55
SITE_MAX_W = 980
SITE_CENTER_Y = 1374

FONT_CANDIDATES = [
    ("NotoSansSC-VF.ttf", "Black", "Bold"),
    ("NotoSansSC-Regular.otf", None, None),
    ("SourceHanSansSC-Heavy.otf", None, None),
]


def _font_dirs() -> list[Path]:
    dirs = []
    base = Path(__file__).resolve().parent
    # 拆分新增：仓库把字体统一放在 assets/fonts/（原布局是 app/fonts/），
    # 这里补一个候选目录，优先级紧随 app/fonts，不改动任何排版参数。
    dirs += [base / "fonts", base.parent / "assets" / "fonts",
             base.parent / "fonts", base.parent.parent / "fonts"]
    dirs.append(Path(r"C:\Windows\Fonts"))
    return dirs


class FontBook:
    """按字重缓存字体对象；优先使用随程序打包的 Noto Sans SC。"""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}
        self._path: Path | None = None
        self._variable = False
        for d in _font_dirs():
            for name, _, _ in FONT_CANDIDATES:
                p = d / name
                if p.exists():
                    self._path = p
                    self._variable = "VF" in name or "Vari" in name
                    break
            if self._path:
                break
        if self._path is None:
            for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
                p = Path(r"C:\Windows\Fonts") / name
                if p.exists():
                    self._path = p
                    break
        if self._path is None:
            raise RuntimeError("找不到可用的中文字体")

    @property
    def path(self) -> Path:
        return self._path  # type: ignore[return-value]

    def get(self, size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
        key = (weight, size)
        if key in self._cache:
            return self._cache[key]
        font = ImageFont.truetype(str(self._path), size)
        if self._variable:
            for candidate in self._weight_aliases(weight):
                try:
                    font.set_variation_by_name(candidate)
                    break
                except Exception:
                    continue
        self._cache[key] = font
        return font

    @staticmethod
    def _weight_aliases(weight: str) -> list[str]:
        return {
            "Black": ["Black", "ExtraBold", "Bold"],
            "Bold": ["Bold", "SemiBold", "Medium"],
            "Medium": ["Medium", "Regular"],
            "Regular": ["Regular", "Book"],
            "SemiBold": ["SemiBold", "Bold", "Medium"],
        }.get(weight, ["Regular"])


BOOK = FontBook()


def _ink_bbox(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    img = Image.new("L", (10, 10), 255)
    box = ImageDraw.Draw(img).textbbox((0, 0), text, font=font)
    return box  # (x0, y0, x1, y1) 相对绘制原点


def measure(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    x0, y0, x1, y1 = _ink_bbox(text, font)
    return x1 - x0, y1 - y0


def draw_ink_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    cx: float,
    cy: float,
) -> tuple[int, int, int, int]:
    """以「墨迹（实际笔画）中心」对齐到 (cx, cy) 绘制文字，返回墨迹外框。"""
    x0, y0, x1, y1 = _ink_bbox(text, font)
    dx = cx - (x0 + x1) / 2
    dy = cy - (y0 + y1) / 2
    draw.text((dx, dy), text, font=font, fill=0)
    return (int(round(dx + x0)), int(round(dy + y0)),
            int(round(dx + x1)), int(round(dy + y1)))


# ---------------------------------------------------------------- 二维码
def _qr_matrix(data: str) -> list[list[bool]]:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=1, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.get_matrix()


def _rounded_rect(draw: ImageDraw.ImageDraw, box, radius: float, fill: int) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def qr_image(data: str, size: int = 300, border: int = 4) -> Image.Image:
    """普通二维码（带静区），用于登录链接等界面展示。"""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=border)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("L")
    return img.resize((size, size), Image.LANCZOS)


def render_qr(data: str, size: int = QR_SIZE, supersample: int = 4) -> Image.Image:
    """绘制二维码：数据模块为方块，三个定位角为圆角（与现有标签风格一致）。"""
    matrix = _qr_matrix(data)
    n = len(matrix)
    unit = size * supersample // n
    side = unit * n
    img = Image.new("L", (side, side), 255)
    draw = ImageDraw.Draw(img)

    is_finder = lambda r, c: (  # noqa: E731
        (r < 7 and c < 7)
        or (r < 7 and c >= n - 7)
        or (r >= n - 7 and c < 7)
    )

    for r in range(n):
        for c in range(n):
            if matrix[r][c] and not is_finder(r, c):
                draw.rectangle(
                    [c * unit, r * unit, (c + 1) * unit - 1, (r + 1) * unit - 1],
                    fill=0,
                )

    radius_outer = unit * 1.2
    radius_inner = unit * 0.7
    for (r0, c0) in ((0, 0), (0, n - 7), (n - 7, 0)):
        x0, y0 = c0 * unit, r0 * unit
        _rounded_rect(draw, [x0, y0, x0 + 7 * unit - 1, y0 + 7 * unit - 1], radius_outer, 0)
        pad = unit
        _rounded_rect(
            draw,
            [x0 + pad, y0 + pad, x0 + 6 * unit - 1, y0 + 6 * unit - 1],
            radius_outer * 0.72,
            255,
        )
        pad2 = 2 * unit
        _rounded_rect(
            draw,
            [x0 + pad2, y0 + pad2, x0 + 5 * unit - 1, y0 + 5 * unit - 1],
            radius_inner,
            0,
        )

    return img.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------- 标签
@dataclass
class TaskLabel:
    task_id: str
    task_name: str
    site_name: str = ""

    @property
    def filename(self) -> str:
        return f"{self.task_id}.png"


def fit_title(text: str, max_width: int = TITLE_MAX_W) -> ImageFont.FreeTypeFont:
    """短标题放大、长标题缩小，使文字尽量铺满标题区域（与现有标签一致）。"""
    length = max(len(text), 1)
    size = min(TITLE_MAX_SIZE, max(TITLE_MIN_SIZE, int(max_width / length)))
    while size > TITLE_MIN_SIZE:
        font = BOOK.get(size, "Black")
        if measure(text, font)[0] <= max_width:
            return font
        size -= 2
    return BOOK.get(TITLE_MIN_SIZE, "Black")


def render_label(task: TaskLabel, watermark: str = "") -> Image.Image:
    img = Image.new("L", (PAGE_W, PAGE_H), 255)
    draw = ImageDraw.Draw(img)
    cx = PAGE_W / 2

    # 标题（任务名称）
    title = (task.task_name or "").strip()
    if title:
        font = fit_title(title)
        w, _ = measure(title, font)
        if w > TITLE_MAX_W:  # 极端长标题：按宽拆两行
            lines = _wrap(title, font, TITLE_MAX_W)
            line_h = int(font.size * 1.34)
            total = line_h * len(lines)
            top = TITLE_CENTER_Y - total / 2
            for i, line in enumerate(lines):
                draw_ink_centered(draw, line, font, cx, top + line_h * (i + 0.5))
            title_bottom = int(top + total)
            title_size = font.size
        else:
            box = draw_ink_centered(draw, title, font, cx, TITLE_CENTER_Y)
            title_bottom = box[3]
            title_size = font.size
    else:
        title_bottom = TITLE_CENTER_Y
        title_size = ID_SIZE

    # 任务ID（与标题基线固定间距，随标题字号轻微浮动，与现有标签一致）
    id_text = f"任务ID： {task.task_id}"
    id_font = BOOK.get(ID_SIZE, "Regular")
    id_h = measure(id_text, id_font)[1]
    baseline = title_bottom + 0.12 * title_size
    id_cy = baseline + BASELINE_GAP + id_h / 2
    draw_ink_centered(draw, id_text, id_font, cx, id_cy)

    # 二维码
    qr = render_qr(task.task_id, QR_SIZE)
    img.paste(qr, (int(cx - QR_SIZE / 2), QR_TOP))

    # 采集点
    site = (task.site_name or "").strip()
    if site:
        site_text = f"采集点： {site}"
        size = SITE_SIZE
        site_font = BOOK.get(size, "Regular")
        while size > 28 and measure(site_text, site_font)[0] > SITE_MAX_W:
            size -= 2
            site_font = BOOK.get(size, "Regular")
        draw_ink_centered(draw, site_text, site_font, cx, SITE_CENTER_Y)

    if watermark:
        wm_font = BOOK.get(18, "Regular")
        draw.text((30, PAGE_H - 46), watermark, font=wm_font, fill=170)

    return img.convert("RGB")


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if measure(cur + ch, font)[0] > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines or [text]


def render_pdf(labels: list[TaskLabel]) -> bytes:
    pages = [render_label(t).convert("RGB") for t in labels]
    if not pages:
        raise ValueError("没有可导出的标签")
    buf = io.BytesIO()
    pages[0].save(
        buf,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=float(DPI),
    )
    return buf.getvalue()


def render_sheet_pdf(labels: list[TaskLabel], per_page: int = 4) -> bytes:
    """A4 拼版：一页放 2×2 共 4 张小标签，省纸，适合批量张贴。"""
    if not labels:
        raise ValueError("没有可导出的标签")
    cell_w, cell_h = PAGE_W // 2, PAGE_H // 2
    margin = 6
    pages: list[Image.Image] = []
    for start in range(0, len(labels), per_page):
        chunk = labels[start:start + per_page]
        page = Image.new("RGB", (PAGE_W, PAGE_H), 255)
        draw = ImageDraw.Draw(page)
        # 裁切参考线（浅灰，不影响二维码）
        draw.line([(cell_w, 0), (cell_w, PAGE_H)], fill=225, width=1)
        draw.line([(0, cell_h), (PAGE_W, cell_h)], fill=225, width=1)
        for index, task in enumerate(chunk):
            col, row = index % 2, index // 2
            img = render_label(task).resize(
                (cell_w - margin * 2, cell_h - margin * 2), Image.LANCZOS
            )
            page.paste(img, (col * cell_w + margin, row * cell_h + margin))
        pages.append(page)

    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:],
                  resolution=float(DPI))
    return buf.getvalue()


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, dpi=(DPI, DPI))
    return buf.getvalue()


def qr_version_for(data: str) -> int:
    n = len(_qr_matrix(data))
    return int(math.floor((n - 17) / 4))
