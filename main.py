"""
league_app.py : interface PyQt6 de la simulation de ligue.

    pip install PyQt6
    python league_app.py --db players.db

Onglets : Classement | Matchs (détail un par un) | Équipes | Transferts | Buteurs
"""
import argparse
import os
import sys

from PyQt6.QtCore import QRectF, QSize, Qt, QUrl
from PyQt6.QtGui import (QAction, QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen,
                         QPixmap, QTextDocument)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox,
                             QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
                             QToolBar, QVBoxLayout, QWidget)

from league_engine import (BASE_GOALS, FORMATION, K, MODEL_EXPLANATION, ROLE_LABELS, ROLES, STATS,
                           League, Player, Team)

GREEN, RED, GREY = "#2e9e4f", "#d64545", "#8a8a8a"


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
class StandingsTab(QWidget):
    HEADERS = ["#", "Évol.", "Équipe", "Général", "J", "G", "N", "P", "BP", "BC", "Diff", "Pts", "Δ Pts", "Forme"]

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("<b>Classement après la journée :</b>"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 38)
        self.spin.valueChanged.connect(self.render)
        prev_btn, next_btn, last_btn = QPushButton("◀"), QPushButton("▶"), QPushButton("Dernière journée")
        prev_btn.clicked.connect(lambda: self.spin.setValue(self.spin.value() - 1))
        next_btn.clicked.connect(lambda: self.spin.setValue(self.spin.value() + 1))
        last_btn.clicked.connect(lambda: self.spin.setValue(self.spin.maximum()))
        for w in (prev_btn, self.spin, next_btn, last_btn):
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
        layout.addWidget(QLabel(
            "<small>Vert = Top 4 (or pour le leader) | Rouge = 3 dernières places | "
            "Évol. et Δ Pts = comparaison avec la simulation précédente (utile après un transfert) | "
            "Double-clic sur une équipe pour voir son effectif.</small>"))

    def refresh(self):
        result = self.win.league.result
        last = len(result.tables)
        self.spin.blockSignals(True)
        self.spin.setRange(1, last)
        self.spin.setValue(last)
        self.spin.blockSignals(False)
        self.render()

    def render(self):
        league = self.win.league
        result = league.result
        md = self.spin.value()
        rows = result.tables[md - 1]
        previous = None
        if league.previous is not None and md == len(result.tables):
            previous = {r.team_id: r for r in league.previous.final_table}
        self.compare_label.setText("<i>Comparé à la simulation précédente</i>" if previous else "")

        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            team:Team = league.teams[r.team_id]
            bg = (255, 215, 0, 80) if i == 0 else (60, 179, 113, 55) if i < 4 else \
                 (220, 20, 60, 50) if i >= len(rows) - 3 else None

            evol, dpts, evol_color, dpts_color = "–", "–", GREY, GREY
            if previous:
                dr = previous[r.team_id].rank - r.rank
                dp = r.pts - previous[r.team_id].pts
                evol = f"▲ {dr}" if dr > 0 else f"▼ {-dr}" if dr < 0 else "="
                evol_color = GREEN if dr > 0 else RED if dr < 0 else GREY
                dpts = f"{dp:+d}"
                dpts_color = GREEN if dp > 0 else RED if dp < 0 else GREY

            values = [r.rank, evol, None, team.overall_rating, r.played, r.won, r.drawn, r.lost, r.gf, r.ga, f"{r.gd:+d}", r.pts, dpts]
            for col, value in enumerate(values):
                if col == 2:
                    item = cell(team.name, "left", bold=True, icon=logo_icon(team), bg=bg)
                    item.setData(Qt.ItemDataRole.UserRole, team.id)
                elif col == 1:
                    item = cell(value, bold=True, color=evol_color, bg=bg)
                elif col == 11:
                    item = cell(value, bold=True, color=dpts_color, bg=bg)
                else:
                    item = cell(value, bold=col in (0, 10), bg=bg)
                self.table.setItem(i, col, item)

            dots = "".join(f"<span style='color:{GREEN if f == 'V' else GREY if f == 'N' else RED}'>●</span> "
                           for f in r.form)
            label = QLabel(dots)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background: transparent; font-size: 14px;")
            self.table.setCellWidget(i, 13, label)
        for col, width in {0: 36, 1: 56, 3: 36, 4: 36, 5: 36, 6: 36, 7: 44, 8: 44, 9: 50, 10: 50, 11: 56, 12: 110}.items():
            self.table.setColumnWidth(col, width)

    def on_double_click(self, row, _col):
        team_id = self.table.item(row, 2).data(Qt.ItemDataRole.UserRole)
        self.win.open_team(team_id)


# =============================================================================
# 5. ONGLET MATCHS
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

        self.table = QTableWidget()
        setup_table(self.table, ["J", "Domicile", "Score", "Extérieur", "xG dom.", "xG ext."], 38)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)

        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)

        splitter.addWidget(left)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setSizes([180, 560, 520])

    def refresh(self):
        league, result = self.win.league, self.win.league.result
        for team in league.teams.values():
            self.detail.document().addResource(QTextDocument.ResourceType.ImageResource,
                                               QUrl(f"logo:{team.id}"), make_logo(team, 64).toImage())
        self.team_filter.blockSignals(True)
        self.day_list.blockSignals(True)
        current_team = self.team_filter.currentData()
        current_day = max(0, self.day_list.currentRow())
        self.team_filter.clear()
        self.team_filter.addItem("Toutes les équipes", None)
        for team in sorted(league.teams.values(), key=lambda t: t.name):
            self.team_filter.addItem(logo_icon(team), team.name, team.id)
        index = self.team_filter.findData(current_team)
        self.team_filter.setCurrentIndex(max(0, index))
        self.day_list.clear()
        for md in range(1, len(result.matchdays) + 1):
            self.day_list.addItem(f"Journée {md}")
        self.day_list.setCurrentRow(min(current_day, len(result.matchdays) - 1))
        self.team_filter.blockSignals(False)
        self.day_list.blockSignals(False)
        self.render_table()

    def render_table(self, *_):
        league, result = self.win.league, self.win.league.result
        team_id = self.team_filter.currentData()
        self.day_list.setEnabled(team_id is None)
        if team_id is None:
            md = max(0, self.day_list.currentRow())
            self.rows = list(result.matchdays[md])
        else:
            self.rows = result.matches_of(team_id)

        self.table.setRowCount(len(self.rows))
        for i, m in enumerate(self.rows):
            home, away = league.teams[m.home_id], league.teams[m.away_id]
            hw, aw = m.home_goals > m.away_goals, m.away_goals > m.home_goals
            self.table.setItem(i, 0, cell(m.matchday, color=GREY))
            self.table.setItem(i, 1, cell(home.name, "left", bold=hw, icon=logo_icon(home)))
            self.table.setItem(i, 2, cell(f"{m.home_goals} - {m.away_goals}", bold=True, size=12))
            self.table.setItem(i, 3, cell(away.name, "left", bold=aw, icon=logo_icon(away)))
            self.table.setItem(i, 4, cell(f"{m.home.xg:.2f}", color=GREY))
            self.table.setItem(i, 5, cell(f"{m.away.xg:.2f}", color=GREY))
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 60)
        if self.rows:
            self.table.selectRow(0)
        else:
            self.detail.clear()

    # ---------------------------------------------------------------- détail
    def show_detail(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return
        m = self.rows[selected[0].row()]
        league = self.win.league
        home, away = league.teams[m.home_id], league.teams[m.away_id]

        def mood_text(side):
            parts = ", ".join(f"{d:+d}" for d in side.last3) or "aucun match"
            return f"{parts} &rarr; x{side.mood_factor:.3f}"

        def analysis_rows(side):
            return [
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

        html = [f"""
        <table width='100%' cellpadding='4'><tr>
          <td align='center'><img src='logo:{home.id}' width='56'><br><b>{home.name}</b></td>
          <td align='center'><span style='font-size:30px'><b>{m.home_goals} - {m.away_goals}</b></span>
              <br><span style='color:{GREY}'>Journée {m.matchday}</span></td>
          <td align='center'><img src='logo:{away.id}' width='56'><br><b>{away.name}</b></td>
        </tr></table><hr>"""]

        html.append("<b>Buts</b><br>")
        if m.goals:
            for e in m.goals:
                side = "◀" if e.team_id == m.home_id else "▶"
                team = home if e.team_id == m.home_id else away
                html.append(f"{e.minute}' &nbsp; {side} <b>{e.player_name}</b> "
                            f"<span style='color:{GREY}'>({team.short})</span><br>")
        else:
            html.append("<i>0 - 0, aucun but</i><br>")

        html.append("<hr><b>Analyse du score</b>")
        html.append("<table width='100%' cellpadding='3' border='0'>"
                    f"<tr><td></td><td align='center'><b>{home.short}</b></td><td align='center'><b>{away.short}</b></td></tr>")
        for (label, hv), (_, av) in zip(analysis_rows(m.home), analysis_rows(m.away)):
            html.append(f"<tr><td>{label}</td><td align='center'>{hv}</td><td align='center'>{av}</td></tr>")
        html.append("</table>")
        html.append(f"<small style='color:{GREY}'>xG = {BASE_GOALS} x (att/déf adverse)^{K} x forme x lieu / "
                    f"racine(forme adverse). Buts = arrondi de xG + reste des matchs précédents.</small>")

        html.append("<hr><b>Compositions (4-4-2)</b><table width='100%' cellpadding='2'><tr>")
        for side in (m.home, m.away):
            html.append("<td valign='top'>")
            for name, role, rating in side.lineup:
                html.append(f"<span style='color:{GREY}'>{ROLE_LABELS[role]}</span> {name} "
                            f"<small>({rating:.0f})</small><br>")
            html.append("</td>")
        html.append("</tr></table>")
        self.detail.setHtml("".join(html))


# =============================================================================
# 6. ONGLET ÉQUIPES
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
        row = next(r for r in result.final_table if r.team_id == team.id)
        profile = result.profiles[team.id]
        captain = team.captain
        self.info.setText(
            f"<h2>{team.name}</h2>"
            f"<b>Entraîneur</b> : {team.coach.name} (tactique {team.coach.tactics}, motivation {team.coach.motivation})<br>"
            f"<b>Capitaine</b> : {captain.name if captain else '-'} (leadership {captain.stats['leadership'] if captain else '-'})<br>"
            f"<b>Niveau</b> : attaque {profile.attack:.1f} | défense {profile.defense:.1f}<br>"
            f"<b>Saison</b> : {row.rank}e, {row.pts} pts ({row.won}V {row.drawn}N {row.lost}D, diff. {row.gd:+d})")

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
# 7. ONGLET TRANSFERTS
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
        self.auto_sim = QCheckBox("Relancer la simulation après le transfert")
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
        try:
            text = league.swap(self.team_combo.currentData(), out_p, in_p, self.source_combo.currentData())
        except ValueError as error:
            QMessageBox.warning(self, "Transfert impossible", str(error))
            self.search()
            return
        self.win.statusBar().showMessage("Transfert effectué : " + text, 8000)
        if self.auto_sim.isChecked():
            self.win.run_simulation()
        else:
            self.win.refresh_all()


# =============================================================================
# 8. ONGLET BUTEURS
# =============================================================================
class ScorersTab(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        setup_table(self.table, ["#", "Joueur", "Équipe", "Buts"], 34)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def refresh(self):
        league = self.win.league
        top = league.result.top_scorers(30)
        self.table.setRowCount(len(top))
        for i, (_pid, (name, team_id, goals)) in enumerate(top):
            team = league.teams[team_id]
            self.table.setItem(i, 0, cell(i + 1, bold=True))
            self.table.setItem(i, 1, cell(name, "left", bold=True))
            self.table.setItem(i, 2, cell(team.name, "left", icon=logo_icon(team)))
            self.table.setItem(i, 3, cell(goals, bold=True))
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(3, 70)


# =============================================================================
# 9. FENÊTRE PRINCIPALE
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self, league: League):
        super().__init__()
        self.league = league
        self.setWindowTitle("Simulation de ligue (20 équipes, 38 journées)")
        self.resize(1280, 800)

        toolbar = QToolBar("Actions")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)
        sim_action = QAction("▶  Simuler la saison", self)
        sim_action.triggered.connect(self.run_simulation)
        new_action = QAction("🔄  Nouvelle ligue…", self)
        new_action.triggered.connect(self.new_league)
        help_action = QAction("ℹ  Comment sont calculés les scores", self)
        help_action.triggered.connect(self.show_model)
        for a in (sim_action, new_action, help_action):
            toolbar.addAction(a)

        self.tabs = QTabWidget()
        self.standings = StandingsTab(self)
        self.matches = MatchesTab(self)
        self.teams_tab = TeamsTab(self)
        self.transfers = TransfersTab(self)
        self.scorers = ScorersTab(self)
        for widget, title in ((self.standings, "🏆 Classement"), (self.matches, "⚽ Matchs"),
                              (self.teams_tab, "👥 Équipes"), (self.transfers, "🔁 Transferts"),
                              (self.scorers, "🥇 Buteurs")):
            self.tabs.addTab(widget, title)
        self.setCentralWidget(self.tabs)
        self.run_simulation()

    def run_simulation(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.league.simulate()
            self.refresh_all()
        finally:
            QApplication.restoreOverrideCursor()
        champion = self.league.teams[self.league.result.final_table[0].team_id]
        self.statusBar().showMessage(f"Simulation terminée : champion {champion.name}", 8000)

    def refresh_all(self):
        for tab in (self.standings, self.matches, self.teams_tab, self.transfers, self.scorers):
            tab.refresh()

    def open_team(self, team_id: int):
        self.teams_tab.select_team(team_id)
        self.tabs.setCurrentWidget(self.teams_tab)

    def new_league(self):
        seed, ok = QInputDialog.getInt(self, "Nouvelle ligue", "Graine (seed) de la nouvelle ligue :", 42, 0, 10**9)
        if not ok:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.league._create(seed)
        finally:
            QApplication.restoreOverrideCursor()
        self.run_simulation()

    def show_model(self):
        box = QMessageBox(self)
        box.setWindowTitle("Modèle de simulation")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(MODEL_EXPLANATION)
        box.exec()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="players.db", help="base générée par generate_players_db.py / main.py")
    parser.add_argument("--seed", type=int, default=42)
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
        league = League.load_or_create(args.db, seed=args.seed, force_new=args.new)
    finally:
        app.restoreOverrideCursor()
    window = MainWindow(league)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
