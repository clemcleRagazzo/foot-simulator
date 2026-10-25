"""
ui_extras.py : petits éléments visuels dessinés par le code (aucune image à fournir).

  flag_pixmap / flag_icon : drapeaux simplifiés des 29 pays du jeu (mis en cache, légers)
  face_pixmap             : visage de dessin animé unique par joueur (rigolo)
  RadarWidget             : diagramme radar ATT / MIL / GB / DEF
  fun_facts               : adresse, style de vie, hobby, plat favori (stables pour un joueur donné)
"""
from __future__ import annotations

import math
import random
import zlib

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF, QRegion
from PyQt6.QtWidgets import QWidget

from fake import Faker

# =============================================================================
# 1. DRAPEAUX (version simplifiée : bandes, croix, étoiles, croissants)
# =============================================================================
BW, BH = 60, 40            # taille de dessin de base


def _bands(p, colors, vertical, ratios=None):
    ratios = ratios or [1] * len(colors)
    total, pos = sum(ratios), 0.0
    for color, r in zip(colors, ratios):
        size = (BW if vertical else BH) * r / total
        rect = QRectF(pos, 0, size + 1, BH) if vertical else QRectF(0, pos, BW, size + 1)
        p.fillRect(rect, QColor(color))
        pos += size


def _star(p, cx, cy, radius, color, filled=True):
    pts = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = radius if i % 2 == 0 else radius * 0.4
        pts.append(QPointF(cx + r * math.cos(angle), cy + r * math.sin(angle)))
    if filled:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
    else:
        p.setPen(QPen(QColor(color), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(QPolygonF(pts))


def _circle(p, cx, cy, r, color):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(cx, cy), r, r)


def _crescent(p, cx, cy, r, color, bg):
    _circle(p, cx, cy, r, color)
    _circle(p, cx + r * 0.35, cy, r * 0.82, bg)


def _cross(p, color, x, w=7):
    p.fillRect(QRectF(0, BH / 2 - w / 2, BW, w), QColor(color))
    p.fillRect(QRectF(x - w / 2, 0, w, BH), QColor(color))


def _flag_fr(p): _bands(p, ["#0055a4", "#ffffff", "#ef4135"], True)
def _flag_es(p): _bands(p, ["#aa151b", "#f1bf00", "#aa151b"], False, [1, 2, 1])
def _flag_it(p): _bands(p, ["#009246", "#ffffff", "#ce2b37"], True)
def _flag_de(p): _bands(p, ["#000000", "#dd0000", "#ffce00"], False)
def _flag_nl(p): _bands(p, ["#ae1c28", "#ffffff", "#21468b"], False)
def _flag_be(p): _bands(p, ["#000000", "#fae042", "#ed2939"], True)
def _flag_pl(p): _bands(p, ["#ffffff", "#dc143c"], False)
def _flag_rs(p): _bands(p, ["#c6363c", "#0c4076", "#ffffff"], False)
def _flag_ci(p): _bands(p, ["#f77f00", "#ffffff", "#009e60"], True)
def _flag_ng(p): _bands(p, ["#008751", "#ffffff", "#008751"], True)
def _flag_co(p): _bands(p, ["#fcd116", "#003893", "#ce1126"], False, [2, 1, 1])


def _flag_pt(p):
    _bands(p, ["#006600", "#ff0000"], True, [2, 3])
    _circle(p, BW * 0.4, BH / 2, 7, "#ffcc00")
    _circle(p, BW * 0.4, BH / 2, 4, "#d22")


def _flag_en(p):
    p.fillRect(QRectF(0, 0, BW, BH), QColor("#ffffff"))
    _cross(p, "#cf142b", BW / 2, 8)


def _flag_hr(p):
    _bands(p, ["#ff0000", "#ffffff", "#171796"], False)
    p.fillRect(QRectF(BW / 2 - 6, BH / 2 - 7, 12, 14), QColor("#ff0000"))
    p.fillRect(QRectF(BW / 2 - 6, BH / 2 - 7, 6, 7), QColor("#ffffff"))
    p.fillRect(QRectF(BW / 2, BH / 2, 6, 7), QColor("#ffffff"))


def _flag_se(p):
    p.fillRect(QRectF(0, 0, BW, BH), QColor("#006aa7"))
    _cross(p, "#fecc00", BW * 0.35, 7)


def _flag_tr(p):
    p.fillRect(QRectF(0, 0, BW, BH), QColor("#e30a17"))
    _crescent(p, BW * 0.36, BH / 2, 11, "#ffffff", "#e30a17")
    _star(p, BW * 0.54, BH / 2, 5, "#ffffff")


def _flag_br(p):
    p.fillRect(QRectF(0, 0, BW, BH), QColor("#009c3b"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffdf00"))
    p.drawPolygon(QPolygonF([QPointF(BW / 2, 4), QPointF(BW - 5, BH / 2), QPointF(BW / 2, BH - 4), QPointF(5, BH / 2)]))
    _circle(p, BW / 2, BH / 2, 9, "#002776")


def _flag_ar(p):
    _bands(p, ["#74acdf", "#ffffff", "#74acdf"], False)
    _circle(p, BW / 2, BH / 2, 4.5, "#f6b40e")


def _flag_uy(p):
    _bands(p, ["#ffffff", "#0038a8"] * 4 + ["#ffffff"], False)
    p.fillRect(QRectF(0, 0, 24, 22), QColor("#ffffff"))
    _circle(p, 12, 11, 6, "#fcd116")


def _flag_mx(p):
    _bands(p, ["#006847", "#ffffff", "#ce1126"], True)
    _circle(p, BW / 2, BH / 2, 5, "#8c5a2b")


def _flag_us(p):
    _bands(p, ["#b22234", "#ffffff"] * 3 + ["#b22234"], False)
    p.fillRect(QRectF(0, 0, 27, 22), QColor("#3c3b6e"))
    for i in range(3):
        for j in range(4):
            _circle(p, 4 + j * 6.5, 4.5 + i * 6.5, 1.3, "#ffffff")


def _flag_ma(p):
    p.fillRect(QRectF(0, 0, BW, BH), QColor("#c1272d"))
    _star(p, BW / 2, BH / 2 + 1, 11, "#006233", filled=False)


def _flag_dz(p):
    _bands(p, ["#006233", "#ffffff"], True)
    _circle(p, BW / 2 + 1, BH / 2, 10, "#d21034")
    p.fillRect(QRectF(BW / 2 + 5, BH / 2 - 11, 8, 22), QColor("#ffffff"))
    _circle(p, BW / 2 + 5, BH / 2, 8, "#ffffff")
    _star(p, BW / 2 + 5, BH / 2, 5, "#d21034")


def _flag_sn(p):
    _bands(p, ["#00853f", "#fdef42", "#e31b23"], True)
    _star(p, BW / 2, BH / 2, 8, "#00853f")


def _flag_gh(p):
    _bands(p, ["#ce1126", "#fcd116", "#006b3f"], False)
    _star(p, BW / 2, BH / 2, 8, "#000000")


def _flag_cm(p):
    _bands(p, ["#007a5e", "#ce1126", "#fcd116"], True)
    _star(p, BW / 2, BH / 2, 8, "#fcd116")


def _flag_eg(p):
    _bands(p, ["#ce1126", "#ffffff", "#000000"], False)
    _circle(p, BW / 2, BH / 2, 4, "#c09300")


def _flag_jp(p):
    p.fillRect(QRectF(0, 0, BW, BH), QColor("#ffffff"))
    _circle(p, BW / 2, BH / 2, 11, "#bc002d")


def _flag_kr(p):
    p.fillRect(QRectF(0, 0, BW, BH), QColor("#ffffff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#cd2e3a"))
    p.drawPie(QRectF(BW / 2 - 10, BH / 2 - 10, 20, 20), 0, 180 * 16)
    p.setBrush(QColor("#0047a0"))
    p.drawPie(QRectF(BW / 2 - 10, BH / 2 - 10, 20, 20), 180 * 16, 180 * 16)
    for x, y in ((7, 6), (BW - 13, 6), (7, BH - 10), (BW - 13, BH - 10)):
        p.fillRect(QRectF(x, y, 7, 4), QColor("#000000"))


FLAG_DRAWERS = {
    "France": _flag_fr, "Espagne": _flag_es, "Portugal": _flag_pt, "Italie": _flag_it, "Allemagne": _flag_de,
    "Angleterre": _flag_en, "Pays-Bas": _flag_nl, "Belgique": _flag_be, "Pologne": _flag_pl, "Croatie": _flag_hr,
    "Serbie": _flag_rs, "Suède": _flag_se, "Turquie": _flag_tr, "Brésil": _flag_br, "Argentine": _flag_ar,
    "Uruguay": _flag_uy, "Colombie": _flag_co, "Mexique": _flag_mx, "États-Unis": _flag_us, "Maroc": _flag_ma,
    "Algérie": _flag_dz, "Sénégal": _flag_sn, "Côte d'Ivoire": _flag_ci, "Nigeria": _flag_ng, "Ghana": _flag_gh,
    "Cameroun": _flag_cm, "Égypte": _flag_eg, "Japon": _flag_jp, "Corée du Sud": _flag_kr,
}
_flag_cache: dict = {}


def flag_pixmap(country: str, width: int = 24) -> QPixmap:
    """Drapeau du pays, dessiné une fois puis mis en cache (très léger)."""
    key = (country, width)
    if key not in _flag_cache:
        base = QPixmap(BW, BH)
        base.fill(QColor("#cccccc"))
        painter = QPainter(base)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        drawer = FLAG_DRAWERS.get(country)
        if drawer:
            drawer(painter)
        else:                                             # pays inconnu : drapeau blanc avec un point d'interrogation
            painter.fillRect(QRectF(0, 0, BW, BH), QColor("#eeeeee"))
            painter.setPen(QColor("#888"))
            painter.drawText(QRectF(0, 0, BW, BH), Qt.AlignmentFlag.AlignCenter, "?")
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(0.5, 0.5, BW - 1, BH - 1))
        painter.end()
        _flag_cache[key] = base.scaled(width, int(width * BH / BW), Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
    return _flag_cache[key]


def flag_icon(country: str, width: int = 24) -> QIcon:
    return QIcon(flag_pixmap(country, width))


# =============================================================================
# 2. VISAGES RIGOLOS
# =============================================================================
SKINS = ["#ffdbb4", "#f1c27d", "#e0ac69", "#c68642", "#a8693c", "#8d5524", "#6b3e1f", "#4a2a14"]
HAIRS = ["#1b1b1b", "#3b2417", "#6a4a2a", "#a0703a", "#d9b25f", "#b5472b", "#8a8a8a", "#e8e8e8"]
BACKGROUNDS = ["#cfe8ff", "#ffe3cf", "#d9f5d3", "#f5d3ee", "#fff3b8", "#d6d3f5", "#c9f2ee", "#f8d0d0"]
_face_cache: dict = {}


def face_pixmap(player, size: int = 160) -> QPixmap:
    """Visage de dessin animé unique : même joueur = même tête. L'âge, l'agressivité et le leadership
    influencent un peu les traits (cheveux gris, sourcils fâchés, balafre...)."""
    key = (player.id, size, player.age, round(player.foul_index / 10))
    if key in _face_cache:
        return _face_cache[key]
    rng = random.Random(player.id * 7919 + 13)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    S = size / 160.0
    p.scale(S, S)

    # fond rond
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(rng.choice(BACKGROUNDS)))
    p.drawEllipse(QRectF(2, 2, 156, 156))
    p.setClipRegion(QRegion(2, 2, 156, 156, QRegion.RegionType.Ellipse))

    skin, hair = QColor(rng.choices(SKINS, [3, 3, 3, 2, 2, 1, 1, 1])[0]), QColor(rng.choice(HAIRS))
    if player.age >= 33 and rng.random() < 0.8:
        hair = QColor("#9a9a9a")
    ink = QColor("#2a1a10")
    cx, cy = 80, 84
    w = rng.uniform(46, 56)                       # largeur de la tête (un peu exagérée)
    h = rng.uniform(56, 66)
    style = rng.choice(["bald", "short", "short", "curly", "mohawk", "long", "afro", "side"])

    # cheveux de derrière
    p.setBrush(hair)
    if style == "afro":
        p.drawEllipse(QPointF(cx, cy - 18), w + 16, h * 0.8)
    if style == "long":
        p.drawRoundedRect(QRectF(cx - w - 6, cy - 30, 2 * w + 12, h + 40), 28, 28)

    # oreilles + tête
    ear = rng.uniform(9, 16)
    p.setBrush(skin)
    p.drawEllipse(QPointF(cx - w, cy + 4), ear * 0.8, ear)
    p.drawEllipse(QPointF(cx + w, cy + 4), ear * 0.8, ear)
    p.drawEllipse(QPointF(cx, cy), w, h)

    # cheveux de devant
    p.setBrush(hair)
    if style in ("short", "side"):
        path_rect = QRectF(cx - w * 0.98, cy - h, w * 1.96, h * 0.7)
        p.drawChord(path_rect, 0, 180 * 16)
        if style == "side":
            p.drawEllipse(QPointF(cx - w * 0.4, cy - h * 0.62), w * 0.7, 9)
    elif style == "curly":
        for i in range(7):
            ang = math.pi + i * math.pi / 6
            p.drawEllipse(QPointF(cx + math.cos(ang) * w * 0.85, cy - 6 + math.sin(ang) * h * 0.92), 11, 11)
    elif style == "mohawk":
        p.drawRoundedRect(QRectF(cx - 8, cy - h - 18, 16, 46), 8, 8)
    elif style == "long":
        p.drawChord(QRectF(cx - w, cy - h, 2 * w, h * 0.8), 0, 180 * 16)
    elif style == "afro":
        p.drawChord(QRectF(cx - w, cy - h * 1.02, 2 * w, h * 0.7), 0, 180 * 16)

    # yeux (un peu trop gros, c'est le but)
    eye_r = rng.uniform(8, 12)
    gap = rng.uniform(17, 24)
    ey = cy - 10
    for sx in (-1, 1):
        p.setPen(QPen(ink, 1.5))
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(cx + sx * gap, ey), eye_r, eye_r * 1.1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawEllipse(QPointF(cx + sx * gap + rng.uniform(-2, 2), ey + 1), eye_r * 0.45, eye_r * 0.45)
    # sourcils : plus fâchés si le joueur est violent
    angry = player.foul_index > 62
    p.setPen(QPen(hair if hair.lightness() < 200 else ink, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for sx in (-1, 1):
        inner = ey - eye_r - (4 if angry else 8)
        outer = ey - eye_r - (12 if angry else 7)
        p.drawLine(QPointF(cx + sx * (gap - eye_r), inner if sx == -1 else inner),
                   QPointF(cx + sx * (gap + eye_r), outer))
    # nez
    p.setPen(QPen(ink.lighter(160), 2))
    p.setBrush(skin.darker(112))
    nose = rng.choice(["round", "tri", "long"])
    if nose == "round":
        p.drawEllipse(QPointF(cx, cy + 8), 6, 5)
    elif nose == "tri":
        p.drawPolygon(QPolygonF([QPointF(cx, cy - 2), QPointF(cx - 6, cy + 11), QPointF(cx + 6, cy + 11)]))
    else:
        p.drawRoundedRect(QRectF(cx - 4, cy - 4, 8, 18), 4, 4)

    # barbe / moustache (pas pour les très jeunes)
    facial = rng.choice(["none", "none", "stache", "beard", "goatee", "stubble"]) if player.age >= 20 else "none"
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(hair.darker(115) if hair.lightness() < 200 else QColor("#bbb"))
    if facial == "beard":
        p.drawChord(QRectF(cx - w * 0.95, cy + 2, w * 1.9, h * 0.95), 180 * 16, 180 * 16)
    elif facial == "goatee":
        p.drawEllipse(QPointF(cx, cy + h * 0.78), 10, 9)
    elif facial == "stubble":
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawChord(QRectF(cx - w * 0.95, cy + 2, w * 1.9, h * 0.95), 180 * 16, 180 * 16)
    # bouche
    my = cy + h * 0.5
    mouth = rng.choice(["smile", "grin", "flat", "open", "smirk"])
    p.setPen(QPen(ink, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if mouth == "smile":
        p.drawArc(QRectF(cx - 16, my - 10, 32, 20), 200 * 16, 140 * 16)
    elif mouth == "grin":
        p.setBrush(QColor("white"))
        p.drawChord(QRectF(cx - 18, my - 12, 36, 24), 180 * 16, 180 * 16)
        p.drawLine(QPointF(cx - 18, my), QPointF(cx + 18, my))
    elif mouth == "flat":
        p.drawLine(QPointF(cx - 12, my), QPointF(cx + 12, my))
    elif mouth == "open":
        p.setBrush(QColor("#8b1e2d"))
        p.drawEllipse(QPointF(cx, my + 2), 10, 8)
    else:
        p.drawArc(QRectF(cx - 6, my - 8, 26, 16), 200 * 16, 120 * 16)
    if facial == "stache":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(hair.darker(115) if hair.lightness() < 200 else QColor("#bbb"))
        p.drawRoundedRect(QRectF(cx - 17, my - 17, 34, 9), 4, 4)

    # extras rigolos
    extras = rng.sample(["glasses", "headband", "scar", "freckles", "blush", "goldtooth", "none", "none"], 2)
    if player.foul_index > 75 and "scar" not in extras:
        extras.append("scar")
    if "glasses" in extras:
        p.setPen(QPen(QColor("#222"), 2.2))
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawEllipse(QPointF(cx - gap, ey), eye_r + 4, eye_r + 4)
        p.drawEllipse(QPointF(cx + gap, ey), eye_r + 4, eye_r + 4)
        p.drawLine(QPointF(cx - gap + eye_r + 4, ey), QPointF(cx + gap - eye_r - 4, ey))
    if "headband" in extras:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(["#d62828", "#1d6fd1", "#f2b705", "#2a9d3f"][player.id % 4]))
        p.drawRect(QRectF(cx - w * 0.98, cy - h * 0.55, w * 1.96, 10))
    if "scar" in extras:
        p.setPen(QPen(QColor("#b04040"), 2))
        p.drawLine(QPointF(cx + 16, cy - 28), QPointF(cx + 26, cy - 4))
        for k in range(3):
            p.drawLine(QPointF(cx + 17 + k * 3, cy - 22 + k * 7), QPointF(cx + 24 + k * 3, cy - 24 + k * 7))
    if "freckles" in extras:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#a5633a"))
        for dx, dy in ((-24, 12), (-18, 16), (-12, 11), (12, 11), (18, 16), (24, 12)):
            p.drawEllipse(QPointF(cx + dx, cy + dy), 1.6, 1.6)
    if "blush" in extras:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 90, 90, 90))
        p.drawEllipse(QPointF(cx - 30, cy + 14), 9, 6)
        p.drawEllipse(QPointF(cx + 30, cy + 14), 9, 6)
    if "goldtooth" in extras and mouth in ("grin", "smile"):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f2c200"))
        p.drawRect(QRectF(cx + 4, my - 2, 5, 6))
    if player.age >= 34:                              # pattes d'oie
        p.setPen(QPen(QColor(0, 0, 0, 70), 1.4))
        for sx in (-1, 1):
            p.drawLine(QPointF(cx + sx * (gap + eye_r + 2), ey - 2), QPointF(cx + sx * (gap + eye_r + 9), ey - 5))
            p.drawLine(QPointF(cx + sx * (gap + eye_r + 2), ey + 3), QPointF(cx + sx * (gap + eye_r + 9), ey + 6))
    # col de maillot
    p.setClipping(False)
    p.end()
    _face_cache[key] = pm
    return pm


# =============================================================================
# 3. RADAR ATT / MIL / GB / DEF
# =============================================================================
class RadarWidget(QWidget):
    """Diagramme radar des 4 aptitudes de poste (notes de 0 à 100)."""

    def __init__(self, values: dict | None = None):
        super().__init__()
        self.values = values or {}
        self.setMinimumSize(270, 200)

    def set_values(self, values: dict) -> None:
        self.values = values
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy, R = W / 2, H / 2 + 2, min(W / 2 - 52, H / 2 - 22)
        axes = [("ATT", "att", -math.pi / 2), ("MIL", "mid", 0.0), ("GB", "gk", math.pi / 2), ("DEF", "def", math.pi)]
        text_color = self.palette().color(self.foregroundRole())
        p.setPen(QPen(QColor(128, 128, 128, 120), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for level in (0.25, 0.5, 0.75, 1.0):
            p.drawPolygon(QPolygonF([QPointF(cx + R * level * math.cos(a), cy + R * level * math.sin(a))
                                     for _, _, a in axes]))
        for _, _, a in axes:
            p.drawLine(QPointF(cx, cy), QPointF(cx + R * math.cos(a), cy + R * math.sin(a)))
        pts = []
        for _, role, a in axes:
            v = max(0.0, min(100.0, float(self.values.get(role, 0)))) / 100
            pts.append(QPointF(cx + R * v * math.cos(a), cy + R * v * math.sin(a)))
        p.setPen(QPen(QColor("#2f6fd6"), 2))
        p.setBrush(QColor(47, 111, 214, 90))
        p.drawPolygon(QPolygonF(pts))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(12)
        p.setFont(font)
        p.setPen(text_color)
        for (label, role, a) in axes:
            text = f"{label} {self.values.get(role, 0):.0f}"
            if math.cos(a) > 0.5:                                      # à droite : aligné à gauche du texte
                rect, align = QRectF(cx + R + 6, cy - 9, 60, 18), Qt.AlignmentFlag.AlignLeft
            elif math.cos(a) < -0.5:                                   # à gauche : aligné à droite
                rect, align = QRectF(cx - R - 66, cy - 9, 60, 18), Qt.AlignmentFlag.AlignRight
            else:                                                      # en haut / en bas
                ty = cy - R - 20 if math.sin(a) < 0 else cy + R + 4
                rect, align = QRectF(cx - 40, ty, 80, 18), Qt.AlignmentFlag.AlignCenter
            p.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, text)


# =============================================================================
# 4. ANECDOTES (adresse, style de vie...) : stables pour un joueur donné
# =============================================================================
LIFESTYLES = [
    "Couche-tôt, sieste de 40 minutes obligatoire", "Console jusqu'à 3 h du matin (en cachette)",
    "Végétarien… sauf le week-end", "Réveil à 5 h pour courir (personne ne le lui a demandé)",
    "Collectionne les chaussettes dépareillées", "Ne sort jamais sans son bonnet porte-bonheur",
    "Cuisine pour toute l'équipe le dimanche", "Parle à sa plante verte avant chaque match",
    "Mange une banane en cachette à la mi-temps", "Médite dix minutes dans le bus du club",
    "Joue de la guitare dans les vestiaires (faux)", "Ne rate aucun épisode de sa série du soir",
]
HOBBIES = ["Pêche", "Échecs", "Jardinage", "Karting", "Pâtisserie", "Poker", "Photographie", "Bricolage",
           "Danse", "Padel", "Jeux de société", "Cinéma d'auteur"]
DISHES = ["Couscous", "Pizza (sans ananas)", "Pot-au-feu", "Paella", "Sushis", "Raclette", "Tacos", "Lasagnes",
          "Poulet-frites", "Tajine", "Burger maison", "Crêpes"]


def fun_facts(player) -> dict:
    """Adresse, style de vie, hobby et plat favori : tirés de l'identifiant du joueur (toujours les mêmes)."""
    pick = lambda items, tag: items[zlib.crc32(f"{player.id}:{tag}".encode()) % len(items)]
    try:
        address = Faker(seed=player.id).get_address(player.country)
    except Exception:
        address = player.country
    return {"Adresse": address, "Style de vie": pick(LIFESTYLES, "life"), "Hobby": pick(HOBBIES, "hobby"),
            "Plat favori": pick(DISHES, "dish")}
