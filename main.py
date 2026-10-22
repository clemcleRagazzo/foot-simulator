"""
league_app.py : interface PyQt6 de la simulation de ligue.

    pip install PyQt6
    python league_app.py --db players.db

Onglets : Classement | Matchs (+ formations) | Équipes | Transferts | Buteurs | Passeurs | Coupe
"""
import argparse
import os
import sys
from collections import Counter

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import (QAction, QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath,
                         QPen, QPixmap, QTextDocument)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox,
                             QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
                             QToolBar, QVBoxLayout, QWidget)

from cup_engine import Cup, describe_structure, next_power_of_two
from league_engine import (BASE_GOALS, FORMATIONS, K, MAX_TEAMS, MIN_TEAMS, MODEL_EXPLANATION, ROLE_LABELS, ROLES,
                           STATS, League, Player, Team, league_zones)

GREEN, RED, GREY = "#2e9e4f", "#d64545", "#8a8a8a"
BLUE, ORANGE = "#2f6fd6", "#f08a24"
ZONE_BG = {"blue": (47, 111, 214, 70), "orange": (240, 138, 36, 85), "red": (220, 20, 60, 65)}
WIN_BG, LOSS_BG, DRAW_BG = (46, 158, 79, 80), (214, 69, 69, 80), (128, 128, 128, 80)


# =============================================================================
# 1. LOGOS (dessinés par le code, un blason unique par équipe)
# =============================================================================
_LOGO_CACHE: dict = {}


def make_logo(team: Team, size: int = 64) -> QPixmap:
    key = (team.id, team.primary, team.secondary, team.pattern, team.short, size)
    if key in _LOGO_CACHE:
        return _LOGO_CACHE[key]

    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w = h = float(size)

    shield = QPainterPath()
    shield.moveTo(w * 0.12, h * 0.06)
    shield.lineTo(w * 0.88, h * 0.06)
    shield.lineTo(w * 0.88, h * 0.52)
    shield.cubicTo(w * 0.88, h * 0.78, w * 0.66, h * 0.90, w * 0.50, h * 0.97)
    shield.cubicTo(w * 0.34, h * 0.90, w * 0.12, h * 0.78, w * 0.12, h * 0.52)
    shield.closeSubpath()

    primary, secondary = QColor(team.primary), QColor(team.secondary)
    p.setClipPath(shield)
    p.fillPath(shield, primary)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(secondary)
    if team.pattern == "stripes":
        for k in (1, 3):
            p.drawRect(QRectF(w * (0.12 + 0.76 * k / 5), 0, w * 0.76 / 5, h))
    elif team.pattern == "split":
        p.drawRect(QRectF(w * 0.5, 0, w * 0.5, h))
    elif team.pattern == "band":
        band = QPainterPath()
        band.moveTo(0, h * 0.10); band.lineTo(w * 0.45, h * 0.06); band.lineTo(w, h * 0.62)
        band.lineTo(w, h * 0.86); band.lineTo(w * 0.55, h * 0.46); band.lineTo(0, h * 0.34)
        band.closeSubpath()
        p.drawPath(band)
    elif team.pattern == "hoops":
        for k in (1, 3):
            p.drawRect(QRectF(0, h * (0.06 + 0.2 * k), w, h * 0.2))
    elif team.pattern == "cross":
        p.drawRect(QRectF(w * 0.42, 0, w * 0.16, h))
        p.drawRect(QRectF(0, h * 0.16, w, h * 0.12))
    p.setClipping(False)

    p.setPen(QPen(QColor("#1f1f1f"), max(1.5, size * 0.045)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(shield)

    plate = QRectF(w * 0.22, h * 0.34, w * 0.56, h * 0.26)
    p.setBrush(QColor(255, 255, 255, 238))
    p.setPen(QPen(QColor("#1f1f1f"), max(1.0, size * 0.02)))
    p.drawRoundedRect(plate, size * 0.06, size * 0.06)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(6, int(size * 0.19)))
    p.setFont(font)
    p.setPen(QColor("#1f1f1f"))
    p.drawText(plate, Qt.AlignmentFlag.AlignCenter, team.short)
    p.end()
    _LOGO_CACHE[key] = pix
    return pix


def logo_icon(team: Team) -> QIcon:
    return QIcon(make_logo(team, 64))


# =============================================================================
# 2. OUTILS TABLEAUX
# =============================================================================
def cell(text="", align="center", bold=False, color=None, bg=None, icon=None, size=None) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    horizontal = {"center": Qt.AlignmentFlag.AlignHCenter, "left": Qt.AlignmentFlag.AlignLeft,
                  "right": Qt.AlignmentFlag.AlignRight}[align]
    item.setTextAlignment(horizontal | Qt.AlignmentFlag.AlignVCenter)
    if bold or size:
        font = item.font()
        font.setBold(bold)
        if size:
            font.setPointSize(size)
        item.setFont(font)
    if color:
        item.setForeground(QBrush(QColor(color)))
    if bg:
        item.setBackground(QBrush(QColor(*bg) if isinstance(bg, tuple) else QColor(bg)))
    if icon:
        item.setIcon(icon)
    return item


def setup_table(table: QTableWidget, headers: list, row_height: int = 34) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.setAlternatingRowColors(True)
    table.setIconSize(QSize(28, 28))
    table.setShowGrid(False)
    table.horizontalHeader().setHighlightSections(False)


def role_text(player: Player) -> str:
    return ROLE_LABELS[player.best_position]


def fill_players_table(table: QTableWidget, players: list, captain_id=None) -> None:
    """Colonnes : Joueur, Poste, Âge, Pays, Note, GB, DEF, MIL, ATT."""
    table.setRowCount(len(players))
    for row, p in enumerate(players):
        name = p.name + ("  ©" if p.id == captain_id else "")
        table.setItem(row, 0, cell(name, "left", bold=p.id == captain_id))
        table.setItem(row, 1, cell(role_text(p), bold=True))
        table.setItem(row, 2, cell(p.age))
        table.setItem(row, 3, cell(p.country, "left"))
        table.setItem(row, 4, cell(f"{p.overall:.0f}", bold=True))
        for col, role in enumerate(ROLES, start=5):
            value = p.ovr[role]
            color = GREEN if value >= 75 else GREY if value < 45 else None
            table.setItem(row, col, cell(f"{value:.0f}", color=color))


PLAYER_HEADERS = ["Joueur", "Poste", "Âge", "Pays", "Note", "GB", "DEF", "MIL", "ATT"]


def make_player_table() -> QTableWidget:
    t = QTableWidget()
    setup_table(t, PLAYER_HEADERS, 28)
    h = t.horizontalHeader()
    h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
    return t


# =============================================================================
# 3. FICHE JOUEUR
# =============================================================================
STAT_LABELS = {
    "pace": "Vitesse", "acceleration": "Accélération", "shooting": "Tir", "finishing": "Finition",
    "passing": "Passe", "vision": "Vision", "dribbling": "Dribble", "crossing": "Centres",
    "heading": "Jeu de tête", "tackling": "Tacle", "marking": "Marquage", "strength": "Force",
    "stamina": "Endurance", "aggression": "Agressivité", "composure": "Sang-froid",
    "leadership": "Leadership", "gk_diving": "GB plongeon", "gk_handling": "GB prise de balle",
    "gk_reflexes": "GB réflexes", "gk_positioning": "GB placement",
}


class PlayerDialog(QDialog):
    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.setWindowTitle(player.name)
        layout = QVBoxLayout(self)
        title = QLabel(f"<h2>{player.name}</h2>{player.age} ans, {player.country} ({player.city}) | "
                       f"pied {player.preferred_foot} | potentiel {player.potential}")
        layout.addWidget(title)
        ratings = " &nbsp; ".join(f"<b>{ROLE_LABELS[r]}</b> {player.ovr[r]:.0f}" for r in ROLES)
        layout.addWidget(QLabel(f"Notes par poste : {ratings}"))
        form = QFormLayout()
        for stat in STATS:
            bar = QProgressBar()
            bar.setRange(0, 99)
            bar.setValue(player.stats[stat])
            bar.setFormat("%v")
            v = player.stats[stat]
            color = GREEN if v >= 75 else "#e0a030" if v >= 50 else RED
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")
            form.addRow(STAT_LABELS[stat], bar)
        layout.addLayout(form)
        self.resize(380, 640)


# =============================================================================
# 4. ONGLET CLASSEMENT
# =============================================================================
MEDALS = ["🥇", "🥈", "🥉"]


class StandingsTab(QWidget):
    HEADERS = ["#", "Évol.", "Équipe", "Général", "J", "G", "N", "P", "BP", "BC", "Diff", "Pts", "Δ Pts", "Forme"]

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Classement après la journée :</b>"))
        self.spin = QSpinBox()
        self.spin.setRange(0, 0)
        self.spin.valueChanged.connect(self.render)
        prev_btn, next_btn, last_btn = QPushButton("◀"), QPushButton("▶"), QPushButton("Dernière journée jouée")
        prev_btn.clicked.connect(lambda: self.spin.setValue(self.spin.value() - 1))
        next_btn.clicked.connect(lambda: self.spin.setValue(self.spin.value() + 1))
        last_btn.clicked.connect(lambda: self.spin.setValue(self.spin.maximum()))
        self.total_label = QLabel()
        for w in (prev_btn, self.spin, next_btn, self.total_label, last_btn):
            top.addWidget(w)
        top.addStretch()
        self.compare_label = QLabel()
        top.addWidget(self.compare_label)
        layout.addLayout(top)

        self.table = QTableWidget()
        setup_table(self.table, self.HEADERS, 36)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self.on_double_click)
        layout.addWidget(self.table)
        self.legend = QLabel()
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)

    def refresh(self):
        result = self.win.league.result
        self.spin.blockSignals(True)
        self.spin.setRange(0, result.played)
        self.spin.setValue(result.played)
        self.spin.blockSignals(False)
        self.total_label.setText(f"/ {result.total_days}")
        self.render()

    def render(self):
        league = self.win.league
        result = league.result
        md = self.spin.value()
        rows = result.tables[md]
        finished = result.finished and md == result.total_days
        n_blue, n_orange, n_red = league_zones(len(rows))
        previous = None
        if league.previous is not None and finished:
            previous = {r.team_id: r for r in league.previous.final_table}
        self.compare_label.setText("<i>Comparé à la simulation précédente</i>" if previous else "")
        self.legend.setText(
            f"<small><span style='color:{BLUE}'>■</span> Bleu = coupe interligue 1 ({n_blue} premiers) | "
            f"<span style='color:{ORANGE}'>■</span> Orange = coupe interligue 2 ({n_orange} suivants) | "
            f"<span style='color:{RED}'>■</span> Rouge = relégués ({n_red} derniers) &nbsp;—&nbsp; "
            "les couleurs apparaissent à la fin de la saison. 🥇🥈🥉 = podium. "
            "Évol. et Δ Pts = comparaison avec la simulation précédente (utile après un transfert). "
            "Double-clic sur une équipe pour voir son effectif.</small>")

        self.table.setRowCount(0)                      # supprime aussi les anciens widgets « Forme »
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            team: Team = league.teams[r.team_id]
            bg = None
            if finished:
                bg = ZONE_BG["blue"] if i < n_blue else ZONE_BG["orange"] if i < n_blue + n_orange else \
                     ZONE_BG["red"] if i >= len(rows) - n_red else None

            evol, dpts, evol_color, dpts_color = "–", "–", GREY, GREY
            if previous:
                dr = previous[r.team_id].rank - r.rank
                dp = r.pts - previous[r.team_id].pts
                evol = f"▲ {dr}" if dr > 0 else f"▼ {-dr}" if dr < 0 else "="
                evol_color = GREEN if dr > 0 else RED if dr < 0 else GREY
                dpts = f"{dp:+d}"
                dpts_color = GREEN if dp > 0 else RED if dp < 0 else GREY

            rank_text = f"{MEDALS[i]} {r.rank}" if md > 0 and i < 3 else str(r.rank)
            values = [rank_text, evol, None, team.overall_rating, r.played, r.won, r.drawn, r.lost, r.gf, r.ga,
                      f"{r.gd:+d}", r.pts, dpts]
            for col, value in enumerate(values):
                if col == 2:
                    item = cell(team.name, "left", bold=True, icon=logo_icon(team), bg=bg)
                    item.setData(Qt.ItemDataRole.UserRole, team.id)
                elif col == 1:
                    item = cell(value, bold=True, color=evol_color, bg=bg)
                elif col == 12:
                    item = cell(value, bold=True, color=dpts_color, bg=bg)
                else:
                    item = cell(value, bold=col in (0, 10, 11), bg=bg)
                self.table.setItem(i, col, item)

            dots = "".join(f"<span style='color:{GREEN if f == 'V' else GREY if f == 'N' else RED}'>●</span> "
                           for f in r.form)
            label = QLabel(dots)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background: transparent; font-size: 14px;")
            self.table.setCellWidget(i, 13, label)
        for col, width in {0: 62, 1: 56, 3: 56, 4: 36, 5: 36, 6: 36, 7: 44, 8: 44, 9: 50, 10: 50, 11: 56, 12: 70}.items():
            self.table.setColumnWidth(col, width)

    def on_double_click(self, row, _col):
        team_id = self.table.item(row, 2).data(Qt.ItemDataRole.UserRole)
        self.win.open_team(team_id)


# =============================================================================
# 5. TERRAIN + DÉTAIL D'UN MATCH (réutilisé par la ligue et la coupe)
# =============================================================================
def short_name(name: str) -> str:
    parts = name.split()
    return (parts[-1] if len(parts) > 1 else name)[:12]


def center_order(items: list) -> list:
    """Place le premier élément au centre de la ligne, les suivants de part et d'autre."""
    out = []
    for i, item in enumerate(items):
        out.append(item) if i % 2 == 0 else out.insert(0, item)
    return out


class PitchWidget(QWidget):
    """Terrain vertical : l'équipe à domicile en bas, l'extérieur en haut, chacune dans sa formation."""

    def __init__(self):
        super().__init__()
        self.match = None
        self.home = self.away = None
        self.pens = None
        self.setMinimumSize(380, 520)

    def set_match(self, home, away, match, pens=None):
        self.home, self.away, self.match, self.pens = home, away, match, pens
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if self.match is None:
            p.setPen(QColor(GREY))
            p.drawText(QRectF(0, 0, W, H), Qt.AlignmentFlag.AlignCenter, "Sélectionne un match")
            return
        top = 32
        field = QRectF(10, top, W - 20, H - 2 * top)
        fw, fh = field.width(), field.height()

        # pelouse rayée
        for i in range(12):
            color = QColor("#2f8f46") if i % 2 == 0 else QColor("#2a833f")
            p.fillRect(QRectF(field.left(), field.top() + i * fh / 12, fw, fh / 12 + 1), color)
        p.setPen(QPen(QColor(255, 255, 255, 210), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(field)
        mid = field.center().y()
        p.drawLine(QPointF(field.left(), mid), QPointF(field.right(), mid))
        p.drawEllipse(field.center(), fw * 0.13, fw * 0.13)
        cx = field.center().x()
        for at_top in (True, False):
            y = field.top() if at_top else field.bottom()
            sign = 1 if at_top else -1
            for w_ratio, d_ratio in ((0.56, 0.15), (0.26, 0.055)):
                bw, bd = fw * w_ratio, fh * d_ratio
                p.drawRect(QRectF(cx - bw / 2, y if at_top else y - bd, bw, bd))
            p.drawArc(QRectF(cx - fw * 0.09, y + sign * fh * 0.15 - fw * 0.09, fw * 0.18, fw * 0.18),
                      (180 if at_top else 0) * 16, 180 * 16)

        # score au centre
        m = self.match
        font = QFont()
        font.setBold(True)
        font.setPixelSize(30)
        p.setFont(font)
        score = f"{m.home_goals} - {m.away_goals}"
        p.setPen(QColor(0, 0, 0, 90))
        p.drawText(QRectF(field.left() + 1, mid - 21, fw, 42), Qt.AlignmentFlag.AlignCenter, score)
        p.setPen(QColor(255, 255, 255, 235))
        p.drawText(QRectF(field.left(), mid - 22, fw, 42), Qt.AlignmentFlag.AlignCenter, score)
        if self.pens:
            small = QFont()
            small.setBold(True)
            small.setPixelSize(12)
            p.setFont(small)
            p.drawText(QRectF(field.left(), mid + 18, fw, 16), Qt.AlignmentFlag.AlignCenter,
                       f"t.a.b. {self.pens[0]} - {self.pens[1]}")

        self._draw_side(p, field, m.home, self.home, True)
        self._draw_side(p, field, m.away, self.away, False)

        # titres
        head = QFont()
        head.setBold(True)
        head.setPixelSize(13)
        p.setFont(head)
        p.setPen(self.palette().color(self.foregroundRole()))
        for team, side, y in ((self.away, m.away, 4), (self.home, m.home, H - top + 4)):
            p.drawPixmap(12, int(y), make_logo(team, 24))
            p.drawText(QRectF(42, y, W - 52, 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"{team.name}   ·   {side.formation}")

    def _draw_side(self, p, field, side, team, is_home):
        fw, fh = field.width(), field.height()
        rows = FORMATIONS[side.formation]
        by_role = {}
        for name, role, rating in side.lineup:
            by_role.setdefault(role, []).append((name, rating))
        used = {role: 0 for role in by_role}
        goals = Counter(e.player_name for e in self.match.goals if e.team_id == team.id)
        n_rows = len(rows)
        radius = max(11.0, min(17.0, fw * 0.045))
        fill, edge = QColor(team.primary), QColor(team.secondary)
        text_color = QColor("#111") if fill.lightness() > 150 else QColor("white")
        for i, (role, count) in enumerate(rows):
            items = by_role[role][used[role]:used[role] + count]
            used[role] += count
            items = center_order(items)
            f = 0.12 if i == 0 else 0.30 + (0.84 - 0.30) * (i - 1) / (n_rows - 2)
            y = field.bottom() - f * fh / 2 if is_home else field.top() + f * fh / 2
            for k, (name, rating) in enumerate(items):
                x = field.left() + fw * (k + 1) / (len(items) + 1)
                body, body_edge, body_text = (QColor("#f4c20d"), QColor("#7a5c00"), QColor("#111")) \
                    if role == "gk" else (fill, edge, text_color)
                p.setBrush(body)
                p.setPen(QPen(body_edge, 2))
                p.drawEllipse(QPointF(x, y), radius, radius)
                f1 = QFont()
                f1.setBold(True)
                f1.setPixelSize(int(radius * 0.95))
                p.setFont(f1)
                p.setPen(body_text)
                p.drawText(QRectF(x - radius, y - radius, 2 * radius, 2 * radius), Qt.AlignmentFlag.AlignCenter,
                           f"{rating:.0f}")
                f2 = QFont()
                f2.setBold(True)
                f2.setPixelSize(11)
                p.setFont(f2)
                label = QRectF(x - 48, y + radius + 1, 96, 14)
                p.setPen(QColor(0, 0, 0, 170))
                p.drawText(label.translated(1, 1), Qt.AlignmentFlag.AlignCenter, short_name(name))
                p.setPen(QColor("white"))
                p.drawText(label, Qt.AlignmentFlag.AlignCenter, short_name(name))
                if goals.get(name):
                    n = goals[name]
                    p.setPen(QColor("white"))
                    p.drawText(QRectF(x + radius * 0.6, y - radius * 1.7, 34, 14), Qt.AlignmentFlag.AlignLeft,
                               "⚽" + (f"×{n}" if n > 1 else ""))


class MatchDetailView(QTabWidget):
    """Deux onglets : 🎽 Formations (terrain) et 📋 Résumé (buts, passeurs, analyse)."""

    def __init__(self):
        super().__init__()
        self.pitch = PitchWidget()
        self.summary = QTextBrowser()
        self.summary.setOpenLinks(False)
        self.addTab(self.pitch, "🎽 Formations")
        self.addTab(self.summary, "📋 Résumé et analyse")

    def clear_match(self):
        self.summary.clear()
        self.pitch.set_match(None, None, None)

    def show_match(self, league: League, m, pens=None, round_label=None):
        home, away = league.teams[m.home_id], league.teams[m.away_id]
        self.pitch.set_match(home, away, m, pens)
        for team in (home, away):
            self.summary.document().addResource(QTextDocument.ResourceType.ImageResource,
                                                QUrl(f"logo:{team.id}"), make_logo(team, 64).toImage())

        def mood_text(side):
            parts = ", ".join(f"{d:+d}" for d in side.last3) or "aucun match"
            return f"{parts} &rarr; x{side.mood_factor:.3f}"

        def analysis_rows(side):
            return [
                ("Formation", side.formation),
                ("Attaque / Défense", f"{side.attack:.1f} / {side.defense:.1f}"),
                ("Rapport att. / déf. adverse", f"{side.ratio:.3f}"),
                ("3 derniers écarts de buts", mood_text(side)),
                ("Entraîneur", f"x{side.coach_factor:.3f}"),
                ("Capitaine", f"x{side.captain_factor:.3f}"),
                ("Banc", f"x{side.depth_factor:.3f}"),
                ("Forme totale", f"<b>x{side.multiplier:.3f}</b>"),
                ("Lieu", f"x{side.venue_factor:.2f}"),
                ("Buts attendus (xG)", f"<b>{side.xg:.2f}</b>"),
            ]

        label = round_label or f"Journée {m.matchday}"
        pens_html = f"<br><span style='color:{GREY}'>t.a.b. {pens[0]} - {pens[1]}</span>" if pens else ""
        html = [f"""
        <table width='100%' cellpadding='4'><tr>
          <td align='center'><img src='logo:{home.id}' width='56'><br><b>{home.name}</b></td>
          <td align='center'><span style='font-size:30px'><b>{m.home_goals} - {m.away_goals}</b></span>
              <br><span style='color:{GREY}'>{label}</span>{pens_html}</td>
          <td align='center'><img src='logo:{away.id}' width='56'><br><b>{away.name}</b></td>
        </tr></table><hr>"""]

        html.append("<b>Buts</b><br>")
        if m.goals:
            for e in m.goals:
                side = "◀" if e.team_id == m.home_id else "▶"
                team = home if e.team_id == m.home_id else away
                assist = (f" <span style='color:{GREY}'>passe de {e.assist_name}</span>" if e.assist_name else "")
                html.append(f"{e.minute}' &nbsp; {side} <b>{e.player_name}</b> "
                            f"<span style='color:{GREY}'>({team.short})</span>{assist}<br>")
        else:
            html.append("<i>0 - 0, aucun but</i><br>")

        html.append("<hr><b>Analyse du score</b>")
        html.append("<table width='100%' cellpadding='3' border='0'>"
                    f"<tr><td></td><td align='center'><b>{home.short}</b></td><td align='center'><b>{away.short}</b></td></tr>")
        for (lab, hv), (_, av) in zip(analysis_rows(m.home), analysis_rows(m.away)):
            html.append(f"<tr><td>{lab}</td><td align='center'>{hv}</td><td align='center'>{av}</td></tr>")
        html.append("</table>")
        html.append(f"<small style='color:{GREY}'>xG = {BASE_GOALS} x (att/déf adverse)^{K} x forme x lieu / "
                    f"racine(forme adverse). Buts = arrondi de xG + reste des matchs précédents.</small>")

        html.append("<hr><b>Compositions</b><table width='100%' cellpadding='2'><tr>")
        for side in (m.home, m.away):
            html.append(f"<td valign='top'><b>{side.formation}</b><br>")
            for name, role, rating in side.lineup:
                html.append(f"<span style='color:{GREY}'>{ROLE_LABELS[role]}</span> {name} "
                            f"<small>({rating:.0f})</small><br>")
            html.append("</td>")
        html.append("</tr></table>")
        self.summary.setHtml("".join(html))


# =============================================================================
# 6. ONGLET MATCHS
# =============================================================================
class MatchesTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.rows: list = []
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer = QHBoxLayout(self)
        outer.addWidget(splitter)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("<b>Équipe</b>"))
        self.team_filter = QComboBox()
        self.team_filter.currentIndexChanged.connect(self.render_table)
        lv.addWidget(self.team_filter)
        lv.addWidget(QLabel("<b>Journée</b>"))
        self.day_list = QListWidget()
        self.day_list.currentRowChanged.connect(self.render_table)
        lv.addWidget(self.day_list)
        left.setMaximumWidth(210)

        middle = QWidget()
        mv = QVBoxLayout(middle)
        self.table = QTableWidget()
        setup_table(self.table, ["J", "Domicile", "Score", "Extérieur", "xG dom.", "xG ext."], 38)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)
        mv.addWidget(self.table)
        mv.addWidget(QLabel(f"<small><span style='color:{GREEN}'>■</span> équipe gagnante | "
                            f"<span style='color:{RED}'>■</span> équipe perdante | "
                            f"<span style='color:{GREY}'>■</span> ligne grise = match nul</small>"))

        self.detail = MatchDetailView()
        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(self.detail)
        splitter.setSizes([180, 540, 540])

    def refresh(self):
        league, result = self.win.league, self.win.league.result
        self.team_filter.blockSignals(True)
        self.day_list.blockSignals(True)
        current_team = self.team_filter.currentData()
        old_count, current = self.day_list.count(), self.day_list.currentRow()
        follow = current < 0 or current == old_count - 1            # on suit la dernière journée jouée
        self.team_filter.clear()
        self.team_filter.addItem("Toutes les équipes", None)
        for team in sorted(league.teams.values(), key=lambda t: t.name):
            self.team_filter.addItem(logo_icon(team), team.name, team.id)
        self.team_filter.setCurrentIndex(max(0, self.team_filter.findData(current_team)))
        self.day_list.clear()
        for md in range(1, result.played + 1):
            self.day_list.addItem(f"Journée {md}")
        if result.played:
            self.day_list.setCurrentRow(result.played - 1 if follow else min(current, result.played - 1))
        self.team_filter.blockSignals(False)
        self.day_list.blockSignals(False)
        self.render_table()

    def render_table(self, *_):
        league, result = self.win.league, self.win.league.result
        team_id = self.team_filter.currentData()
        self.day_list.setEnabled(team_id is None)
        if team_id is None:
            md = self.day_list.currentRow()
            self.rows = list(result.matchdays[md]) if 0 <= md < result.played else []
        else:
            self.rows = result.matches_of(team_id)

        self.table.setRowCount(len(self.rows))
        for i, m in enumerate(self.rows):
            home, away = league.teams[m.home_id], league.teams[m.away_id]
            if m.home_goals == m.away_goals:
                bg_home = bg_away = bg_other = DRAW_BG                    # ligne entière grise
            else:
                home_won = m.home_goals > m.away_goals
                bg_home, bg_away = (WIN_BG, LOSS_BG) if home_won else (LOSS_BG, WIN_BG)
                bg_other = None
            hw, aw = m.home_goals > m.away_goals, m.away_goals > m.home_goals
            self.table.setItem(i, 0, cell(m.matchday, color=GREY, bg=bg_other))
            self.table.setItem(i, 1, cell(home.name, "left", bold=hw, icon=logo_icon(home), bg=bg_home))
            self.table.setItem(i, 2, cell(f"{m.home_goals} - {m.away_goals}", bold=True, size=12, bg=bg_other))
            self.table.setItem(i, 3, cell(away.name, "left", bold=aw, icon=logo_icon(away), bg=bg_away))
            self.table.setItem(i, 4, cell(f"{m.home.xg:.2f}", color=GREY, bg=bg_other))
            self.table.setItem(i, 5, cell(f"{m.away.xg:.2f}", color=GREY, bg=bg_other))
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 60)
        if self.rows:
            self.table.selectRow(0)
            self.show_detail()                         # la sélection peut ne pas changer : on force
        else:
            self.detail.clear_match()

    def show_detail(self):
        selected = self.table.selectionModel().selectedRows()
        if selected:
            self.detail.show_match(self.win.league, self.rows[selected[0].row()])


# =============================================================================
# 7. ONGLET ÉQUIPES
# =============================================================================
class TeamsTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.players: list = []
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.currentIndexChanged.connect(self.render)
        top.addWidget(self.combo)
        self.logo = QLabel()
        self.logo.setFixedSize(96, 96)
        top.addWidget(self.logo)
        self.info = QLabel()
        self.info.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.info, 1)
        layout.addLayout(top)

        self.table = QTableWidget()
        setup_table(self.table, ["Joueur", "Poste", "Âge", "Pays", "Note", "GB", "DEF", "MIL", "ATT", "Rôle"], 30)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda row, _c: PlayerDialog(self.players[row], self).exec())
        layout.addWidget(self.table)
        layout.addWidget(QLabel("<small>© = capitaine | Double-clic sur un joueur pour voir toutes ses stats.</small>"))

    def refresh(self):
        league = self.win.league
        current = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        for team in sorted(league.teams.values(), key=lambda t: t.name):
            self.combo.addItem(logo_icon(team), team.name, team.id)
        self.combo.setCurrentIndex(max(0, self.combo.findData(current)))
        self.combo.blockSignals(False)
        self.render()

    def select_team(self, team_id: int):
        self.combo.setCurrentIndex(max(0, self.combo.findData(team_id)))

    def render(self, *_):
        league, result = self.win.league, self.win.league.result
        team = league.teams[self.combo.currentData()]
        self.logo.setPixmap(make_logo(team, 96))
        row = next(r for r in result.current_table if r.team_id == team.id)
        season_text = (f"{row.rank}e, {row.pts} pts ({row.won}V {row.drawn}N {row.lost}D, diff. {row.gd:+d})"
                       if row.played else "pas encore commencée")
        profile = result.profiles[team.id]
        captain = team.captain
        self.info.setText(
            f"<h2>{team.name}</h2>"
            f"<b>Entraîneur</b> : {team.coach.name} (tactique {team.coach.tactics}, motivation {team.coach.motivation})<br>"
            f"<b>Capitaine</b> : {captain.name if captain else '-'} (leadership {captain.stats['leadership'] if captain else '-'})<br>"
            f"<b>Formation</b> : {team.formation}<br>"
            f"<b>Niveau</b> : attaque {profile.attack:.1f} | défense {profile.defense:.1f}<br>"
            f"<b>Saison</b> : {season_text}")

        xi_roles = {p.id: r for p, r, _ in profile.xi}
        order = {r: i for i, r in enumerate(("gk", "def", "mid", "att"))}
        self.players = sorted(team.players, key=lambda p: (p.id not in xi_roles,
                              order[xi_roles.get(p.id, p.best_position)], -p.ovr[xi_roles.get(p.id, p.best_position)]))
        self.table.setRowCount(len(self.players))
        for i, p in enumerate(self.players):
            starter = p.id in xi_roles
            name = p.name + ("  ©" if p.id == team.captain_id else "")
            self.table.setItem(i, 0, cell(name, "left", bold=starter))
            self.table.setItem(i, 1, cell(role_text(p), bold=True))
            self.table.setItem(i, 2, cell(p.age))
            self.table.setItem(i, 3, cell(p.country, "left"))
            self.table.setItem(i, 4, cell(f"{p.overall:.0f}", bold=True))
            for col, role in enumerate(ROLES, start=5):
                v = p.ovr[role]
                self.table.setItem(i, col, cell(f"{v:.0f}", color=GREEN if v >= 75 else GREY if v < 45 else None))
            self.table.setItem(i, 9, cell(f"Titulaire ({ROLE_LABELS[xi_roles[p.id]]})" if starter else "Remplaçant",
                                          color=None if starter else GREY))


# =============================================================================
# 8. ONGLET TRANSFERTS
# =============================================================================
class TransfersTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.my_players: list = []
        self.candidates: list = []
        root = QVBoxLayout(self)

        columns = QHBoxLayout()
        root.addLayout(columns, 1)

        # ---- gauche : l'équipe qui vend un joueur
        left = QGroupBox("1. Équipe et joueur qui PART")
        lv = QVBoxLayout(left)
        self.team_combo = QComboBox()
        self.team_combo.currentIndexChanged.connect(self.on_team_changed)
        lv.addWidget(self.team_combo)
        self.my_table = make_player_table()
        self.my_table.itemSelectionChanged.connect(self.update_summary)
        lv.addWidget(self.my_table)
        columns.addWidget(left, 1)

        # ---- droite : le joueur recherché
        right = QGroupBox("2. Joueur qui ARRIVE")
        rv = QVBoxLayout(right)
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self.search)
        rv.addWidget(self.source_combo)

        filters = QHBoxLayout()
        self.role_combo = QComboBox()
        self.role_combo.addItem("Tous postes", None)
        for r in ROLES:
            self.role_combo.addItem(ROLE_LABELS[r], r)
        self.min_rating = QSpinBox()
        self.min_rating.setRange(0, 99)
        self.min_rating.setValue(70)
        self.min_rating.setPrefix("Note min ")
        self.max_age = QSpinBox()
        self.max_age.setRange(16, 45)
        self.max_age.setValue(36)
        self.max_age.setPrefix("Âge max ")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Nom…")
        self.name_edit.returnPressed.connect(self.search)
        search_btn = QPushButton("Rechercher")
        search_btn.clicked.connect(self.search)
        for w in (self.role_combo, self.min_rating, self.max_age, self.name_edit, search_btn):
            filters.addWidget(w)
        rv.addLayout(filters)
        self.cand_table = make_player_table()
        self.cand_table.itemSelectionChanged.connect(self.update_summary)
        rv.addWidget(self.cand_table)
        columns.addWidget(right, 1)

        # ---- bas : résumé + bouton + journal
        self.summary = QLabel("Sélectionne un joueur de chaque côté.")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.summary)
        actions = QHBoxLayout()
        self.auto_sim = QCheckBox("Relancer la simulation de toute la ligue après le transfert (si la saison est terminée)")
        self.auto_sim.setChecked(True)
        self.swap_btn = QPushButton("✔  Effectuer le transfert")
        self.swap_btn.setEnabled(False)
        self.swap_btn.clicked.connect(self.do_swap)
        actions.addWidget(self.auto_sim)
        actions.addStretch()
        actions.addWidget(self.swap_btn)
        root.addLayout(actions)
        root.addWidget(QLabel("<b>Journal des transferts</b>"))
        self.log = QListWidget()
        self.log.setMaximumHeight(110)
        root.addWidget(self.log)

    def refresh(self):
        league = self.win.league
        current = self.team_combo.currentData()
        self.team_combo.blockSignals(True)
        self.team_combo.clear()
        for team in sorted(league.teams.values(), key=lambda t: t.name):
            self.team_combo.addItem(logo_icon(team), team.name, team.id)
        self.team_combo.setCurrentIndex(max(0, self.team_combo.findData(current)))
        self.team_combo.blockSignals(False)
        self.log.clear()
        self.log.addItems(league.transfers)
        self.on_team_changed()

    def on_team_changed(self, *_):
        league = self.win.league
        team = league.teams[self.team_combo.currentData()]
        self.my_players = sorted(team.players, key=lambda p: (-p.overall, p.id))
        fill_players_table(self.my_table, self.my_players, team.captain_id)

        previous_source = self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("Marché libre (joueurs sans club)", None)
        for other in sorted(league.teams.values(), key=lambda t: t.name):
            if other.id != team.id:
                self.source_combo.addItem(logo_icon(other), f"Échange avec {other.name}", other.id)
        self.source_combo.setCurrentIndex(max(0, self.source_combo.findData(previous_source)))
        self.source_combo.blockSignals(False)
        self.search()

    def search(self, *_):
        league = self.win.league
        role, min_rating = self.role_combo.currentData(), self.min_rating.value()
        max_age, name = self.max_age.value(), self.name_edit.text().strip()
        source = self.source_combo.currentData()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if source is None:
                self.candidates = league.market(role, min_rating, max_age, name, limit=200)
            else:
                pool = league.teams[source].players
                key = (lambda p: p.ovr[role]) if role else (lambda p: p.overall)
                self.candidates = sorted(
                    (p for p in pool if key(p) >= min_rating and p.age <= max_age and name.lower() in p.name.lower()),
                    key=lambda p: -key(p))
        finally:
            QApplication.restoreOverrideCursor()
        captain = league.teams[source].captain_id if source else None
        fill_players_table(self.cand_table, self.candidates, captain)
        self.update_summary()

    def _selected(self, table, players):
        rows = table.selectionModel().selectedRows()
        return players[rows[0].row()] if rows else None

    def update_summary(self):
        out_p = self._selected(self.my_table, self.my_players)
        in_p = self._selected(self.cand_table, self.candidates)
        self.swap_btn.setEnabled(bool(out_p and in_p))
        if out_p and in_p:
            self.summary.setText(
                f"<b style='color:{RED}'>Part :</b> {out_p.name} ({role_text(out_p)} {out_p.overall:.0f}, {out_p.age} ans) "
                f"&nbsp;&nbsp;➜&nbsp;&nbsp; <b style='color:{GREEN}'>Arrive :</b> {in_p.name} "
                f"({role_text(in_p)} {in_p.overall:.0f}, {in_p.age} ans)")
        else:
            self.summary.setText("Sélectionne un joueur de chaque côté.")

    def do_swap(self):
        league = self.win.league
        out_p = self._selected(self.my_table, self.my_players)
        in_p = self._selected(self.cand_table, self.candidates)
        if not (out_p and in_p):
            return
        if league.in_progress:
            QMessageBox.information(self, "Saison en cours",
                                    "Les transferts se font avant la saison ou une fois la ligue terminée.\n"
                                    "Termine-la (⏭ Simuler toute la ligue) ou relance-la (↺ Rejouer la saison).")
            return
        try:
            text = league.swap(self.team_combo.currentData(), out_p, in_p, self.source_combo.currentData())
        except ValueError as error:
            QMessageBox.warning(self, "Transfert impossible", str(error))
            self.search()
            return
        self.win.statusBar().showMessage("Transfert effectué : " + text, 8000)
        if self.auto_sim.isChecked() and league.season.finished:
            self.win.rerun_full()
        else:
            self.win.refresh_all()


# =============================================================================
# 9. ONGLETS BUTEURS / PASSEURS
# =============================================================================
class StatsTab(QWidget):
    """kind = 'goals' (buteurs) ou 'assists' (passeurs décisifs)."""

    def __init__(self, win: "MainWindow", kind: str):
        super().__init__()
        self.win, self.kind = win, kind
        layout = QVBoxLayout(self)
        main, other = ("Buts", "Passes D.") if kind == "goals" else ("Passes D.", "Buts")
        self.table = QTableWidget()
        setup_table(self.table, ["#", "Joueur", "Équipe", main, other], 34)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def refresh(self):
        league, result = self.win.league, self.win.league.result
        if self.kind == "goals":
            top, other = result.top_scorers(30), result.assisters
        else:
            top, other = result.top_assisters(30), result.scorers
        self.table.setRowCount(len(top))
        for i, (pid, (name, team_id, count)) in enumerate(top):
            team = league.teams[team_id]
            self.table.setItem(i, 0, cell(MEDALS[i] if i < 3 else i + 1, bold=True))
            self.table.setItem(i, 1, cell(name, "left", bold=True))
            self.table.setItem(i, 2, cell(team.name, "left", icon=logo_icon(team)))
            self.table.setItem(i, 3, cell(count, bold=True))
            self.table.setItem(i, 4, cell(other.get(pid, [0, 0, 0])[2], color=GREY))
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 80)


# =============================================================================
# 10. COUPE : tableau en arbre, inscriptions, onglet
# =============================================================================
class BracketWidget(QWidget):
    """Dessine le tableau : barrages (si besoin) puis tours jusqu'à la finale et le vainqueur."""
    matchClicked = pyqtSignal(object)

    BOX_W, ROW_H, COL_GAP, TOP, LEFT, SPACING = 184, 24, 46, 44, 16, 76

    def __init__(self):
        super().__init__()
        self.cup: Cup | None = None
        self.league: League | None = None
        self._hits: list = []

    def set_cup(self, cup, league):
        self.cup, self.league = cup, league
        if cup is None:
            self.setMinimumSize(10, 10)
        else:
            lay = self._layout()
            self.setMinimumSize(int(lay["width"]), int(lay["height"]))
            self.resize(int(lay["width"]), int(lay["height"]))
        self.update()

    # ---- géométrie
    def _layout(self) -> dict:
        cup, bh = self.cup, 2 * self.ROW_H
        offset = 1 if cup.has_barrages else 0
        main_defs = cup.round_defs[offset:]
        centers = [[self.TOP + self.SPACING * (i + 0.5) for i in range(main_defs[0][1])]]
        for _ in range(1, len(main_defs)):
            prev = centers[-1]
            centers.append([(prev[2 * i] + prev[2 * i + 1]) / 2 for i in range(len(prev) // 2)])
        col_x = [self.LEFT + c * (self.BOX_W + self.COL_GAP) for c in range(len(cup.round_defs))]

        barrage_y, barrage_row_y = [], []
        if cup.has_barrages:
            wanted = []
            for seed in cup.barrage_slots:
                pos = cup.bracket_order.index(seed)
                row_y = centers[0][pos // 2] + (-self.ROW_H / 2 if pos % 2 == 0 else self.ROW_H / 2)
                barrage_row_y.append(row_y)
                wanted.append(row_y)
            order = sorted(range(len(wanted)), key=lambda i: wanted[i])
            placed = {}
            last = -1e9
            for i in order:
                y = max(wanted[i], last + bh + 10)
                placed[i] = y
                last = y
            barrage_y = [placed[i] for i in range(len(wanted))]
        bottom = max(centers[0][-1], *(barrage_y or [0])) + bh / 2 + 34
        width = col_x[-1] + self.BOX_W + self.COL_GAP + 190
        return dict(offset=offset, centers=centers, col_x=col_x, barrage_y=barrage_y,
                    barrage_row_y=barrage_row_y, width=width, height=bottom)

    # ---- dessin
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._hits = []
        if self.cup is None:
            return
        cup, league, bh = self.cup, self.league, 2 * self.ROW_H
        lay = self._layout()
        offset, centers, col_x = lay["offset"], lay["centers"], lay["col_x"]
        text, line = self.palette().color(self.foregroundRole()), QColor(GREY)

        head = QFont()
        head.setBold(True)
        head.setPixelSize(13)
        for c, (name, _n) in enumerate(cup.round_defs):
            p.setFont(head)
            p.setPen(text)
            p.drawText(QRectF(col_x[c], 8, self.BOX_W, 24), Qt.AlignmentFlag.AlignCenter, name)

        # barrages
        if cup.has_barrages:
            barrage_matches = cup.rounds[0] if cup.rounds else None
            for i, y in enumerate(lay["barrage_y"]):
                if barrage_matches:
                    cm = barrage_matches[i]
                    self._box(p, col_x[0], y, cm.home_id, cm.away_id, cm)
                else:
                    a, b = cup.barrage_pairs[i]
                    self._box(p, col_x[0], y, a, b, None)
                row_y = lay["barrage_row_y"][i]
                xm = col_x[1] - self.COL_GAP / 2
                p.setPen(QPen(line, 1.5))
                p.drawLine(QPointF(col_x[0] + self.BOX_W, y), QPointF(xm, y))
                p.drawLine(QPointF(xm, y), QPointF(xm, row_y))
                p.drawLine(QPointF(xm, row_y), QPointF(col_x[1], row_y))

        # tours du tableau principal
        for r, (name, n_matches) in enumerate(cup.round_defs[offset:]):
            g = r + offset
            x = col_x[g]
            played = cup.rounds[g] if g < len(cup.rounds) else None
            for i in range(n_matches):
                yc = centers[r][i]
                if played:
                    cm = played[i]
                    self._box(p, x, yc, cm.home_id, cm.away_id, cm)
                else:
                    if r == 0:
                        entries = cup.first_round_entries()
                        a, b = entries[2 * i], entries[2 * i + 1]
                    else:
                        prev = cup.rounds[g - 1] if g - 1 < len(cup.rounds) else None
                        a = prev[2 * i].winner_id if prev else None
                        b = prev[2 * i + 1].winner_id if prev else None
                    self._box(p, x, yc, a, b, None)
                if r > 0:
                    xm = x - self.COL_GAP / 2
                    p.setPen(QPen(line, 1.5))
                    for fy in (centers[r - 1][2 * i], centers[r - 1][2 * i + 1]):
                        p.drawLine(QPointF(col_x[g - 1] + self.BOX_W, fy), QPointF(xm, fy))
                        p.drawLine(QPointF(xm, fy), QPointF(xm, yc))
                    p.drawLine(QPointF(xm, yc), QPointF(x, yc))

        # vainqueur
        fx = col_x[-1] + self.BOX_W + self.COL_GAP
        fy = centers[-1][0]
        p.setPen(text)
        big = QFont()
        big.setPixelSize(34)
        p.setFont(big)
        p.drawText(QRectF(fx, fy - 70, 160, 44), Qt.AlignmentFlag.AlignCenter, "🏆")
        if cup.finished:
            champ = cup.champion
            p.drawPixmap(int(fx + 48), int(fy - 22), make_logo(champ, 64))
            head.setPixelSize(14)
            p.setFont(head)
            p.drawText(QRectF(fx, fy + 46, 160, 40), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       champ.name)
        else:
            p.setPen(line)
            p.drawText(QRectF(fx, fy - 20, 160, 40), Qt.AlignmentFlag.AlignCenter, "?")

    def _box(self, p, x, yc, top_id, bot_id, cm):
        league, rh = self.league, self.ROW_H
        top = yc - rh
        base, text = self.palette().color(self.backgroundRole()), self.palette().color(self.foregroundRole())
        rect = QRectF(x, top, self.BOX_W, 2 * rh)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.palette().color(self.palette().ColorRole.Base))
        p.drawRoundedRect(rect, 5, 5)
        for k, tid in enumerate((top_id, bot_id)):
            row = QRectF(x, top + k * rh, self.BOX_W, rh)
            won = cm is not None and tid == cm.winner_id
            if cm is not None:
                p.setClipRect(row)
                p.setBrush(QColor(*(WIN_BG if won else LOSS_BG)))
                p.drawRoundedRect(rect, 5, 5)
                p.setClipping(False)
            if tid is None:
                p.setPen(QColor(GREY))
                f = QFont()
                f.setItalic(True)
                f.setPixelSize(12)
                p.setFont(f)
                p.drawText(row.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, "à déterminer")
                continue
            team = league.teams[tid]
            p.drawPixmap(int(x + 4), int(row.top() + 3), make_logo(team, int(rh - 6)))
            f = QFont()
            f.setBold(won)
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(text)
            fm = QFontMetrics(f)
            p.drawText(QRectF(x + rh + 4, row.top(), self.BOX_W - rh - 52, rh), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(team.name, Qt.TextElideMode.ElideRight, int(self.BOX_W - rh - 52)))
            if cm is not None:
                goals = cm.result.home_goals if k == 0 else cm.result.away_goals
                label = str(goals)
                if cm.pens:
                    label += f" ({cm.pens[k]})"
                f.setBold(True)
                p.setFont(f)
                p.drawText(QRectF(x + self.BOX_W - 50, row.top(), 44, rh),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, label)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(GREY), 1.2))
        p.drawRoundedRect(rect, 5, 5)
        p.drawLine(QPointF(x, top + rh), QPointF(x + self.BOX_W, top + rh))
        if cm is not None:
            self._hits.append((rect, cm))

    def mousePressEvent(self, event):
        for rect, cm in self._hits:
            if rect.contains(event.position()):
                self.matchClicked.emit(cm)
                return


class CupEntryDialog(QDialog):
    """Choix des équipes inscrites à la coupe (n'importe quel nombre >= 2)."""

    def __init__(self, league: League, preselected: list, parent=None):
        super().__init__(parent)
        self.league = league
        self.setWindowTitle("Équipes inscrites à la coupe")
        layout = QVBoxLayout(self)
        qualified = league.qualified_for_cup()
        tag = {i: "  [Interligue 1]" for i in qualified["blue"]}
        tag.update({i: "  [Interligue 2]" for i in qualified["orange"]})
        self.qualified_ids = qualified["blue"] + qualified["orange"]
        ids = league.seed_order(list(league.teams))
        self.seed_ids = ids

        self.list = QListWidget()
        for rank, tid in enumerate(ids, start=1):
            team = league.teams[tid]
            item = QListWidgetItem(logo_icon(team), f"{rank}. {team.name}{tag.get(tid, '')}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if tid in preselected else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, tid)
            self.list.addItem(item)
        self.list.itemChanged.connect(self.update_info)
        layout.addWidget(self.list)

        row = QHBoxLayout()
        q_btn = QPushButton("Qualifiés de la ligue")
        q_btn.setEnabled(bool(self.qualified_ids))
        q_btn.setToolTip("Disponible quand la saison est terminée")
        q_btn.clicked.connect(lambda: self.set_checked(self.qualified_ids))
        grow_btn = QPushButton("＋ Ajouter des équipes (→ puissance de 2 suivante)")
        grow_btn.clicked.connect(self.grow)
        none_btn = QPushButton("Tout décocher")
        none_btn.clicked.connect(lambda: self.set_checked([]))
        for b in (q_btn, grow_btn, none_btn):
            row.addWidget(b)
        layout.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.resize(520, 640)
        self.update_info()

    def checked_ids(self) -> list:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def set_checked(self, ids: list):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in ids
                               else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self.update_info()

    def grow(self):
        """Complète avec les meilleures équipes restantes jusqu'à la puissance de 2 suivante (6 -> 8, 8 -> 16...)."""
        checked = self.checked_ids()
        target = min(max(2, next_power_of_two(len(checked))), len(self.seed_ids))
        for tid in self.seed_ids:
            if len(checked) >= target:
                break
            if tid not in checked:
                checked.append(tid)
        self.set_checked(checked)

    def update_info(self, *_):
        n = len(self.checked_ids())
        self.info.setText(describe_structure(n) if n >= 2 else "Il faut au moins 2 équipes.")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(n >= 2)


class CupTab(QWidget):
    """Coupe indépendante de la ligue : la ligue ne sert qu'à qualifier des équipes."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.entries: list = []
        self.cup: Cup | None = None
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        entries_btn = QPushButton("👥  Équipes inscrites…")
        entries_btn.clicked.connect(self.edit_entries)
        self.next_btn = QPushButton("▶  Tour suivant")
        self.next_btn.clicked.connect(lambda: self.play(False))
        self.all_btn = QPushButton("⏭  Simuler toute la coupe")
        self.all_btn.clicked.connect(lambda: self.play(True))
        self.reset_btn = QPushButton("↺  Rejouer la coupe")
        self.reset_btn.clicked.connect(self.rebuild)
        for b in (entries_btn, self.next_btn, self.all_btn, self.reset_btn):
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.bracket = BracketWidget()
        self.bracket.matchClicked.connect(self.show_match)
        scroll = QScrollArea()
        scroll.setWidget(self.bracket)
        scroll.setWidgetResizable(False)
        layout.addWidget(scroll, 1)
        layout.addWidget(QLabel("<small>Clique sur un match joué pour voir les formations, les buteurs et les "
                                "passeurs. Un match nul après 90 min se décide aux tirs au but. La finale se joue "
                                "sur terrain neutre.</small>"))

    def reset(self):
        self.entries, self.cup = [], None

    def refresh(self):
        league = self.win.league
        if self.cup is not None and not all(i in league.teams for i in self.entries):
            self.reset()
        self.bracket.set_cup(self.cup, league)
        for b in (self.next_btn, self.all_btn):
            b.setEnabled(self.cup is not None and not self.cup.finished)
        self.reset_btn.setEnabled(self.cup is not None)
        q = league.qualified_for_cup()
        if self.cup is None:
            if q["blue"]:
                names = lambda ids: ", ".join(league.teams[i].short for i in ids)
                self.info.setText(f"Aucune coupe en cours. Qualifiés par la ligue : Interligue 1 ({names(q['blue'])}) "
                                  f"et Interligue 2 ({names(q['orange'])}). Clique sur « Équipes inscrites… ».")
            else:
                self.info.setText("Aucune coupe en cours. Les qualifiés de la ligue sont connus à la fin de la saison, "
                                  "mais tu peux déjà inscrire les équipes de ton choix avec « Équipes inscrites… ».")
        else:
            state = (f"🏆 Vainqueur : <b>{self.cup.champion.name}</b>" if self.cup.finished
                     else f"Prochain tour : <b>{self.cup.next_round_name}</b>")
            self.info.setText(f"{describe_structure(len(self.entries))}. {state}")

    def edit_entries(self):
        league = self.win.league
        q = league.qualified_for_cup()
        pre = self.entries or (q["blue"] + q["orange"])
        dlg = CupEntryDialog(league, pre, self)
        if not dlg.exec():
            return
        if self.cup is not None and self.cup.rounds:
            if QMessageBox.question(self, "Nouvelle coupe",
                                    "Changer les inscrits relance la coupe depuis le début. Continuer ?") \
                    != QMessageBox.StandardButton.Yes:
                return
        self.entries = league.seed_order(dlg.checked_ids())
        self.rebuild()

    def rebuild(self):
        if not self.entries:
            return
        league = self.win.league
        self.cup = Cup([league.teams[i] for i in self.entries])
        self.refresh()

    def play(self, everything: bool):
        if self.cup is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.cup.play_all() if everything else self.cup.play_next_round()
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh()

    def show_match(self, cm):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Coupe : {cm.round_name}")
        lay = QVBoxLayout(dlg)
        view = MatchDetailView()
        view.show_match(self.win.league, cm.result, pens=cm.pens, round_label=cm.round_name)
        lay.addWidget(view)
        dlg.resize(560, 760)
        dlg.exec()


# =============================================================================
# 11. NOUVELLE LIGUE
# =============================================================================
class NewLeagueDialog(QDialog):
    def __init__(self, current_teams: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouvelle ligue")
        form = QFormLayout(self)
        self.teams = QSpinBox()
        self.teams.setRange(MIN_TEAMS, MAX_TEAMS)
        self.teams.setSingleStep(2)
        self.teams.setValue(current_teams)
        self.teams.valueChanged.connect(self.update_days)
        self.days = QLabel()
        self.seed = QSpinBox()
        self.seed.setRange(0, 10 ** 9)
        self.seed.setValue(42)
        form.addRow("Nombre d'équipes (pair) :", self.teams)
        form.addRow("Journées :", self.days)
        form.addRow("Graine (seed) :", self.seed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.update_days()

    def update_days(self):
        n = self.teams.value()
        if n % 2:
            self.teams.setValue(n + 1 if n < MAX_TEAMS else n - 1)
            return
        b, o, r = league_zones(n)
        self.days.setText(f"{2 * (n - 1)}  (zones : {b} bleues, {o} oranges, {r} relégués)")


# =============================================================================
# 12. FENÊTRE PRINCIPALE
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self, league: League):
        super().__init__()
        self.league = league
        if league.season is None:
            league.start_season()
        self.resize(1280, 800)

        toolbar = QToolBar("Actions")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)

        def action(text, slot):
            a = QAction(text, self)
            a.triggered.connect(slot)
            toolbar.addAction(a)
            return a

        self.next_action = action("▶  Journée suivante", lambda: self.advance(1))
        self.until_action = action("⏩  Jusqu'à la journée…", self.advance_until)
        self.all_action = action("⏭  Simuler toute la ligue", lambda: self.advance(None))
        toolbar.addSeparator()
        self.restart_action = action("↺  Rejouer la saison", self.restart_season)
        action("🔄  Nouvelle ligue…", self.new_league)
        action("ℹ  Comment sont calculés les scores", self.show_model)
        self.day_label = QLabel()
        self.statusBar().addPermanentWidget(self.day_label)

        self.tabs = QTabWidget()
        self.standings = StandingsTab(self)
        self.matches = MatchesTab(self)
        self.teams_tab = TeamsTab(self)
        self.transfers = TransfersTab(self)
        self.scorers = StatsTab(self, "goals")
        self.assists = StatsTab(self, "assists")
        self.cup_tab = CupTab(self)
        self.all_tabs = (self.standings, self.matches, self.teams_tab, self.transfers, self.scorers,
                         self.assists, self.cup_tab)
        for widget, title in ((self.standings, "🏆 Classement"), (self.matches, "⚽ Matchs"),
                              (self.teams_tab, "👥 Équipes"), (self.transfers, "🔁 Transferts"),
                              (self.scorers, "🥇 Buteurs"), (self.assists, "🎯 Passeurs"),
                              (self.cup_tab, "🏅 Coupe")):
            self.tabs.addTab(widget, title)
        self.setCentralWidget(self.tabs)
        self.refresh_all()

    # ---- simulation
    def advance(self, days):
        """days = nombre de journées à jouer, ou None pour finir toute la ligue."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.league.play_all() if days is None else self.league.play_days(days)
            self.refresh_all()
        finally:
            QApplication.restoreOverrideCursor()
        season = self.league.season
        if season.finished:
            champion = self.league.teams[season.result.final_table[0].team_id]
            self.statusBar().showMessage(f"Saison terminée : champion {champion.name}", 8000)

    def advance_until(self):
        season = self.league.season
        if season.finished:
            return
        day, ok = QInputDialog.getInt(self, "Simuler jusqu'à…", f"Jouer jusqu'à la journée (sur {season.total_days}) :",
                                      min(season.played + 5, season.total_days), season.played + 1, season.total_days)
        if ok:
            self.advance(day - season.played)

    def restart_season(self):
        self.league.start_season()
        self.refresh_all()
        self.statusBar().showMessage("Saison relancée à la journée 0", 5000)

    def rerun_full(self):
        """Après un transfert : on rejoue toute la saison avec les nouveaux effectifs."""
        self.league.start_season()
        self.advance(None)

    def update_status(self):
        season = self.league.season
        self.day_label.setText(f"Journée {season.played} / {season.total_days}"
                               + ("  ✔ terminée" if season.finished else ""))
        for a in (self.next_action, self.until_action, self.all_action):
            a.setEnabled(not season.finished)
        self.setWindowTitle(f"Simulation de ligue ({self.league.n_teams} équipes, {season.total_days} journées)")

    def refresh_all(self):
        self.update_status()
        for tab in self.all_tabs:
            tab.refresh()

    def open_team(self, team_id: int):
        self.teams_tab.select_team(team_id)
        self.tabs.setCurrentWidget(self.teams_tab)

    def new_league(self):
        dlg = NewLeagueDialog(self.league.n_teams, self)
        if not dlg.exec():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.league._create(dlg.seed.value(), dlg.teams.value())
            self.league.start_season()
            self.cup_tab.reset()
            self.refresh_all()
        except ValueError as error:
            QMessageBox.warning(self, "Création impossible", str(error))
        finally:
            QApplication.restoreOverrideCursor()

    def show_model(self):
        box = QMessageBox(self)
        box.setWindowTitle("Modèle de simulation")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(MODEL_EXPLANATION)
        box.exec()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="players.db", help="base générée par generate_player.py")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--teams", type=int, default=20, help="nombre d'équipes (pair, 8 à 32) si une ligue est créée")
    parser.add_argument("--new", action="store_true", help="recrée une nouvelle ligue même si une existe déjà")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if not os.path.exists(args.db):
        QMessageBox.critical(None, "Base introuvable",
                             f"Le fichier {args.db} n'existe pas.\nGénère-le d'abord avec le script de génération.")
        sys.exit(1)
    app.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        league = League.load_or_create(args.db, seed=args.seed, force_new=args.new, n_teams=args.teams)
    finally:
        app.restoreOverrideCursor()
    window = MainWindow(league)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
