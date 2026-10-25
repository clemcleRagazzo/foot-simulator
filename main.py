"""
league_app.py : interface PyQt6 de la simulation de ligue.

    pip install PyQt6
    python league_app.py --db players.db

Onglets : Classement | Matchs (+ formations) | Équipes | Transferts | Buteurs | Passeurs | Coupe
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import Counter

from PyQt6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (QAction, QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath,
                         QPalette, QPen, QPixmap, QTextDocument)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QGridLayout, QGroupBox, QMenu, QToolButton, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox,
                             QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
                             QToolBar, QVBoxLayout, QWidget)

from cup_engine import Cup, GroupCup, describe_groups, describe_structure, next_power_of_two
from exports import export_all, write_csv
from finance import coach_salary, fmt_money, player_salary, player_value, transfer_fee, wage_bill
from fake import Faker
from PyQt6.QtWidgets import QFileDialog, QSlider, QStyledItemDelegate
from ui_extras import RadarWidget, face_pixmap, flag_icon, flag_pixmap, fun_facts
from league_engine import (OPTIONS, BASE_GOALS, DEFAULT_COUNTRIES, FORMATIONS, K, MAX_COUNTRIES, MAX_DIVISIONS, MAX_TEAMS,
                           MIN_TEAMS, MODEL_EXPLANATION, ROLE_LABELS, ROLES, STATS, League, Player, Team, World,
                           league_zones)

GREEN, RED, GREY = "#2e9e4f", "#d64545", "#8a8a8a"
BLUE, ORANGE = "#2f6fd6", "#f08a24"
ZONE_BG = {"blue": (47, 111, 214, 70), "orange": (240, 138, 36, 85), "red": (220, 20, 60, 65),
           "green": (46, 158, 79, 70)}
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
# 2. OUTILS TABLEAUX (tri sur toutes les colonnes)
# =============================================================================
SORT_ROLE = Qt.ItemDataRole.UserRole + 7        # clé de tri d'une cellule
FORM_ROLE = Qt.ItemDataRole.UserRole + 8        # liste « V N D » dessinée par FormDelegate
_LEADING = re.compile(r"^[^\w+\-]+")
_NUMBER = re.compile(r"^([+\-]?\d+(?:[.,]\d+)?)")


def sort_key(value) -> tuple:
    """Clé de tri alphanumérique : les nombres se trient comme des nombres (« 9 » avant « 10 », « 3e » avant « 12e »),
    le reste par ordre alphabétique sans tenir compte des accents ni de la casse."""
    if isinstance(value, (int, float)):
        return (0, float(value))
    text = _LEADING.sub("", str(value).replace("\u202f", "").strip())
    compact = text.replace(" ", "")
    m = _NUMBER.match(compact)
    if m and len(compact) - len(m.group(1)) <= 2:
        return (0, float(m.group(1).replace(",", ".")))
    folded = unicodedata.normalize("NFKD", text.casefold())
    return (1, "".join(ch for ch in folded if not unicodedata.combining(ch)))


class SortItem(QTableWidgetItem):
    def __lt__(self, other):
        a, b = self.data(SORT_ROLE), other.data(SORT_ROLE)
        return a < b if a is not None and b is not None else super().__lt__(other)


class SortHeader(QHeaderView):
    """En-tête cliquable : un clic trie par cette colonne (croissant, puis décroissant). Il n'active pas la sélection
    de colonne de Qt, donc la ligne sélectionnée ne change pas."""
    sortRequested = pyqtSignal(int)

    def __init__(self, parent):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._press = None

    def mousePressEvent(self, event):
        self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pos = event.position().toPoint()
        moved = self._press is None or (pos - self._press).manhattanLength() > 4      # redimensionnement = pas un tri
        index = self.logicalIndexAt(pos)
        super().mouseReleaseEvent(event)
        if not moved and index >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self.sortRequested.emit(index)


class SortTable(QTableWidget):
    """Tableau triable par n'importe quelle colonne. Le tri choisi est conservé quand le tableau est rempli à nouveau."""

    def __init__(self):
        super().__init__()
        self._sort = None
        header = SortHeader(self)
        header.setSectionsClickable(False)
        header.sortRequested.connect(self._header_clicked)
        self.setHorizontalHeader(header)

    def _header_clicked(self, col: int) -> None:
        ascending = not (self._sort and self._sort[0] == col and self._sort[1] == Qt.SortOrder.AscendingOrder)
        self._sort = (col, Qt.SortOrder.AscendingOrder if ascending else Qt.SortOrder.DescendingOrder)
        self.apply_sort()

    def apply_sort(self) -> None:
        if self._sort is None or self.rowCount() == 0 or self._sort[0] >= self.columnCount():
            return
        col, order = self._sort
        self.horizontalHeader().setSortIndicatorShown(True)
        self.horizontalHeader().setSortIndicator(col, order)
        self.sortItems(col, order)

    def setRowCount(self, rows: int) -> None:
        super().setRowCount(rows)
        QTimer.singleShot(0, self.apply_sort)           # après le remplissage : on remet le tri de l'utilisateur

    # ---- export : lignes affichées, dans l'ordre affiché (tri et filtres compris)
    def table_rows(self) -> tuple:
        headers = [self.horizontalHeaderItem(c).text() if self.horizontalHeaderItem(c) else ""
                   for c in range(self.columnCount())]
        rows = []
        for r in range(self.rowCount()):
            if self.isRowHidden(r):
                continue
            row = []
            for c in range(self.columnCount()):
                item = self.item(r, c)
                text = item.text() if item is not None else ""
                if item is not None and not text:
                    if item.data(FORM_ROLE):                 # forme récente : V / N / D
                        text = "".join(item.data(FORM_ROLE))
                    elif item.data(Qt.ItemDataRole.CheckStateRole) is not None:    # case à cocher
                        text = "oui" if item.checkState() == Qt.CheckState.Checked else "non"
                    elif item.toolTip():                    # cellule drapeau : le nom du pays
                        text = item.toolTip()
                row.append(text)
            rows.append(row)
        return headers, rows

    def export_dialog(self, parent=None) -> None:
        headers, rows = self.table_rows()
        path, _ = QFileDialog.getSaveFileName(parent or self, "Exporter le tableau en CSV", "tableau.csv",
                                              "Fichier CSV (*.csv)")
        if path:
            write_csv(path, headers, rows)
            QMessageBox.information(parent or self, "Export terminé", f"{len(rows)} ligne(s) exportée(s) dans :\n{path}")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("📤  Exporter ce tableau en CSV…", self.export_dialog)
        menu.addAction("📋  Copier le tableau (collable dans Excel)", self.copy_table)
        menu.exec(event.globalPos())

    def copy_table(self) -> None:
        headers, rows = self.table_rows()
        QApplication.clipboard().setText("\n".join("\t".join(r) for r in [headers] + rows))


class FormDelegate(QStyledItemDelegate):
    """Dessine les 5 derniers résultats (● vert / gris / rouge) à partir de la liste stockée dans la cellule."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        form = index.data(FORM_ROLE) or []
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = 15
        x = option.rect.center().x() - step * (len(form) - 1) / 2
        for f in form:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(GREEN if f == "V" else GREY if f == "N" else RED))
            painter.drawEllipse(QPointF(x, option.rect.center().y()), 5, 5)
            x += step
        painter.restore()


def cell(text="", align="center", bold=False, color=None, bg=None, icon=None, size=None, sort=None) -> QTableWidgetItem:
    item = SortItem(str(text))
    item.setData(SORT_ROLE, sort if sort is not None else sort_key(text))
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
    table.setAlternatingRowColors(False)
    palette = table.palette()                                   # sélection translucide : ne masque pas les couleurs
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 45))
    palette.setColor(QPalette.ColorRole.HighlightedText, palette.color(QPalette.ColorRole.Text))
    table.setPalette(palette)
    table.setIconSize(QSize(28, 28))
    table.setShowGrid(False)
    table.horizontalHeader().setHighlightSections(False)


def flag_cell(country: str, bg=None) -> QTableWidgetItem:
    """Cellule avec le drapeau du pays (le nom du pays est dans l'info-bulle)."""
    item = cell("", icon=flag_icon(country, 28), bg=bg, sort=(1, country.casefold()))
    item.setToolTip(country)
    return item


def role_text(player: Player) -> str:
    return ROLE_LABELS[player.best_position]


def fill_players_table(table: QTableWidget, players: list, captain_id=None) -> None:
    """Colonnes : Joueur, Poste, Âge, Pays, Note, GB, DEF, MIL, ATT."""
    table.setRowCount(len(players))
    for row, p in enumerate(players):
        name = p.name + ("  ©" if p.id == captain_id else "")
        first = cell(name, "left", bold=p.id == captain_id)
        first.setData(Qt.ItemDataRole.UserRole, row)               # index dans la liste (le tri change l'ordre visuel)
        table.setItem(row, 0, first)
        table.setItem(row, 1, cell(role_text(p), bold=True))
        table.setItem(row, 2, cell(p.age))
        table.setItem(row, 3, flag_cell(p.country))
        table.setItem(row, 4, cell(f"{p.overall:.0f}", bold=True))
        for col, role in enumerate(ROLES, start=5):
            value = p.ovr[role]
            color = GREEN if value >= 75 else GREY if value < 45 else None
            table.setItem(row, col, cell(f"{value:.0f}", color=color))


PLAYER_HEADERS = ["Joueur", "Poste", "Âge", "Pays", "Note", "GB", "DEF", "MIL", "ATT"]


def make_player_table() -> QTableWidget:
    t = SortTable()
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
    """Fiche joueur : visage, numéro, surnom (gagné), radar des postes, stats, saison en cours, CV et petites anecdotes."""

    def __init__(self, player: Player, world: World, parent=None):
        super().__init__(parent)
        self.setWindowTitle(player.name)
        ledger = world.ledger
        team = next((t for t in world.teams.values() if any(p.id == player.id for p in t.players)), None)
        root = QVBoxLayout(self)

        head = QHBoxLayout()
        face = QLabel()
        face.setPixmap(face_pixmap(player, 150))
        face.setFixedSize(150, 150)
        head.addWidget(face)

        info = QVBoxLayout()
        number = f"#{player.number}  " if player.number else ""
        title = f"<h2 style='margin:0'>{number}{player.name}</h2>"
        if player.nickname:
            title += f"<div style='color:#b8860b'><i>« {player.nickname} »</i></div>"
        info.addWidget(QLabel(title))
        club = QHBoxLayout()
        if team:
            logo = QLabel()
            logo.setPixmap(make_logo(team, 22))
            club.addWidget(logo)
            club.addWidget(QLabel(f"<b>{team.name}</b> · {ROLE_LABELS[player.best_position]} · {player.age} ans"))
        club.addStretch()
        info.addLayout(club)
        origin = QHBoxLayout()
        flag = QLabel()
        flag.setPixmap(flag_pixmap(player.country, 28))
        flag.setToolTip(player.country)
        origin.addWidget(flag)
        origin.addWidget(QLabel(f"{player.city} · pied {player.preferred_foot} · potentiel {player.potential}"))
        origin.addStretch()
        info.addLayout(origin)
        status = ledger.status_of(player)
        res = player.injury_resistance
        info.addWidget(QLabel(
            f"Résistance aux blessures : <b>{res}</b> ({'solide' if res >= 70 else 'fragile' if res < 45 else 'normale'})"
            f" · Violence : <b>{player.foul_index:.0f}</b><br>"
            + (f"<span style='color:{RED}'><b>{status}</b></span>" if status else "<span style='color:%s'>Disponible</span>" % GREEN)))
        info.addWidget(QLabel(f"💶 Salaire <b>{fmt_money(player_salary(player))}</b>/an · Valeur marchande "
                              f"<b>{fmt_money(player_value(player))}</b> <span style='color:{GREY}'>(indicatif)</span>"))
        info.addStretch()
        head.addLayout(info, 1)
        head.addWidget(RadarWidget(player.ovr))
        root.addLayout(head)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # --- stats détaillées (2 colonnes)
        stats_page = QWidget()
        grid = QGridLayout(stats_page)
        for i, stat in enumerate(STATS):
            v = player.stats[stat]
            bar = QProgressBar()
            bar.setRange(0, 99)
            bar.setValue(v)
            bar.setFormat("%v")
            color = GREEN if v >= 75 else "#e0a030" if v >= 50 else RED
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")
            grid.addWidget(QLabel(STAT_LABELS[stat]), i % 10, (i // 10) * 2)
            grid.addWidget(bar, i % 10, (i // 10) * 2 + 1)
        tabs.addTab(stats_page, "📊 Stats")

        # --- CV : saison en cours, parcours, fiche perso
        cv_page = QWidget()
        cv = QVBoxLayout(cv_page)
        st = ledger.stats.get(player.id, {})
        cv.addWidget(QLabel(
            f"<b>Saison en cours</b> : {st.get('games', 0)} matchs · ⚽ {st.get('goals', 0)} buts · "
            f"👟 {st.get('assists', 0)} passes · 🟨 {st.get('yellow', 0)} · 🟥 {st.get('red', 0)} · "
            f"🩹 {st.get('injuries', 0)} blessure(s)"))
        rows = world.player_career(player.id)
        table = SortTable()
        setup_table(table, ["Saison", "Club", "Pays", "Div.", "J", "Buts", "Passes", "🟨", "🟥", "🩹"], 26)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setRowCount(len(rows) + (1 if rows else 0))
        totals = [0] * 6
        for i, (season, club_name, country, division, games, goals, assists, yellow, red, inj) in enumerate(rows):
            table.setItem(i, 0, cell(season))
            table.setItem(i, 1, cell(club_name, "left"))
            table.setItem(i, 2, flag_cell(country))
            table.setItem(i, 3, cell(division))
            for col, v in enumerate((games, goals, assists, yellow, red, inj), start=4):
                table.setItem(i, col, cell(v))
            totals = [a + b for a, b in zip(totals, (games, goals, assists, yellow, red, inj))]
        if rows:
            n = len(rows)
            table.setItem(n, 1, cell("Total carrière", "left", bold=True))
            for col, v in enumerate(totals, start=4):
                table.setItem(n, col, cell(v, bold=True))
        for col, width in ((0, 56), (2, 46), (3, 40)):
            table.setColumnWidth(col, width)
        for col in range(4, 10):
            table.setColumnWidth(col, 48)
        if not rows:
            cv.addWidget(QLabel(f"<i style='color:{GREY}'>Aucune saison terminée pour le moment : le CV se remplit "
                                f"à chaque « Saison suivante ».</i>"))
        else:
            cv.addWidget(table, 1)
        perso = QFormLayout()
        for key, value in fun_facts(player).items():
            label = QLabel(value)
            label.setWordWrap(True)
            perso.addRow(f"<b>{key}</b>", label)
        box = QGroupBox("Fiche perso")
        box.setLayout(perso)
        cv.addWidget(box)
        tabs.addTab(cv_page, "📄 CV")
        self.resize(620, 700)


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
        self.comp_label = QLabel()
        self.comp_label.setStyleSheet("font-size: 15px; padding-right: 14px;")
        top.addWidget(self.comp_label)
        top.addWidget(QLabel("Classement après la journée :"))
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

        self.table = SortTable()
        setup_table(self.table, self.HEADERS, 36)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(self.on_double_click)
        self.table.setItemDelegateForColumn(13, FormDelegate(self.table))
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
        zc = league.zone_counts()
        previous = None
        if league.previous is not None and finished:
            previous = {r.team_id: r for r in league.previous.final_table}
        self.compare_label.setText("<i>Comparé à la saison précédente</i>" if previous else "")
        legend = []
        if zc["blue"]:
            legend.append(f"<span style='color:{BLUE}'>■</span> Bleu = coupe interligue 1 ({zc['blue']} premiers)")
            legend.append(f"<span style='color:{ORANGE}'>■</span> Orange = coupe interligue 2 ({zc['orange']} suivants)")
        if zc["green"]:
            legend.append(f"<span style='color:{GREEN}'>■</span> Vert = promus en division {league.division - 1} "
                          f"({zc['green']} premiers)")
        if zc["red"]:
            where = f" en division {league.division + 1}" if league.n_divisions > 1 else ""
            legend.append(f"<span style='color:{RED}'>■</span> Rouge = relégués{where} ({zc['red']} derniers)")
        self.comp_label.setText(f"<b>{league.label}</b>")
        self.legend.setText("<small>" + " | ".join(legend) + " &nbsp;—&nbsp; les couleurs apparaissent à la fin de la "
                            "saison. 🥇🥈🥉 = podium. Évol. et Δ Pts = comparaison avec la saison précédente. "
                            "Double-clic sur une équipe pour voir son effectif. Clique sur un en-tête de colonne pour trier.</small>")

        self.table.setRowCount(0)                      # supprime aussi les anciens widgets « Forme »
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            team: Team = league.teams[r.team_id]
            bg = None
            if finished:
                if i < zc["blue"]:
                    bg = ZONE_BG["blue"]
                elif i < zc["blue"] + zc["orange"]:
                    bg = ZONE_BG["orange"]
                elif i < zc["green"]:
                    bg = ZONE_BG["green"]
                elif zc["red"] and i >= len(rows) - zc["red"]:
                    bg = ZONE_BG["red"]

            evol, dpts, evol_color, dpts_color = "–", "–", GREY, GREY
            if previous and r.team_id in previous:
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

            form_item = cell("", bg=bg, sort=(0, float(sum(3 if f == "V" else 1 if f == "N" else 0 for f in r.form))))
            form_item.setData(FORM_ROLE, list(r.form))
            self.table.setItem(i, 13, form_item)
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


def draw_pitch(p: QPainter, field: QRectF) -> None:
    """Pelouse rayée + lignes du terrain."""
    fw, fh = field.width(), field.height()
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


def colors_clash(a: str, b: str) -> bool:
    ca, cb = QColor(a), QColor(b)
    return (abs(ca.red() - cb.red()) + abs(ca.green() - cb.green()) + abs(ca.blue() - cb.blue())) < 150


def draw_lineup(p: QPainter, field: QRectF, formation: str, items_by_role: dict, team: Team, is_home: bool,
                captain_name: str | None = None, badges: dict | None = None, alt_kit: bool = False) -> None:
    """Dessine un onze dans sa formation. items_by_role[rôle] = [(nom, texte dans le rond)] ;
    badges[nom] = ["⚽", "👟×2", "🟨", ...] affichés à droite du joueur."""
    badges = badges or {}
    fw, fh = field.width(), field.height()
    rows = FORMATIONS[formation]
    used = {role: 0 for role in items_by_role}
    n_rows = len(rows)
    radius = max(11.0, min(17.0, fw * 0.045))
    fill, edge = (QColor(team.secondary), QColor(team.primary)) if alt_kit else (QColor(team.primary), QColor(team.secondary))
    text_color = QColor("#111") if fill.lightness() > 150 else QColor("white")
    for i, (role, count) in enumerate(rows):
        items = center_order(items_by_role[role][used[role]:used[role] + count])
        used[role] += count
        f = 0.12 if i == 0 else 0.30 + (0.84 - 0.30) * (i - 1) / (n_rows - 2)
        y = field.bottom() - f * fh / 2 if is_home else field.top() + f * fh / 2
        for k, (name, label) in enumerate(items):
            x = field.left() + fw * (k + 1) / (len(items) + 1)
            body, body_edge, body_text = (QColor("#f4c20d"), QColor("#7a5c00"), QColor("#111")) \
                if role == "gk" else (fill, edge, text_color)
            p.setBrush(body)
            p.setPen(QPen(body_edge, 2))
            p.drawEllipse(QPointF(x, y), radius, radius)
            f1 = QFont()
            f1.setBold(True)
            f1.setPixelSize(int(radius * (0.95 if len(label) < 3 else 0.8)))
            p.setFont(f1)
            p.setPen(body_text)
            p.drawText(QRectF(x - radius, y - radius, 2 * radius, 2 * radius), Qt.AlignmentFlag.AlignCenter, label)
            f2 = QFont()
            f2.setBold(True)
            f2.setPixelSize(11)
            p.setFont(f2)
            box = QRectF(x - 48, y + radius + 1, 96, 14)
            p.setPen(QColor(0, 0, 0, 170))
            p.drawText(box.translated(1, 1), Qt.AlignmentFlag.AlignCenter, short_name(name))
            p.setPen(QColor("white"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, short_name(name))
            if name == captain_name:                           # brassard de capitaine
                p.setBrush(QColor("#ffd400"))
                p.setPen(QPen(QColor("#222"), 1.5))
                p.drawRoundedRect(QRectF(x - radius - 16, y - 7, 14, 14), 3, 3)
                cap_font = QFont()
                cap_font.setBold(True)
                cap_font.setPixelSize(10)
                p.setFont(cap_font)
                p.setPen(QColor("#222"))
                p.drawText(QRectF(x - radius - 16, y - 7, 14, 14), Qt.AlignmentFlag.AlignCenter, "C")
            if badges.get(name):
                badge_font = QFont()
                badge_font.setPixelSize(11)
                p.setFont(badge_font)
                p.setPen(QColor("white"))
                for idx, text in enumerate(badges[name][:4]):
                    p.drawText(QRectF(x + radius + 1, y - radius * 1.3 + idx * 12, 40, 13),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


def match_badges(m, team_id: int) -> dict:
    """{nom: ["⚽", "👟×2", "🟨", "🟥", "🩹"]} pour une équipe d'après les événements du match."""
    raw: dict = {}

    def add(name, icon):
        counts = raw.setdefault(name, {})
        counts[icon] = counts.get(icon, 0) + 1

    for e in m.goals:
        if e.team_id == team_id:
            add(e.player_name, "⚽")
        if e.assist_name and e.team_id == team_id:
            add(e.assist_name, "👟")
    for c in m.cards:
        if c.team_id == team_id:
            add(c.player_name, "🟨" if c.kind == "yellow" else "🟥")
    for i in m.injuries:
        if i.team_id == team_id:
            add(i.player_name, "🩹")
    return {name: [icon + (f"×{n}" if n > 1 else "") for icon, n in counts.items()] for name, counts in raw.items()}


class PitchWidget(QWidget):
    """Terrain vertical : l'équipe à domicile en bas, l'extérieur en haut, chacune dans sa formation.
    Dans le rond : la note du joueur. Pastilles : ⚽ but, 👟 passe décisive, 🟨 🟥 cartons, 🩹 blessure."""

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
        fw = field.width()
        draw_pitch(p, field)
        mid = field.center().y()

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
        small = QFont()
        small.setBold(True)
        small.setPixelSize(12)
        p.setFont(small)
        if self.pens:
            p.drawText(QRectF(field.left(), mid + 18, fw, 16), Qt.AlignmentFlag.AlignCenter,
                       f"t.a.b. {self.pens[0]} - {self.pens[1]}")

        for team, side, is_home in ((self.home, m.home, True), (self.away, m.away, False)):
            by_role = {}
            for name, role, rating in side.lineup:
                by_role.setdefault(role, []).append((name, f"{rating:.0f}"))
            alt = (not is_home) and colors_clash(self.home.primary, self.away.primary)   # maillot extérieur
            draw_lineup(p, field, side.formation, by_role, team, is_home, side.captain_name,
                        match_badges(m, team.id), alt)

        head = QFont()
        head.setBold(True)
        head.setPixelSize(13)
        p.setFont(head)
        p.setPen(self.palette().color(self.foregroundRole()))
        for team, side, y in ((self.away, m.away, 4), (self.home, m.home, H - top + 4)):
            p.drawPixmap(12, int(y), make_logo(team, 24))
            p.drawText(QRectF(42, y, W - 52, 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"{team.name}   ·   {side.formation}")
        if m.attendance:                                   # affluence : en bas à droite, sans gêner les joueurs
            p.drawText(QRectF(W - 190, H - top + 4, 178, 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       f"👥 {m.attendance:,} / {m.capacity:,}".replace(",", " "))


class TeamPitchWidget(QWidget):
    """Demi-terrain avec le onze type d'une équipe, numéros de maillot dans les ronds."""

    def __init__(self):
        super().__init__()
        self.team = None
        self.status: dict = {}
        self.setMinimumSize(420, 360)

    def set_team(self, team: Team, ledger) -> None:
        self.team = team
        self.status = {p.name: [s.split()[0]] for p in team.players if (s := ledger.status_of(p))} if ledger else {}
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        if self.team is None:
            return
        field = QRectF(10, -(H - 16), W - 20, 2 * (H - 16))        # on ne voit que la moitié basse
        p.setClipRect(QRectF(0, 0, W, H))
        draw_pitch(p, field)
        by_role = {}
        for player, role in self.team.best_xi(self.team.formation):
            by_role.setdefault(role, []).append((player.name, str(player.number or "")))
        captain = self.team.captain
        draw_lineup(p, field, self.team.formation, by_role, self.team, True, captain.name if captain else None,
                    self.status)
        head = QFont()
        head.setBold(True)
        head.setPixelSize(14)
        p.setFont(head)
        p.setPen(QColor("white"))
        p.drawText(QRectF(14, 8, W - 28, 20), Qt.AlignmentFlag.AlignLeft, f"Formation {self.team.formation}")


class MatchDetailView(QTabWidget):
    """Deux onglets : 🎽 Formations (terrain) et 📋 Résumé (événements, analyse, compositions)."""

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

    def show_match(self, league, m, pens=None, round_label=None):
        """league : n'importe quel objet qui a .teams (un championnat ou le monde)."""
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
                ("Lieu / public", f"x{side.venue_factor:.3f}"),
                ("Rouge / blessure en match", f"x{side.event_factor:.3f}"),
                ("Buts attendus (xG)", f"<b>{side.xg:.2f}</b>"),
            ]

        label = round_label or f"Journée {m.matchday}"
        pens_html = f"<br><span style='color:{GREY}'>t.a.b. {pens[0]} - {pens[1]}</span>" if pens else ""
        crowd = ""
        if m.attendance:
            where = "stade neutre" if m.neutral else home.stadium
            crowd = (f"<br><span style='color:{GREY}'>👥 {m.attendance:,} / {m.capacity:,} "
                     f"({100 * m.attendance / max(1, m.capacity):.0f} %) · {where}</span>").replace(",", " ")
        html = [f"""
        <table width='100%' cellpadding='4'><tr>
          <td align='center'><img src='logo:{home.id}' width='56'><br><b>{home.name}</b></td>
          <td align='center'><span style='font-size:30px'><b>{m.home_goals} - {m.away_goals}</b></span>
              <br><span style='color:{GREY}'>{label}</span>{pens_html}{crowd}</td>
          <td align='center'><img src='logo:{away.id}' width='56'><br><b>{away.name}</b></td>
        </tr></table><hr>"""]

        # chronologie : buts (⚽ + 👟), cartons (🟨 🟥), blessures (🩹)
        timeline = []
        for e in m.goals:
            team = home if e.team_id == m.home_id else away
            assist = f" &nbsp;👟 <span style='color:{GREY}'>passe de {e.assist_name}</span>" if e.assist_name else ""
            timeline.append((e.minute, e.team_id, f"⚽ <b>{e.player_name}</b> "
                                                  f"<span style='color:{GREY}'>({team.short})</span>{assist}"))
        for c in m.cards:
            team = home if c.team_id == m.home_id else away
            if c.kind == "yellow":
                text = f"🟨 {c.player_name}"
            elif c.kind == "second_yellow":
                text = f"🟥 {c.player_name} <span style='color:{GREY}'>(2e jaune, {c.ban} match de suspension)</span>"
            else:
                text = (f"🟥 <b>{c.player_name}</b> <span style='color:{GREY}'>(rouge direct"
                        f"{', geste violent' if c.violent else ''}, {c.ban} matchs de suspension)</span>")
            timeline.append((c.minute, c.team_id, f"{text} <span style='color:{GREY}'>({team.short})</span>"))
        for i in m.injuries:
            team = home if i.team_id == m.home_id else away
            sub = f", remplacé par {i.sub_name}" if i.sub_name else ", pas de remplaçant"
            timeline.append((i.minute, i.team_id, f"🩹 {i.player_name} <span style='color:{GREY}'>({i.label}, "
                                                  f"{i.matches} match{'s' if i.matches > 1 else ''}{sub}; {team.short})</span>"))
        html.append("<b>Chronologie</b> <small style='color:%s'>(⚽ but, 👟 passe décisive, 🟨🟥 cartons, 🩹 blessure)</small><br>" % GREY)
        if timeline:
            for minute, team_id, text in sorted(timeline, key=lambda x: (x[0], x[1])):
                side = "◀" if team_id == m.home_id else "▶"
                html.append(f"{minute}' &nbsp; {side} {text}<br>")
        else:
            html.append("<i>Aucun événement</i><br>")
        for side, team in ((m.home, home), (m.away, away)):
            if side.absent:
                html.append(f"<span style='color:{GREY}'>Absents {team.short} : "
                            + ", ".join(f"{n} ({r})" for n, r in side.absent) + "</span><br>")

        html.append("<hr><b>Analyse du score</b>")
        html.append("<table width='100%' cellpadding='3' border='0'>"
                    f"<tr><td></td><td align='center'><b>{home.short}</b></td><td align='center'><b>{away.short}</b></td></tr>")
        for (lab, hv), (_, av) in zip(analysis_rows(m.home), analysis_rows(m.away)):
            html.append(f"<tr><td>{lab}</td><td align='center'>{hv}</td><td align='center'>{av}</td></tr>")
        html.append("</table>")
        html.append(f"<small style='color:{GREY}'>xG = {BASE_GOALS} x (att/déf adverse)^{K} x forme x lieu / "
                    f"racine(forme adverse) x incidents. Buts = arrondi de xG + reste des matchs précédents.</small>")

        html.append("<hr><b>Compositions</b><table width='100%' cellpadding='2'><tr>")
        for side in (m.home, m.away):
            html.append(f"<td valign='top'><b>{side.formation}</b><br>")
            for name, role, rating in side.lineup:
                cap = " <b style='color:#c49a00'>©</b>" if name == side.captain_name else ""
                html.append(f"<span style='color:{GREY}'>{ROLE_LABELS[role]}</span> {name}{cap} "
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
        self.table = SortTable()
        setup_table(self.table, ["J", "Domicile", "Score", "Extérieur", "Affluence", "xG dom.", "xG ext."], 38)
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
            first = cell(m.matchday, color=GREY, bg=bg_other)
            first.setData(Qt.ItemDataRole.UserRole, i)             # index dans self.rows (le tri change l'ordre visuel)
            self.table.setItem(i, 0, first)
            self.table.setItem(i, 1, cell(home.name, "left", bold=hw, icon=logo_icon(home), bg=bg_home))
            marks = (" 🟥" if any(c.kind != "yellow" for c in m.cards) else "") + (" 🩹" if m.injuries else "")
            self.table.setItem(i, 2, cell(f"{m.home_goals} - {m.away_goals}{marks}", bold=True, size=12, bg=bg_other))
            self.table.setItem(i, 3, cell(away.name, "left", bold=aw, icon=logo_icon(away), bg=bg_away))
            self.table.setItem(i, 4, cell(f"{m.attendance:,}".replace(",", " "), color=GREY, bg=bg_other))
            self.table.setItem(i, 5, cell(f"{m.home.xg:.2f}", color=GREY, bg=bg_other))
            self.table.setItem(i, 6, cell(f"{m.away.xg:.2f}", color=GREY, bg=bg_other))
        self.table.setColumnWidth(0, 34)
        self.table.setColumnWidth(2, 92)
        self.table.setColumnWidth(4, 78)
        self.table.setColumnWidth(5, 54)
        self.table.setColumnWidth(6, 54)
        if self.rows:
            self.table.selectRow(0)
            self.show_detail()                         # la sélection peut ne pas changer : on force
        else:
            self.detail.clear_match()

    def show_detail(self):
        selected = self.table.selectionModel().selectedRows()
        if selected:
            self.detail.show_match(self.win.league, self.rows[self.table.item(selected[0].row(), 0).data(
                Qt.ItemDataRole.UserRole)])


# =============================================================================
# 7. ONGLET ÉQUIPES
# =============================================================================
TROPHY_ICONS = {"league1": "🏆", "league2": "🥈", "league3": "🥉", "cup": "🏅", "interleague1": "🔵", "interleague2": "🟠"}


def trophy_html(rows: list) -> str:
    """Résumé des trophées d'une équipe : [(saison, genre, libellé)]."""
    if not rows:
        return f"<span style='color:{GREY}'>Aucun trophée pour le moment.</span>"
    grouped: dict = {}
    for season, kind, label in rows:
        grouped.setdefault((kind, label), []).append(season)
    lines = []
    for (kind, label), seasons in grouped.items():
        lines.append(f"{TROPHY_ICONS.get(kind, '🏆')} <b>{len(seasons)}×</b> {label} "
                     f"<small style='color:{GREY}'>(saison{'s' if len(seasons) > 1 else ''} "
                     f"{', '.join(str(s) for s in seasons)})</small>")
    return "<br>".join(lines)


class TeamsTab(QWidget):
    HEADERS = ["N°", "Joueur", "Poste", "Âge", "Pays", "Note", "Salaire/an", "Valeur", "J", "Buts", "Passes", "🟨",
               "🟥", "🩹", "État"]

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
        self.flag = QLabel()
        top.addWidget(self.flag)
        self.info = QLabel()
        self.info.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.info, 1)
        layout.addLayout(top)

        self.sub = QTabWidget()
        layout.addWidget(self.sub, 1)

        # effectif
        self.table = SortTable()
        setup_table(self.table, self.HEADERS, 30)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(14, QHeaderView.ResizeMode.ResizeToContents)
        for col, width in {0: 44, 2: 50, 3: 44, 4: 46, 5: 52, 6: 84, 7: 76, 8: 40, 9: 52, 10: 56, 11: 40, 12: 40, 13: 40}.items():
            self.table.setColumnWidth(col, width)
        self.table.cellDoubleClicked.connect(self.open_player)
        squad = QWidget()
        sv = QVBoxLayout(squad)
        sv.addWidget(self.table)
        sv.addWidget(QLabel("<small>© = capitaine · 🩹 blessé · ⛔ suspendu · statistiques de la saison en cours "
                            "(championnat + coupe nationale). Double-clic sur un joueur : fiche, visage, CV.</small>"))
        self.sub.addTab(squad, "👤 Effectif")

        # formation
        self.pitch = TeamPitchWidget()
        self.bench = QLabel()
        self.bench.setTextFormat(Qt.TextFormat.RichText)
        self.bench.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.bench.setMinimumWidth(230)
        self.bench.setWordWrap(True)
        formation = QWidget()
        fh = QHBoxLayout(formation)
        fh.addWidget(self.pitch, 3)
        fh.addWidget(self.bench, 1)
        self.sub.addTab(formation, "🎽 Formation")

        # finances (indicatives : rien n'est bloqué)
        self.fin_summary = QLabel()
        self.fin_summary.setTextFormat(Qt.TextFormat.RichText)
        self.fin_summary.setWordWrap(True)
        self.fin_in, self.fin_out = SortTable(), SortTable()
        setup_table(self.fin_in, ["Recettes (saison en cours)", "Montant"], 28)
        setup_table(self.fin_out, ["Dépenses (saison en cours)", "Montant"], 28)
        for t in (self.fin_in, self.fin_out):
            t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            t.setColumnWidth(1, 110)
            t.setFixedHeight(28 * 7 + 4)
        self.fin_hist = SortTable()
        setup_table(self.fin_hist, ["Saison", "Div.", "Recettes", "Dépenses", "Résultat", "Salaires", "Budget fin de saison"], 28)
        for col in range(1, 7):
            self.fin_hist.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        finance = QWidget()
        fv = QVBoxLayout(finance)
        fv.addWidget(self.fin_summary)
        fin_row = QHBoxLayout()
        fin_row.addWidget(self.fin_in)
        fin_row.addWidget(self.fin_out)
        fv.addLayout(fin_row)
        fv.addWidget(QLabel("<b>Saisons passées</b>"))
        fv.addWidget(self.fin_hist, 1)
        fv.addWidget(QLabel("<small>Chiffres INDICATIFS : aucun transfert ni aucune action n'est bloqué par le budget "
                            "(sauf si tu actives « Budget strict » dans Options). Billetterie = affluence réelle x prix "
                            "du billet ; droits TV, sponsors, salaires et entretien sont répartis sur la saison.</small>"))
        self.sub.addTab(finance, "💰 Finances")

        # historique
        self.trophies = QLabel()
        self.trophies.setTextFormat(Qt.TextFormat.RichText)
        self.history = SortTable()
        setup_table(self.history, ["Saison", "Pays", "Div.", "Rang", "Pts", "V", "N", "D", "BP", "BC",
                                   "Coupe nationale", "Interligue"], 28)
        self.history.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
        self.history.horizontalHeader().setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)
        for col, width in {0: 56, 1: 46, 2: 40, 3: 46, 4: 46, 5: 38, 6: 38, 7: 38, 8: 44, 9: 44}.items():
            self.history.setColumnWidth(col, width)
        hist = QWidget()
        hv = QVBoxLayout(hist)
        hv.addWidget(QLabel("<b>Trophées</b>"))
        hv.addWidget(self.trophies)
        hv.addWidget(QLabel("<b>Saisons passées</b>"))
        hv.addWidget(self.history, 1)
        self.sub.addTab(hist, "📜 Historique")

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

    def open_player(self, row: int, _col: int = 0):
        index = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        PlayerDialog(self.players[index], self.win.world, self).exec()

    def select_team(self, team_id: int):
        self.combo.setCurrentIndex(max(0, self.combo.findData(team_id)))

    def render(self, *_):
        world, league, result = self.win.world, self.win.league, self.win.league.result
        ledger = world.ledger
        team = league.teams[self.combo.currentData()]
        self.logo.setPixmap(make_logo(team, 96))
        self.flag.setPixmap(flag_pixmap(team.country, 44))
        self.flag.setToolTip(team.country)
        row = next(r for r in result.current_table if r.team_id == team.id)
        season_text = (f"{row.rank}e, {row.pts} pts ({row.won}V {row.drawn}N {row.lost}D, diff. {row.gd:+d})"
                       if row.played else "pas encore commencée")
        profile = result.profiles[team.id]
        captain = team.captain
        stats = [ledger.stats.get(p.id, {}) for p in team.players]
        total = lambda k: sum(s.get(k, 0) for s in stats)
        self.info.setText(
            f"<h2 style='margin:0'>{team.name}</h2>"
            f"<b>Note générale</b> : {team.overall_rating} · <b>Formation</b> : {team.formation} · "
            f"<b>Entraîneur</b> : {team.coach.name} (tactique {team.coach.tactics}, motivation {team.coach.motivation})<br>"
            f"<b>Capitaine</b> : {captain.name if captain else '-'} (leadership {captain.stats['leadership'] if captain else '-'}) · "
            f"<b>Niveau</b> : attaque {profile.attack:.1f} | défense {profile.defense:.1f}<br>"
            f"<b>Stade</b> : {team.stadium} ({team.capacity:,} places)".replace(",", " ") +
            f" · <b>Budget</b> : {fmt_money(world.team_budget_now(team.id))} · "
            f"<b>Masse salariale</b> : {fmt_money(wage_bill(team))}/an <span style='color:{GREY}'>(indicatif)</span>" +
            f"<br><b>Saison</b> : {season_text} · ⚽ {total('goals')} buts · 👟 {total('assists')} passes · "
            f"🟨 {total('yellow')} · 🟥 {total('red')} · 🩹 {total('injuries')} blessure(s)")

        # --- effectif : numérotés, titulaires (1 à 11) d'abord
        starters = {p.id for p, _ in team.best_xi(team.formation)}
        self.players = sorted(team.players, key=lambda p: (p.number or 99, p.id))
        self.table.setRowCount(len(self.players))
        for i, p in enumerate(self.players):
            st = ledger.stats.get(p.id, {})
            starter = p.id in starters
            status = ledger.status_of(p)
            name = p.name + ("  ©" if p.id == team.captain_id else "") + (f"  «{p.nickname}»" if p.nickname else "")
            bg = (214, 69, 69, 55) if status else None
            number_item = cell(p.number or "", bold=True, size=11, bg=bg)
            number_item.setData(Qt.ItemDataRole.UserRole, i)
            self.table.setItem(i, 0, number_item)
            self.table.setItem(i, 1, cell(name, "left", bold=starter, bg=bg))
            self.table.setItem(i, 2, cell(role_text(p), bold=True, bg=bg))
            self.table.setItem(i, 3, cell(p.age, bg=bg))
            self.table.setItem(i, 4, flag_cell(p.country, bg))
            self.table.setItem(i, 5, cell(f"{p.overall:.0f}", bold=True, bg=bg))
            salary, value = player_salary(p), player_value(p)
            self.table.setItem(i, 6, cell(fmt_money(salary), sort=(0, float(salary)), bg=bg))
            self.table.setItem(i, 7, cell(fmt_money(value), sort=(0, float(value)), color=GREY, bg=bg))
            for col, key in enumerate(("games", "goals", "assists", "yellow", "red", "injuries"), start=8):
                v = st.get(key, 0)
                self.table.setItem(i, col, cell(v, color=None if v else GREY, bg=bg))
            self.table.setItem(i, 14, cell(status or ("Titulaire" if starter else "Remplaçant"), "left",
                                           color=RED if status else (None if starter else GREY), bg=bg))

        # --- formation
        self.pitch.set_team(team, ledger)
        bench = [p for p in self.players if p.id not in starters]
        self.bench.setText("<b>Remplaçants</b><br>" + "<br>".join(
            f"<b>{p.number}</b> {p.name} <small style='color:{GREY}'>({role_text(p)} {p.overall:.0f})</small>"
            for p in bench) + f"<br><br><small style='color:{GREY}'>Numéros : le meilleur de chaque poste prend "
            "le numéro du poste (1 gardien, 10 meneur, 9 avant-centre...). Un remplaçant promu titulaire "
            "hérite du numéro.</small>")

        # --- finances
        st = world.team_statement(team.id)
        for table, key in ((self.fin_in, "revenus"), (self.fin_out, "dépenses")):
            lines = st[key]
            table.setRowCount(len(lines))
            for i, (label, amount) in enumerate(lines):
                table.setItem(i, 0, cell(label, "left"))
                table.setItem(i, 1, cell(fmt_money(amount), color=None if amount else GREY, sort=(0, float(amount))))
        profit = st["profit"]
        color = GREEN if profit >= 0 else RED
        self.fin_summary.setText(
            f"<b>Budget de début de saison</b> : {fmt_money(team.budget)} · <b>Résultat à ce jour</b> : "
            f"<b style='color:{color}'>{fmt_money(profit, True)}</b> (recettes {fmt_money(st['total_revenus'])}, "
            f"dépenses {fmt_money(st['total_dépenses'])}) · <b>Budget actuel</b> : <b>{fmt_money(team.budget + profit)}</b>"
            f"<br><b>Masse salariale</b> : {fmt_money(wage_bill(team))}/an dont entraîneur {fmt_money(coach_salary(team.coach))}")
        history = world.team_finance_history(team.id)
        self.fin_hist.setRowCount(len(history))
        for i, (season, division, revenue, expenses, result, wages, budget_end) in enumerate(history):
            self.fin_hist.setItem(i, 0, cell(season))
            self.fin_hist.setItem(i, 1, cell(division))
            for col, v in enumerate((revenue, expenses, result, wages, budget_end), start=2):
                self.fin_hist.setItem(i, col, cell(fmt_money(v, col == 4), sort=(0, float(v)),
                                                   color=(GREEN if v >= 0 else RED) if col == 4 else None))

        # --- historique
        self.trophies.setText(trophy_html(world.team_trophies(team.id)))
        rows = world.team_history(team.id)
        self.history.setRowCount(len(rows))
        for i, (season, country, division, rank, pts, w, d, l, gf, ga, cup, inter) in enumerate(rows):
            bg = (255, 215, 0, 60) if rank == 1 else None
            for col, v in enumerate((season, None, division, rank, pts, w, d, l, gf, ga, cup, inter)):
                if col == 1:
                    self.history.setItem(i, col, flag_cell(country, bg))
                else:
                    self.history.setItem(i, col, cell(v, "left" if col >= 10 else "center", bold=col == 3, bg=bg))


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
        self.min_rating.setValue(60)
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

        more = QHBoxLayout()
        self.country_combo = QComboBox()
        self.country_combo.addItem("Tous pays", None)
        for c in Faker().get_countries():
            self.country_combo.addItem(flag_icon(c, 22), c, c)
        self.min_age = QSpinBox()
        self.min_age.setRange(16, 45)
        self.min_age.setValue(16)
        self.min_age.setPrefix("Âge min ")
        self.max_rating = QSpinBox()
        self.max_rating.setRange(0, 99)
        self.max_rating.setValue(99)
        self.max_rating.setPrefix("Note max ")
        self.min_pot = QSpinBox()
        self.min_pot.setRange(0, 99)
        self.min_pot.setPrefix("Potentiel min ")
        self.min_res = QSpinBox()
        self.min_res.setRange(0, 99)
        self.min_res.setPrefix("Résistance min ")
        self.min_res.setToolTip("Résistance aux blessures")
        self.foot_combo = QComboBox()
        for text, key in (("Tous pieds", None), ("Pied droit", "R"), ("Pied gauche", "L"), ("Deux pieds", "B")):
            self.foot_combo.addItem(text, key)
        for w in (self.country_combo, self.min_age, self.max_rating, self.min_pot, self.min_res, self.foot_combo):
            more.addWidget(w)
            if isinstance(w, QSpinBox):
                w.editingFinished.connect(self.search)
            else:
                w.currentIndexChanged.connect(self.search)
        reset_btn = QPushButton("Réinitialiser")
        reset_btn.clicked.connect(self.reset_filters)
        more.addWidget(reset_btn)
        rv.addLayout(more)
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

    def reset_filters(self):
        for w, v in ((self.min_rating, 0), (self.max_age, 45), (self.min_age, 16), (self.max_rating, 99),
                     (self.min_pot, 0), (self.min_res, 0)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        for w in (self.role_combo, self.country_combo, self.foot_combo):
            w.blockSignals(True)
            w.setCurrentIndex(0)
            w.blockSignals(False)
        self.name_edit.clear()
        self.search()

    def search(self, *_):
        league = self.win.league
        role, min_rating = self.role_combo.currentData(), self.min_rating.value()
        max_age, name = self.max_age.value(), self.name_edit.text().strip()
        country, foot = self.country_combo.currentData(), self.foot_combo.currentData()
        min_age, max_rating = self.min_age.value(), self.max_rating.value()
        min_pot, min_res = self.min_pot.value(), self.min_res.value()
        source = self.source_combo.currentData()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if source is None:
                self.candidates = league.market(role, min_rating, max_age, name, limit=300, country=country,
                                                min_age=min_age, max_rating=max_rating, min_potential=min_pot,
                                                min_resistance=min_res, foot=foot)
            else:
                pool = league.teams[source].players
                key = (lambda p: p.ovr[role]) if role else (lambda p: p.overall)
                self.candidates = sorted(
                    (p for p in pool if min_rating <= key(p) <= max_rating and min_age <= p.age <= max_age
                     and name.lower() in p.name.lower() and (not country or p.country == country)
                     and p.potential >= min_pot and p.injury_resistance >= min_res
                     and (not foot or p.preferred_foot == foot)),
                    key=lambda p: -key(p))
        finally:
            QApplication.restoreOverrideCursor()
        captain = league.teams[source].captain_id if source else None
        fill_players_table(self.cand_table, self.candidates, captain)
        self.update_summary()

    def _selected(self, table, players):
        rows = table.selectionModel().selectedRows()
        return players[table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)] if rows else None

    def finance_hint(self, out_p, in_p) -> str:
        """Conséquences financières INDICATIVES du transfert (salaires, indemnité). Ne bloque rien."""
        free = self.source_combo.currentData() is None
        fee = transfer_fee(in_p, out_p, free_market=free)
        delta = player_salary(in_p) - player_salary(out_p)
        fee_text = (f"prime de signature <b>{fmt_money(fee)}</b>" if free else
                    f"indemnité <b>{fmt_money(abs(fee))}</b> " + ("payée" if fee > 0 else "encaissée"))
        return (f"<span style='color:{GREY}'>💶 Salaire : {fmt_money(player_salary(out_p))} → {fmt_money(player_salary(in_p))} "
                f"({fmt_money(delta, True)}/an) · valeurs {fmt_money(player_value(out_p))} / {fmt_money(player_value(in_p))} · "
                f"{fee_text} (indicatif)</span>")

    def update_summary(self):
        out_p = self._selected(self.my_table, self.my_players)
        in_p = self._selected(self.cand_table, self.candidates)
        self.swap_btn.setEnabled(bool(out_p and in_p))
        if out_p and in_p:
            self.summary.setText(
                f"<b style='color:{RED}'>Part :</b> {out_p.name} ({role_text(out_p)} {out_p.overall:.0f}, {out_p.age} ans) "
                f"&nbsp;&nbsp;➜&nbsp;&nbsp; <b style='color:{GREEN}'>Arrive :</b> {in_p.name} "
                f"({role_text(in_p)} {in_p.overall:.0f}, {in_p.age} ans)<br>"
                + self.finance_hint(out_p, in_p))
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
        self.win.world.rebuild_unplayed()
        self.win.statusBar().showMessage("Transfert effectué : " + text, 8000)
        if self.auto_sim.isChecked() and league.season.finished:
            self.win.rerun_full()
        else:
            self.win.refresh_all()


# =============================================================================
# 9. ONGLETS BUTEURS / PASSEURS
# =============================================================================
class StatsTab(QWidget):
    """Buteurs (kind='goals') ou passeurs (kind='assists'), par portée : division, pays, monde, coupes, ou tout confondu."""
    SCOPES = [("division", "Cette division"),
              ("country", "Championnat du pays (toutes ses divisions)"),
              ("leagues", "Tous les championnats (monde)"),
              ("cup", "Coupe nationale du pays"),
              ("inter", "Coupes interligue"),
              ("all", "Tout confondu (championnats et coupes)")]

    def __init__(self, win: "MainWindow", kind: str):
        super().__init__()
        self.win, self.kind = win, kind
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>Classement :</b>"))
        self.scope = QComboBox()
        for key, label in self.SCOPES:
            self.scope.addItem(label, key)
        self.scope.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.scope)
        self.caption = QLabel()
        bar.addWidget(self.caption, 1)
        layout.addLayout(bar)
        main, other = ("Buts", "Passes D.") if kind == "goals" else ("Passes D.", "Buts")
        self.table = SortTable()
        setup_table(self.table, ["#", "Joueur", "Équipe", "Pays", main, other], 34)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

    def predicate(self):
        key = self.scope.currentData()
        league = self.win.league
        country, division = league.country, league.division
        return {
            "division": lambda sc: sc == ("league", country, division),
            "country": lambda sc: sc[0] == "league" and sc[1] == country,
            "leagues": lambda sc: sc[0] == "league",
            "cup": lambda sc: sc == ("cup", country),
            "inter": lambda sc: sc[0] == "inter",
            "all": lambda sc: True,
        }[key]

    def refresh(self, *_):
        world = self.win.world
        data = world.ledger.aggregate(self.predicate())
        goals_first = self.kind == "goals"
        top = sorted(data.items(), key=lambda kv: ((-kv[1][2], -kv[1][3]) if goals_first else (-kv[1][3], -kv[1][2]),
                                                     kv[1][0]))[:50]
        label = dict(self.SCOPES)[self.scope.currentData()]
        self.caption.setText(f"<span style='color:{GREY}'>{label} · {len(data)} joueur(s) ont marqué ou "
                             f"délivré une passe</span>")
        self.table.setRowCount(len(top))
        for i, (pid, (name, team_id, goals, assists)) in enumerate(top):
            team = world.teams[team_id]
            self.table.setItem(i, 0, cell(MEDALS[i] if i < 3 else i + 1, bold=True, sort=(0, float(i + 1))))
            self.table.setItem(i, 1, cell(name, "left", bold=True))
            self.table.setItem(i, 2, cell(team.name, "left", icon=logo_icon(team)))
            self.table.setItem(i, 3, flag_cell(team.country))
            self.table.setItem(i, 4, cell(goals if goals_first else assists, bold=True))
            self.table.setItem(i, 5, cell(assists if goals_first else goals, color=GREY))
        for col, width in {0: 50, 3: 50, 4: 80, 5: 80}.items():
            self.table.setColumnWidth(col, width)


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
        self.zoom = 1.0

    def base_size(self):
        """Taille du tableau à 100 % (None s'il n'y a pas de coupe)."""
        if self.cup is None:
            return None
        lay = self._layout()
        return lay["width"], lay["height"]

    def _apply_size(self):
        base = self.base_size()
        if base is None:
            self.setFixedSize(10, 10)
        else:
            self.setFixedSize(int(base[0] * self.zoom), int(base[1] * self.zoom))

    def set_zoom(self, zoom: float):
        self.zoom = max(0.3, min(2.5, zoom))
        self._apply_size()
        self.update()

    def set_cup(self, cup, league):
        self.cup, self.league = cup, league
        self._apply_size()
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
        p.scale(self.zoom, self.zoom)
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
            day = f" · J{cup.round_days[c]}" if c < len(cup.round_days) else ""
            p.drawText(QRectF(col_x[c], 8, self.BOX_W, 24), Qt.AlignmentFlag.AlignCenter, name + day)

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
        point = QPointF(event.position().x() / self.zoom, event.position().y() / self.zoom)
        for rect, cm in self._hits:
            if rect.contains(point):
                self.matchClicked.emit(cm)
                return


class ZoomBracket(QWidget):
    """Tableau de coupe avec zoom : boutons − / ＋, curseur, « Ajuster à la fenêtre », Ctrl + molette."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        minus, plus = QPushButton("−"), QPushButton("＋")
        for b in (minus, plus):
            b.setFixedWidth(34)
        minus.setToolTip("Rétrécir")
        plus.setToolTip("Agrandir")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(30, 250)
        self.slider.setValue(100)
        self.slider.setFixedWidth(170)
        self.label = QLabel("100 %")
        self.label.setMinimumWidth(44)
        fit = QPushButton("⤢  Ajuster à la fenêtre")
        reset = QPushButton("100 %")
        bar.addWidget(QLabel("🔍 Zoom :"))
        for w in (minus, self.slider, plus, self.label, fit, reset):
            bar.addWidget(w)
        bar.addWidget(QLabel("<small style='color:%s'>Ctrl + molette pour zoomer</small>" % GREY))
        bar.addStretch()
        layout.addLayout(bar)

        self.bracket = BracketWidget()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.bracket)
        self.scroll.setWidgetResizable(False)
        self.scroll.viewport().installEventFilter(self)
        layout.addWidget(self.scroll, 1)

        self.slider.valueChanged.connect(lambda v: self.set_zoom(v / 100))
        minus.clicked.connect(lambda: self.set_zoom(self.bracket.zoom / 1.2))
        plus.clicked.connect(lambda: self.set_zoom(self.bracket.zoom * 1.2))
        reset.clicked.connect(lambda: self.set_zoom(1.0))
        fit.clicked.connect(self.fit)

    def set_zoom(self, zoom: float) -> None:
        self.bracket.set_zoom(zoom)
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(self.bracket.zoom * 100)))
        self.slider.blockSignals(False)
        self.label.setText(f"{int(round(self.bracket.zoom * 100))} %")

    def fit(self) -> None:
        base = self.bracket.base_size()
        if base is None:
            return
        view = self.scroll.viewport().size()
        self.set_zoom(min(view.width() / base[0], view.height() / base[1]) * 0.97)

    def eventFilter(self, obj, event):
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Wheel \
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.bracket.zoom * (1.1 if event.angleDelta().y() > 0 else 1 / 1.1))
            return True
        return super().eventFilter(obj, event)


class CupEntryDialog(QDialog):
    """Choix des équipes inscrites à une coupe interligue (tous pays confondus), avec filtres."""

    def __init__(self, world: World, kind: str, preselected: list, parent=None):
        super().__init__(parent)
        self.world, self.kind = world, kind
        self.setWindowTitle("Équipes inscrites à la coupe")
        layout = QVBoxLayout(self)
        qualified = world.qualifiers or {"blue": [], "orange": []}      # qualifiés de la saison précédente
        self.qualified_ids = qualified[kind]
        self.status = {i: "Interligue 1" for i in qualified["blue"]}
        self.status.update({i: "Interligue 2" for i in qualified["orange"]})
        self.seed_ids = world.seed_order(list(world.teams))
        ranks = {}
        for lg in world.competitions.values():
            if lg.season.played:
                ranks.update({r.team_id: r.rank for r in lg.season.result.current_table})

        # ---- filtres
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔎 Nom du club ou de la ville…")
        self.search.setClearButtonEnabled(True)
        self.country = QComboBox()
        self.country.addItem("Tous les pays", None)
        for c in world.countries:
            self.country.addItem(flag_icon(c, 22), c, c)
        self.division = QComboBox()
        self.division.addItem("Toutes les divisions", None)
        for d in range(1, world.n_divisions + 1):
            self.division.addItem(f"Division {d}", d)
        self.state = QComboBox()
        for text, key in (("Tous les clubs", "all"), ("Qualifiés pour cette coupe", "mine"),
                          ("Qualifiés (toutes les coupes)", "any"), ("Non qualifiés", "none")):
            self.state.addItem(text, key)
        self.only_checked = QCheckBox("Inscrits seulement")
        for w in (self.search, self.country, self.division, self.state, self.only_checked):
            bar.addWidget(w)
        bar.setStretch(0, 2)
        layout.addLayout(bar)

        # ---- tableau
        self.table = SortTable()
        setup_table(self.table, ["", "#", "Équipe", "Pays", "Div.", "Rang", "Qualification"], 28)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setRowCount(len(self.seed_ids))
        for row, tid in enumerate(self.seed_ids):
            team = world.teams[tid]
            check = cell("")
            check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Checked if tid in preselected else Qt.CheckState.Unchecked)
            name = cell(team.name, "left", bold=tid in self.status, icon=logo_icon(team))
            name.setData(Qt.ItemDataRole.UserRole, tid)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, cell(row + 1, color=GREY))
            self.table.setItem(row, 2, name)
            self.table.setItem(row, 3, flag_cell(team.country))
            self.table.setItem(row, 4, cell(f"D{team.division}"))
            self.table.setItem(row, 5, cell(f"{ranks[tid]}e" if tid in ranks else "–", color=None if tid in ranks else GREY))
            q = self.status.get(tid)
            self.table.setItem(row, 6, cell(f"✔ {q}" if q else "", "left", bold=True,
                                            color=BLUE if q == "Interligue 1" else ORANGE if q else None))
        for col, width in {0: 36, 1: 40, 3: 46, 4: 44, 5: 50}.items():
            self.table.setColumnWidth(col, width)
        self.table.cellClicked.connect(self.on_click)
        self.table.itemChanged.connect(self.on_changed)
        layout.addWidget(self.table, 1)

        # ---- actions
        row = QHBoxLayout()
        q_btn = QPushButton("Qualifiés pour cette coupe")
        q_btn.setEnabled(bool(self.qualified_ids))
        q_btn.setToolTip("Les qualifiés de la saison précédente (complétés jusqu'à une puissance de 2)")
        q_btn.clicked.connect(lambda: self.set_checked(set(self.qualified_ids)))
        all_btn = QPushButton("☑ Cocher les affichés")
        all_btn.clicked.connect(lambda: self.set_visible(True))
        none_btn = QPushButton("☐ Décocher les affichés")
        none_btn.clicked.connect(lambda: self.set_visible(False))
        grow_btn = QPushButton("＋ Ajouter les meilleurs affichés (→ puissance de 2)")
        grow_btn.clicked.connect(self.grow)
        clear_btn = QPushButton("Tout décocher")
        clear_btn.clicked.connect(lambda: self.set_checked(set()))
        for b in (q_btn, all_btn, none_btn, grow_btn, clear_btn):
            row.addWidget(b)
        layout.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for w in (self.country, self.division, self.state):
            w.currentIndexChanged.connect(self.apply_filter)
        self.search.textChanged.connect(self.apply_filter)
        self.only_checked.toggled.connect(self.apply_filter)
        self.resize(760, 700)
        self.apply_filter()

    # ---- utilitaires
    def _tid(self, row: int) -> int:
        return self.table.item(row, 2).data(Qt.ItemDataRole.UserRole)

    def _is_checked(self, row: int) -> bool:
        return self.table.item(row, 0).checkState() == Qt.CheckState.Checked

    def checked_ids(self) -> list:
        return [self._tid(r) for r in range(self.table.rowCount()) if self._is_checked(r)]

    def set_checked(self, ids: set):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(Qt.CheckState.Checked if self._tid(r) in ids
                                                else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.apply_filter()

    def set_visible(self, value: bool):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            if not self.table.isRowHidden(r):
                self.table.item(r, 0).setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.apply_filter()

    def on_click(self, row, col):
        if col != 0:                                   # un clic n'importe où sur la ligne coche / décoche
            item = self.table.item(row, 0)
            item.setCheckState(Qt.CheckState.Unchecked if self._is_checked(row) else Qt.CheckState.Checked)

    def on_changed(self, item):
        if item.column() == 0:
            self.apply_filter() if self.only_checked.isChecked() else self.update_info()

    def apply_filter(self, *_):
        text = self.search.text().strip().lower()
        country, division, state = self.country.currentData(), self.division.currentData(), self.state.currentData()
        for r in range(self.table.rowCount()):
            tid = self._tid(r)
            team = self.world.teams[tid]
            ok = (not text or text in team.name.lower() or text in team.city.lower()) \
                and (country is None or team.country == country) \
                and (division is None or team.division == division) \
                and (state == "all" or (state == "mine" and tid in self.qualified_ids)
                     or (state == "any" and tid in self.status) or (state == "none" and tid not in self.status)) \
                and (not self.only_checked.isChecked() or self._is_checked(r))
            self.table.setRowHidden(r, not ok)
        self.update_info()

    def grow(self):
        """Ajoute les meilleures équipes AFFICHÉES jusqu'à la puissance de 2 suivante (6 -> 8, 8 -> 16...)."""
        checked = set(self.checked_ids())
        target = min(max(2, next_power_of_two(len(checked))), len(self.seed_ids))
        for r in range(self.table.rowCount()):                      # ordre du tableau = têtes de série
            if len(checked) >= target:
                break
            if not self.table.isRowHidden(r):
                checked.add(self._tid(r))
        self.set_checked(checked)

    def update_info(self, *_):
        n = len(self.checked_ids())
        shown = sum(1 for r in range(self.table.rowCount()) if not self.table.isRowHidden(r))
        power_of_two = n >= 2 and n & (n - 1) == 0
        self.info.setText(f"<b>{n}</b> inscrits · {shown} clubs affichés — "
                          + (describe_structure(n) if power_of_two else
                             "il faut 2, 4, 8, 16… équipes (aucune équipe n'est qualifiée d'office) : "
                             "utilise « Ajouter » pour compléter."))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(power_of_two)


class GroupsWidget(QWidget):
    """Phase de poules d'une coupe interligue : un classement par poule + la liste des matchs joués."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.matches: list = []
        outer = QVBoxLayout(self)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.scroll.setWidget(self.host)
        self.scroll.setMinimumHeight(220)
        outer.addWidget(self.scroll, 3)
        outer.addWidget(QLabel("<b>Matchs de poule joués</b> <small>(double-clic pour le détail)</small>"))
        self.table = SortTable()
        setup_table(self.table, ["Journée", "Poule", "Domicile", "Score", "Extérieur", "Affluence"], 28)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(3, 70)
        self.table.cellDoubleClicked.connect(self.open_match)
        outer.addWidget(self.table, 2)

    def refresh(self, cup) -> None:
        world = self.win.world
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.matches = []
        if cup is None:
            self.table.setRowCount(0)
            return
        started = bool(cup.group_rounds)
        done = cup.knockout is not None
        self.hint.setText(f"{describe_groups(len(cup.teams))}. "
                          + ("Les 2 premiers de chaque poule (en vert) passent en phase finale." if done else
                             "Les poules se jouent sur 3 journées de calendrier."))
        columns = 2 if cup.n_groups <= 4 else 4
        for g in range(cup.n_groups):
            box = QGroupBox(f"Poule {chr(65 + g)}")
            lay = QVBoxLayout(box)
            table = SortTable()
            setup_table(table, ["#", "Équipe", "J", "V", "N", "D", "BP", "BC", "Pts"], 26)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            for col in (0, 2, 3, 4, 5, 6, 7, 8):
                table.setColumnWidth(col, 34)
            rows = cup.group_table(g)
            table.setRowCount(len(rows))
            for i, (tid, played, w, d, l, gf, ga, pts) in enumerate(rows):
                team = world.teams[tid]
                bg = WIN_BG if done and i < 2 else None
                for col, value in enumerate((i + 1, None, played, w, d, l, gf, ga, pts)):
                    if col == 1:
                        table.setItem(i, col, cell(team.name, "left", bold=True, icon=logo_icon(team), bg=bg))
                    else:
                        table.setItem(i, col, cell(value, bold=col == 8, bg=bg))
            table.setFixedHeight(26 * (len(rows) + 1) + 6)
            lay.addWidget(table)
            self.grid.addWidget(box, g // columns, g % columns)
        self.grid.setRowStretch(self.grid.rowCount(), 1)

        for g, schedule_rounds in enumerate(cup.group_schedule):
            pass
        rows = []
        for matches in cup.group_rounds:
            for cm in matches:
                group = next(g for g, ids in enumerate(cup.groups) if cm.home_id in ids)
                rows.append((cm, group))
        self.matches = rows
        self.table.setRowCount(len(rows))
        for i, (cm, group) in enumerate(rows):
            r = cm.result
            if r.home_goals == r.away_goals:
                bg_h = bg_a = bg_o = DRAW_BG
            else:
                won = r.home_goals > r.away_goals
                bg_h, bg_a = (WIN_BG, LOSS_BG) if won else (LOSS_BG, WIN_BG)
                bg_o = None
            first = cell(cm.round_name.split("journée ")[-1], bg=bg_o)
            first.setData(Qt.ItemDataRole.UserRole, i)
            self.table.setItem(i, 0, first)
            self.table.setItem(i, 1, cell(chr(65 + group), bg=bg_o))
            home, away = world.teams[cm.home_id], world.teams[cm.away_id]
            self.table.setItem(i, 2, cell(home.name, "left", icon=logo_icon(home), bg=bg_h))
            self.table.setItem(i, 3, cell(f"{r.home_goals} - {r.away_goals}", bold=True, bg=bg_o))
            self.table.setItem(i, 4, cell(away.name, "left", icon=logo_icon(away), bg=bg_a))
            self.table.setItem(i, 5, cell(f"{r.attendance:,}".replace(",", " "), color=GREY, bg=bg_o))

    def open_match(self, row, _col):
        cm, _group = self.matches[self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)]
        dlg = QDialog(self)
        dlg.setWindowTitle(cm.round_name)
        lay = QVBoxLayout(dlg)
        view = MatchDetailView()
        view.show_match(self.win.world, cm.result, round_label=cm.round_name)
        lay.addWidget(view)
        dlg.resize(560, 760)
        dlg.exec()


class CupPanel(QWidget):
    """Coupe interligue : jouée automatiquement à certaines journées du calendrier, avec les qualifiés de la saison
    précédente (jamais d'équipe qualifiée d'office : toutes jouent le premier tour). Au choix : élimination directe
    ou phase de poules (4 équipes par poule) puis élimination directe."""

    def __init__(self, win: "MainWindow", kind: str, title: str):
        super().__init__()
        self.win, self.kind, self.title = win, kind, title
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.edit_btn = QPushButton("👥  Personnaliser les inscrits…")
        self.edit_btn.setToolTip("Possible tant que le premier tour n'est pas joué (nombre d'équipes = puissance de 2)")
        self.edit_btn.clicked.connect(self.edit_entries)
        bar.addWidget(self.edit_btn)
        self.groups_box = QCheckBox("Phase de poules")
        self.groups_box.setToolTip("Poules de 4 (8 équipes ou plus), puis élimination directe. S'applique aux deux "
                                   "coupes interligue.")
        self.groups_box.toggled.connect(self.toggle_groups)
        bar.addWidget(self.groups_box)
        bar.addStretch()
        layout.addLayout(bar)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.stack = QTabWidget()
        self.groups_view = GroupsWidget(win)
        self.zoom_view = ZoomBracket()
        self.bracket = self.zoom_view.bracket
        self.bracket.matchClicked.connect(self.show_match)
        self.stack.addTab(self.groups_view, "📊 Poules")
        self.stack.addTab(self.zoom_view, "🏆 Phase finale")
        layout.addWidget(self.stack, 1)
        layout.addWidget(QLabel("<small>Qualifiés = 3 premiers (Interligue 1) ou 3 suivants (Interligue 2) de chaque "
                                "division 1 à la fin de la saison précédente, complétés par les meilleurs suivants "
                                "jusqu'à une puissance de 2. Les tours se jouent aux journées indiquées. Un nul se "
                                "joue aux tirs au but (hors poules), la finale sur terrain neutre.</small>"))

    def reset(self):
        pass                                        # les coupes viennent du monde : rien à effacer ici

    def toggle_groups(self, value: bool):
        world = self.win.world
        OPTIONS.interleague_groups = value
        world.rebuild_interleague_if_unplayed()
        self.win.refresh_all()
        played = any(c is not None and c.rounds for c in world.interleague.values())
        if played:
            self.win.statusBar().showMessage("Les coupes ont déjà commencé : le format s'appliquera à la saison "
                                             "suivante.", 7000)

    def refresh(self):
        world = self.win.world
        cup = world.interleague.get(self.kind)
        grouped = isinstance(cup, GroupCup)
        self.groups_box.blockSignals(True)
        self.groups_box.setChecked(OPTIONS.interleague_groups)
        self.groups_box.blockSignals(False)
        self.stack.setTabVisible(0, grouped)
        bracket_cup = cup.knockout if grouped else cup
        self.bracket.set_cup(bracket_cup, world)
        self.groups_view.refresh(cup if grouped else None)
        self.edit_btn.setEnabled(world.qualifiers is not None and (cup is None or not cup.rounds))
        if cup is None:
            self.info.setText("<b>Pas de coupe cette saison</b> : elle repose sur les qualifiés de la saison "
                              "précédente. Termine la saison puis clique sur « Saison suivante ».")
            return
        if cup.finished:
            state = f"🏆 Vainqueur : <b>{cup.champion.name}</b> ({cup.champion.country})"
        else:
            state = f"Prochain tour : <b>{cup.next_round_name}</b> (journée {cup.round_days[len(cup.rounds)]})"
        text = describe_groups(len(cup.teams)) if grouped else describe_structure(len(cup.teams))
        self.info.setText(f"{text}. {state}")
        if grouped and cup.knockout is None:
            self.stack.setCurrentIndex(0)

    def edit_entries(self):
        world = self.win.world
        cup = world.interleague.get(self.kind)
        pre = list(cup.teams) if cup else (world.qualifiers or {}).get(self.kind, [])
        dlg = CupEntryDialog(world, self.kind, pre, self)
        if dlg.exec():
            world.build_interleague(self.kind, world.seed_order(dlg.checked_ids()))
            self.refresh()

    def show_match(self, cm):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.title} : {cm.round_name}")
        lay = QVBoxLayout(dlg)
        view = MatchDetailView()
        view.show_match(self.win.world, cm.result, pens=cm.pens, round_label=cm.round_name)
        lay.addWidget(view)
        dlg.resize(560, 760)
        dlg.exec()


class CupTab(QTabWidget):
    """Les deux coupes interligue : 1 (3 premiers de chaque division 1) et 2 (les 3 suivants)."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.panels = (CupPanel(win, "blue", "Coupe interligue 1"), CupPanel(win, "orange", "Coupe interligue 2"))
        self.addTab(self.panels[0], "🔵 Coupe interligue 1")
        self.addTab(self.panels[1], "🟠 Coupe interligue 2")

    def reset(self):
        for p in self.panels:
            p.reset()

    def refresh(self):
        for p in self.panels:
            p.refresh()


class NationalCupPanel(QWidget):
    """Coupe d'un pays : toutes les divisions s'affrontent. Les tours se jouent automatiquement pendant la saison."""

    def __init__(self, win: "MainWindow", country: str):
        super().__init__()
        self.win, self.country = win, country
        layout = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.zoom_view = ZoomBracket()
        self.bracket = self.zoom_view.bracket
        self.bracket.matchClicked.connect(self.show_match)
        layout.addWidget(self.zoom_view, 1)
        layout.addWidget(QLabel("<small>Les tours se jouent aux journées indiquées, avec les mêmes joueurs que le "
                                "championnat (un suspendu ou un blessé ne joue pas non plus la coupe). Les petites "
                                "divisions jouent un tour de barrages plus tôt. Clique sur un match joué pour le "
                                "détail.</small>"))

    def refresh(self):
        world = self.win.world
        cup = world.cups.get(self.country)
        self.bracket.set_cup(cup, world)
        if cup is None:
            self.info.setText("Pas de coupe.")
            return
        if cup.finished:
            state = f"🏆 Vainqueur : <b>{cup.champion.name}</b> (division {cup.champion.division})"
        else:
            index = len(cup.rounds)
            state = f"Prochain tour : <b>{cup.next_round_name}</b> (journée {cup.round_days[index]})"
        self.info.setText(f"{describe_structure(len(cup.teams))} (toutes divisions). {state}")

    def show_match(self, cm):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Coupe {self.country} : {cm.round_name}")
        lay = QVBoxLayout(dlg)
        view = MatchDetailView()
        view.show_match(self.win.world, cm.result, pens=cm.pens, round_label=cm.round_name)
        lay.addWidget(view)
        dlg.resize(560, 760)
        dlg.exec()


class NationalCupTab(QTabWidget):
    """Une coupe nationale par pays (un onglet avec drapeau pour chacun)."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self._countries: list = []
        self.panels: list = []

    def refresh(self):
        countries = list(self.win.world.countries)
        if countries != self._countries:
            current = self.currentIndex()
            self.clear()
            self.panels = []
            for c in countries:
                panel = NationalCupPanel(self.win, c)
                self.panels.append(panel)
                self.addTab(panel, flag_icon(c, 22), c)
            self._countries = countries
            self.setCurrentIndex(max(0, min(current, len(countries) - 1)))
        for panel in self.panels:
            panel.refresh()


class PalmaresDialog(QDialog):
    """Palmarès de toutes les saisons : champions, coupes nationales, coupes interligue."""

    def __init__(self, world: World, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Palmarès")
        rows = world.palmares()
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        seasons = sorted({r[0] for r in rows})
        for kind, title in (("league1", "🏆 Champions (division 1)"), ("cup", "🏅 Coupes nationales")):
            table = SortTable()
            setup_table(table, ["Saison"] + list(world.countries), 30)
            table.setRowCount(len(seasons))
            data = {(s, c): name for s, c, k, name in rows if k == kind}
            for i, s in enumerate(seasons):
                table.setItem(i, 0, cell(s, bold=True))
                for j, c in enumerate(world.countries, start=1):
                    table.setItem(i, j, cell(data.get((s, c), ""), "left"))
            for j in range(1, len(world.countries) + 1):
                table.horizontalHeader().setSectionResizeMode(j, QHeaderView.ResizeMode.Stretch)
                table.horizontalHeaderItem(j).setIcon(flag_icon(world.countries[j - 1], 22))
            tabs.addTab(table, title)
        table = SortTable()
        setup_table(table, ["Saison", "🔵 Interligue 1", "🟠 Interligue 2"], 30)
        table.setRowCount(len(seasons))
        for i, s in enumerate(seasons):
            table.setItem(i, 0, cell(s, bold=True))
            for j, kind in ((1, "interleague1"), (2, "interleague2")):
                match = next(((c, name) for s2, c, k, name in rows if s2 == s and k == kind), None)
                table.setItem(i, j, cell(match[1] if match else "", "left",
                                         icon=flag_icon(match[0], 22) if match else None))
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tabs.addTab(table, "🌍 Coupes interligue")
        if not seasons:
            layout.addWidget(QLabel("<i>Aucune saison terminée : clique sur « Saison suivante » pour archiver la "
                                    "saison (champions, coupes, historique des équipes).</i>"))
        self.resize(780, 520)


class CalendarTab(QWidget):
    """Calendrier d'un pays, journée par journée : toutes ses divisions + coupes (nationale et interligue)."""
    HEADERS = ["Compétition", "Domicile", "Score", "Extérieur", "Affluence"]

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.rows: list = []
        self._following = True
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>Pays :</b>"))
        self.country = QComboBox()
        self.country.currentIndexChanged.connect(self.on_country)
        bar.addWidget(self.country)
        bar.addSpacing(20)
        bar.addWidget(QLabel("<b>Journée :</b>"))
        prev_btn, next_btn, now_btn = QPushButton("◀"), QPushButton("▶"), QPushButton("Dernière jouée")
        self.day = QSpinBox()
        self.day.setRange(1, 1)
        self.day.valueChanged.connect(self.on_day)
        prev_btn.clicked.connect(lambda: self.day.setValue(self.day.value() - 1))
        next_btn.clicked.connect(lambda: self.day.setValue(self.day.value() + 1))
        now_btn.clicked.connect(lambda: self.day.setValue(max(1, self.win.world.played)))
        self.total = QLabel()
        for w in (prev_btn, self.day, next_btn, self.total, now_btn):
            bar.addWidget(w)
        bar.addStretch()
        layout.addLayout(bar)

        self.grid_area = QScrollArea()
        self.grid_area.setWidgetResizable(True)
        self.grid_area.setMaximumHeight(176)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(4)
        self.grid_area.setWidget(self.grid_host)
        self.day_buttons: dict = {}
        layout.addWidget(self.grid_area)
        layout.addWidget(QLabel("<small>⚽ championnat · 🏆 coupe nationale · 🏅 coupe interligue — "
                                "<span style='background:#d6efdb'>&nbsp;journée jouée&nbsp;</span> "
                                "<span style='background:#f0f0f0'>&nbsp;à venir&nbsp;</span> · bordure dorée = journée "
                                "de coupe. Clique sur une journée pour voir ses matchs.</small>"))
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.table = SortTable()
        setup_table(self.table, self.HEADERS, 34)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(4, 90)
        self.table.cellDoubleClicked.connect(self.open_match)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel(f"<small><span style='color:{GREEN}'>■</span> gagnante | "
                                f"<span style='color:{RED}'>■</span> perdante | grise = nul. Les journées à venir "
                                "montrent les affiches prévues. Double-clic sur un match joué pour le détail.</small>"))

    def refresh(self):
        world = self.win.world
        current = self.country.currentData()
        self.country.blockSignals(True)
        self.country.clear()
        for c in world.countries:
            self.country.addItem(flag_icon(c, 24), c, c)
        self.country.setCurrentIndex(max(0, self.country.findData(current or self.win.league.country)))
        self.country.blockSignals(False)
        self.day.blockSignals(True)
        self.day.setRange(1, world.total_days)
        if self._following:
            self.day.setValue(max(1, world.played))
        self.day.blockSignals(False)
        self.total.setText(f"/ {world.total_days}")
        self.build_grid()
        self.render()

    def on_country(self, *_):
        self.build_grid()
        self.render()

    def build_grid(self):
        """Une case par journée : ⚽ championnat, 🏆 coupe nationale, 🏅 coupe interligue. Un clic ouvre la journée."""
        world, country = self.win.world, self.country.currentData()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.day_buttons = {}
        national = world.cups.get(country)
        inter = [("Interligue 1", world.interleague.get("blue")), ("Interligue 2", world.interleague.get("orange"))]
        columns = 14
        for d in range(1, world.total_days + 1):
            icons, tips = ["⚽"], ["Championnat"]
            if national and d in national.round_days:
                icons.append("🏆")
                tips.append(f"Coupe {country} : {national.round_defs[national.round_days.index(d)][0]}")
            for label, cup in inter:
                if cup is not None and d in cup.round_days:
                    icons.append("🏅")
                    tips.append(f"{label} : {cup.round_defs[cup.round_days.index(d)][0]}")
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setText(f"J{d}\n{' '.join(icons)}")
            button.setToolTip(f"Journée {d} — " + " · ".join(tips))
            button.setFixedSize(66, 42)
            border = "#d4a017" if len(icons) > 1 else "#bbbbbb"
            background = "#d6efdb" if d <= world.played else "#f0f0f0"
            button.setStyleSheet(f"QToolButton {{ background: {background}; border: 2px solid {border}; "
                                 f"border-radius: 6px; color: #222; }} "
                                 f"QToolButton:checked {{ background: #bcd4f7; border-color: #2f6fd6; }}")
            button.clicked.connect(lambda _checked=False, day=d: self.day.setValue(day))
            self.grid.addWidget(button, (d - 1) // columns, (d - 1) % columns)
            self.day_buttons[d] = button
        self.sync_grid()

    def sync_grid(self):
        button = self.day_buttons.get(self.day.value())
        if button is not None:
            button.setChecked(True)

    def on_day(self, *_):
        self._following = self.day.value() >= self.win.world.played       # on suit la saison tant qu'on est à jour
        self.render()

    def render(self, *_):
        world = self.win.world
        country, day = self.country.currentData(), self.day.value()
        self.sync_grid()
        rows = []                                    # (compétition, id dom., id ext., résultat, tirs au but, étiquette)
        for (c, division), lg in world.competitions.items():
            if c != country:
                continue
            season = lg.season
            played = season.matchdays[day - 1] if day <= season.played else None
            for k, (h, a) in enumerate(season.schedule[day - 1]):
                rows.append((f"Division {division}", h, a, played[k] if played else None, None, f"Division {division}"))
        cups = [(f"Coupe {country}", world.cups.get(country), False),
                ("Interligue 1", world.interleague.get("blue"), True), ("Interligue 2", world.interleague.get("orange"), True)]
        for label, cup, interleague in cups:
            if cup is None or day not in cup.round_days:
                continue
            index = cup.round_days.index(day)
            if index < len(cup.rounds):
                for cm in cup.rounds[index]:
                    if interleague and country not in (world.teams[cm.home_id].country, world.teams[cm.away_id].country):
                        continue
                    rows.append((f"{label} · {cm.round_name}", cm.home_id, cm.away_id, cm.result, cm.pens, label))
            else:
                rows.append((f"{label} · {cup.round_defs[index][0]}", None, None, None, None, label))
        self.rows = rows
        self.table.setRowCount(len(rows))
        for i, (comp, h, a, result, pens, _label) in enumerate(rows):
            if result is None:
                bg_home = bg_away = bg_other = None
            elif result.home_goals == result.away_goals and not pens:
                bg_home = bg_away = bg_other = DRAW_BG
            else:
                home_won = result.home_goals > result.away_goals or (pens is not None and pens[0] > pens[1])
                bg_home, bg_away = (WIN_BG, LOSS_BG) if home_won else (LOSS_BG, WIN_BG)
                bg_other = None
            first = cell(comp, "left", bold=comp.startswith("Coupe") or comp.startswith("Inter"), bg=bg_other)
            first.setData(Qt.ItemDataRole.UserRole, i)
            self.table.setItem(i, 0, first)
            for col, tid, bg in ((1, h, bg_home), (3, a, bg_away)):
                team = world.teams.get(tid) if tid is not None else None
                self.table.setItem(i, col, cell(team.name if team else "à déterminer", "left",
                                                color=None if team else GREY, icon=logo_icon(team) if team else None, bg=bg))
            if result is None:
                score, crowd = ("à jouer" if h is not None else "—"), ""
            else:
                score = f"{result.home_goals} - {result.away_goals}" + (f" ({pens[0]}-{pens[1]} tab)" if pens else "")
                crowd = f"{result.attendance:,}".replace(",", " ")
            self.table.setItem(i, 2, cell(score, bold=result is not None, color=None if result else GREY, bg=bg_other))
            self.table.setItem(i, 4, cell(crowd, color=GREY, bg=bg_other))
        played_count = sum(1 for r in rows if r[3] is not None)
        self.summary.setText(f"<b>Journée {day}</b> · {len(rows)} match(s) ou tour(s) prévu(s), {played_count} joué(s)")

    def open_match(self, row, _col):
        index = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        comp, h, a, result, pens, _ = self.rows[index]
        if result is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(comp)
        lay = QVBoxLayout(dlg)
        view = MatchDetailView()
        view.show_match(self.win.world, result, pens=pens, round_label=comp)
        lay.addWidget(view)
        dlg.resize(560, 760)
        dlg.exec()


class FriendlyTab(QWidget):
    """Matchs amicaux : n'importe quelle équipe contre n'importe quelle équipe (aucun effet sur la saison)."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer = QHBoxLayout(self)
        outer.addWidget(splitter)

        left = QWidget()
        lv = QVBoxLayout(left)
        box = QGroupBox("Organiser un match amical")
        form = QFormLayout(box)
        self.home = QComboBox()
        self.away = QComboBox()
        for combo in (self.home, self.away):
            combo.setMinimumWidth(300)
            combo.setMaxVisibleItems(18)
            combo.currentIndexChanged.connect(self.update_hint)
        form.addRow("Domicile :", self.home)
        form.addRow("Extérieur :", self.away)
        self.neutral = QCheckBox("Terrain neutre")
        form.addRow("", self.neutral)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        form.addRow(self.hint)
        lv.addWidget(box)

        row = QHBoxLayout()
        play = QPushButton("▶  Jouer le match amical")
        play.clicked.connect(self.play)
        swap = QPushButton("⇄  Inverser")
        swap.clicked.connect(self.swap)
        row.addWidget(play, 1)
        row.addWidget(swap)
        lv.addLayout(row)
        fun = QPushButton("⚔  Meilleure équipe du monde  vs  pire équipe du monde")
        fun.setToolTip("Prépare le match (et le joue) : la meilleure note contre la moins bonne")
        fun.clicked.connect(self.best_vs_worst)
        lv.addWidget(fun)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        lv.addWidget(self.banner)

        lv.addWidget(QLabel("<b>Amicaux joués</b>"))
        self.table = SortTable()
        self.rows: list = []
        setup_table(self.table, ["Domicile", "Score", "Extérieur", "Affluence"], 32)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(3, 80)
        self.table.itemSelectionChanged.connect(self.show_selected)
        lv.addWidget(self.table, 1)
        lv.addWidget(QLabel("<small>Effectifs complets, pas de cartons ni de blessures, aucun effet sur le "
                            "championnat ni les statistiques.</small>"))
        self.detail = MatchDetailView()
        splitter.addWidget(left)
        splitter.addWidget(self.detail)
        splitter.setSizes([520, 560])

    def refresh(self):
        world = self.win.world
        ordered = sorted(world.teams.values(), key=lambda t: (-t.overall_rating, t.id))
        keep = (self.home.currentData(), self.away.currentData())
        for combo, wanted in ((self.home, keep[0]), (self.away, keep[1])):
            combo.blockSignals(True)
            combo.clear()
            for t in ordered:
                combo.addItem(logo_icon(t), f"{t.name}  ·  {t.country} D{t.division}  ·  note {t.overall_rating:.1f}", t.id)
            idx = combo.findData(wanted)
            combo.setCurrentIndex(idx if idx >= 0 else (0 if combo is self.home else min(1, combo.count() - 1)))
            combo.blockSignals(False)
        self.update_hint()
        self.render_history()

    def update_hint(self, *_):
        world = self.win.world
        h, a = self.home.currentData(), self.away.currentData()
        if h is None or a is None:
            return
        if h == a:
            self.hint.setText(f"<span style='color:{RED}'>Choisis deux équipes différentes.</span>")
            return
        th, ta = world.teams[h], world.teams[a]
        gap = th.overall_rating - ta.overall_rating
        self.hint.setText(f"<span style='color:{GREY}'>Écart de note : {gap:+.1f} "
                          f"({th.short} {th.overall_rating:.1f} · {ta.short} {ta.overall_rating:.1f})</span>")

    def swap(self):
        h, a = self.home.currentData(), self.away.currentData()
        self.home.setCurrentIndex(self.home.findData(a))
        self.away.setCurrentIndex(self.away.findData(h))

    def best_vs_worst(self):
        world = self.win.world
        best = max(world.teams.values(), key=lambda t: (t.overall_rating, -t.id))
        worst = min(world.teams.values(), key=lambda t: (t.overall_rating, t.id))
        self.home.setCurrentIndex(self.home.findData(best.id))
        self.away.setCurrentIndex(self.away.findData(worst.id))
        self.play()

    def play(self):
        world = self.win.world
        try:
            result = world.play_friendly(self.home.currentData(), self.away.currentData(), self.neutral.isChecked())
        except ValueError as error:
            QMessageBox.warning(self, "Match impossible", str(error))
            return
        home, away = world.teams[result.home_id], world.teams[result.away_id]
        diff = result.home_goals - result.away_goals
        verdict = ("💥 <b>Une correction !</b>" if abs(diff) >= 3 else "Match nul." if diff == 0 else
                   f"Victoire de <b>{home.name if diff > 0 else away.name}</b>.")
        self.banner.setText(f"<span style='font-size:15px'><b>{home.name} {result.home_goals} - {result.away_goals} "
                            f"{away.name}</b></span><br>{verdict}")
        self.render_history(select=len(world.friendlies) - 1)

    def render_history(self, select: int | None = None):
        world = self.win.world
        self.rows = list(world.friendlies)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for i in range(len(self.rows) - 1, -1, -1):                      # le plus récent d'abord
            m = self.rows[i]
            row = len(self.rows) - 1 - i
            home, away = world.teams[m.home_id], world.teams[m.away_id]
            if m.home_goals == m.away_goals:
                bg_h = bg_a = bg_o = DRAW_BG
            else:
                won = m.home_goals > m.away_goals
                bg_h, bg_a = (WIN_BG, LOSS_BG) if won else (LOSS_BG, WIN_BG)
                bg_o = None
            first = cell(home.name, "left", bold=m.home_goals > m.away_goals, icon=logo_icon(home), bg=bg_h)
            first.setData(Qt.ItemDataRole.UserRole, i)
            self.table.setItem(row, 0, first)
            self.table.setItem(row, 1, cell(f"{m.home_goals} - {m.away_goals}", bold=True, size=12, bg=bg_o))
            self.table.setItem(row, 2, cell(away.name, "left", bold=m.away_goals > m.home_goals,
                                            icon=logo_icon(away), bg=bg_a))
            self.table.setItem(row, 3, cell(f"{m.attendance:,}".replace(",", " "), color=GREY, bg=bg_o))
        self.table.blockSignals(False)
        if self.rows:
            self.table.selectRow(0)
            self.show_selected()
        else:
            self.detail.clear_match()

    def show_selected(self):
        selected = self.table.selectionModel().selectedRows()
        if selected:
            index = self.table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)
            self.detail.show_match(self.win.world, self.rows[index], round_label="Match amical")


# =============================================================================
# 11. NOUVELLE LIGUE
# =============================================================================
class NewLeagueDialog(QDialog):
    def __init__(self, world: World, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau monde")
        form = QFormLayout(self)
        self.countries = QListWidget()
        self.countries.setMinimumHeight(180)
        for name in Faker().get_countries():
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in world.countries else Qt.CheckState.Unchecked)
            self.countries.addItem(item)
        self.countries.itemChanged.connect(self.update_info)
        self.divisions = QSpinBox()
        self.divisions.setRange(1, MAX_DIVISIONS)
        self.divisions.setValue(world.n_divisions)
        self.teams = QSpinBox()
        self.teams.setRange(MIN_TEAMS, MAX_TEAMS)
        self.teams.setSingleStep(2)
        self.teams.setValue(world.n_teams_per_division)
        self.seed = QSpinBox()
        self.seed.setRange(0, 10 ** 9)
        self.seed.setValue(42)
        self.info = QLabel()
        self.info.setWordWrap(True)
        for w in (self.divisions, self.teams):
            w.valueChanged.connect(self.update_info)
        form.addRow(f"Pays (1 à {MAX_COUNTRIES}) :", self.countries)
        form.addRow("Divisions par pays :", self.divisions)
        form.addRow("Équipes par division (pair) :", self.teams)
        form.addRow("Graine (seed) :", self.seed)
        form.addRow(self.info)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.update_info()

    def selected(self) -> list:
        return [self.countries.item(i).text() for i in range(self.countries.count())
                if self.countries.item(i).checkState() == Qt.CheckState.Checked]

    def update_info(self, *_):
        n = self.teams.value()
        if n % 2:
            self.teams.setValue(n + 1 if n < MAX_TEAMS else n - 1)
            return
        k = len(self.selected())
        ok = 1 <= k <= MAX_COUNTRIES
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        b, o, r = league_zones(n)
        self.info.setText(f"{k} pays x {self.divisions.value()} division(s) x {n} équipes = "
                          f"{k * self.divisions.value() * n} clubs, {2 * (n - 1)} journées.<br>"
                          f"Division 1 : {b} bleus, {o} oranges, {r} relégués ; "
                          f"divisions inférieures : {r} promus." if ok else
                          f"<span style='color:{RED}'>Choisis entre 1 et {MAX_COUNTRIES} pays.</span>")


# =============================================================================
# 12. FENÊTRE PRINCIPALE
# =============================================================================
class MainWindow(QMainWindow):
    def __init__(self, world: World):
        super().__init__()
        self.world = world
        self.current = (world.countries[0], 1)
        self._updating = False
        self.resize(1280, 800)

        toolbar = QToolBar("Actions")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)

        def action(text, slot, bar=toolbar):
            a = QAction(text, self)
            a.triggered.connect(slot)
            bar.addAction(a)
            return a

        self.country_combo, self.division_combo = QComboBox(), QComboBox()
        toolbar.addWidget(QLabel(" Championnat : "))
        toolbar.addWidget(self.country_combo)
        toolbar.addWidget(self.division_combo)
        toolbar.addSeparator()
        self.next_action = action("▶  Journée suivante", lambda: self.advance(1))
        self.until_action = action("⏩  Jusqu'à la journée…", self.advance_until)
        self.all_action = action("⏭  Simuler toute la ligue", lambda: self.advance(None))
        self.season_action = action("➡  Saison suivante", self.next_season)
        toolbar.addSeparator()
        self.restart_action = action("↺  Rejouer la saison", self.restart_season)
        action("🔄  Nouveau monde…", self.new_league)
        action("🏛  Palmarès", self.show_history)
        self.country_action = action("＋  Ajouter un pays…", self.add_country)
        self.add_export_menu(toolbar)
        self.add_options_menu(toolbar)
        action("ℹ  Modèle de calcul", self.show_model)
        self.day_label = QLabel()
        self.statusBar().addPermanentWidget(self.day_label)

        self.tabs = QTabWidget()
        self.standings = StandingsTab(self)
        self.matches = MatchesTab(self)
        self.teams_tab = TeamsTab(self)
        self.transfers = TransfersTab(self)
        self.scorers = StatsTab(self, "goals")
        self.assists = StatsTab(self, "assists")
        self.national_tab = NationalCupTab(self)
        self.cup_tab = CupTab(self)
        self.calendar_tab = CalendarTab(self)
        self.friendly_tab = FriendlyTab(self)
        self.all_tabs = (self.standings, self.matches, self.teams_tab, self.transfers, self.scorers,
                         self.assists, self.national_tab, self.cup_tab, self.calendar_tab, self.friendly_tab)
        for widget, title in ((self.standings, "🏆 Classement"), (self.matches, "⚽ Matchs"),
                              (self.teams_tab, "👥 Équipes"), (self.transfers, "🔁 Transferts"),
                              (self.scorers, "🥇 Buteurs"), (self.assists, "🎯 Passeurs"),
                              (self.national_tab, "🏆 Coupe nationale"), (self.cup_tab, "🏅 Coupes interligue"),
                              (self.calendar_tab, "📅 Calendrier"), (self.friendly_tab, "🤝 Amicaux")):
            self.tabs.addTab(widget, title)
        self.setCentralWidget(self.tabs)
        self.fill_selectors()
        self.country_combo.currentIndexChanged.connect(self.on_selector)
        self.division_combo.currentIndexChanged.connect(self.on_selector)
        self.refresh_all()

    @property
    def league(self) -> League:
        """Le championnat affiché (pays + division sélectionnés)."""
        return self.world.competitions[self.current]

    # ---- sélection du championnat
    def fill_selectors(self):
        self._updating = True
        self.country_combo.clear()
        for c in self.world.countries:
            self.country_combo.addItem(flag_icon(c, 24), c)
        self.country_combo.setCurrentText(self.current[0])
        self.division_combo.clear()
        for d in range(1, self.world.n_divisions + 1):
            self.division_combo.addItem(f"Division {d}", d)
        self.division_combo.setCurrentIndex(self.current[1] - 1)
        self._updating = False

    def on_selector(self):
        if self._updating:
            return
        self.current = (self.country_combo.currentText(), self.division_combo.currentData() or 1)
        self.refresh_all()

    # ---- simulation (tous les championnats avancent ensemble)
    def advance(self, days):
        """days = nombre de journées à jouer, ou None pour finir toute la saison."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.world.play_all() if days is None else self.world.play_days(days)
            self.refresh_all()
        finally:
            QApplication.restoreOverrideCursor()
        if self.world.finished:
            champion = self.league.teams[self.league.season.result.final_table[0].team_id]
            self.statusBar().showMessage(f"Saison terminée ({self.league.label}) : champion {champion.name}", 8000)

    def advance_until(self):
        world = self.world
        if world.finished:
            return
        day, ok = QInputDialog.getInt(self, "Simuler jusqu'à…", f"Jouer jusqu'à la journée (sur {world.total_days}) :",
                                      min(world.played + 5, world.total_days), world.played + 1, world.total_days)
        if ok:
            self.advance(day - world.played)

    def add_options_menu(self, toolbar):
        """Menu Options : boutons bascule (cartons, blessures, bonus d'affluence)."""
        button = QToolButton()
        button.setText("⚙  Options")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        for text, attr, tip in (
                ("🟨  Cartons et suspensions", "cards", "Cartons jaunes / rouges, suspensions, jeu à 10"),
                ("🩹  Blessures", "injuries", "Blessures de plusieurs matchs, selon la résistance des joueurs"),
                ("👥  Bonus d'affluence à domicile", "crowd_bonus", "Un stade plein donne un petit bonus à domicile"),
                ("🔁  Promotions et relégations", "relegation",
                 "Décoché : les divisions restent figées d'une saison à l'autre"),
                ("🏟  Coupes interligue : phase de poules", "interleague_groups",
                 "Poules de 4 puis élimination directe (au lieu de l'élimination directe seule)"),
                ("💰  Budget strict (bloque les transferts trop chers)", "finance_strict",
                 "Désactivé : les finances sont seulement indicatives")):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(getattr(OPTIONS, attr))
            act.setToolTip(tip)
            act.toggled.connect(lambda value, a=attr: self.set_option(a, value))
        button.setMenu(menu)
        toolbar.addWidget(button)

    def set_option(self, attr: str, value: bool):
        setattr(OPTIONS, attr, value)
        if attr == "interleague_groups":
            self.world.rebuild_interleague_if_unplayed()
        if attr in ("relegation", "interleague_groups"):   # le classement / les coupes changent tout de suite
            self.refresh_all()
        self.statusBar().showMessage("Option modifiée : elle s'applique à partir de la prochaine journée jouée "
                                     "(les suspensions et blessures en cours se terminent normalement).", 6000)

    def add_export_menu(self, toolbar):
        button = QToolButton()
        button.setText("📤  Exporter (CSV)")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        menu.addAction("Le tableau affiché dans cet onglet…", self.export_current_table)
        menu.addAction("Toutes les données (un dossier de fichiers CSV)…", self.export_everything)
        menu.addAction("Astuce : clic droit sur n'importe quel tableau").setEnabled(False)
        button.setMenu(menu)
        toolbar.addWidget(button)

    def export_current_table(self):
        page = self.tabs.currentWidget()
        tables = [t for t in page.findChildren(SortTable) if t.isVisible() and t.rowCount() > 0]
        if not tables:
            QMessageBox.information(self, "Export", "Aucun tableau rempli dans cet onglet.")
            return
        table = tables[0]
        if len(tables) > 1:
            labels = [f"{i + 1}. " + ", ".join(h for h in table_.table_rows()[0][:5] if h) for i, table_ in enumerate(tables)]
            choice, ok = QInputDialog.getItem(self, "Exporter", "Quel tableau ?", labels, 0, False)
            if not ok:
                return
            table = tables[labels.index(choice)]
        table.export_dialog(self)

    def export_everything(self):
        folder = QFileDialog.getExistingDirectory(self, "Dossier où écrire les fichiers CSV")
        if not folder:
            return
        target = os.path.join(folder, f"export_saison{self.world.season_number}_journee{self.world.played}")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            files = export_all(self.world, target)
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Export terminé", f"{len(files)} fichiers CSV écrits dans :\n{target}\n\n"
                                + "\n".join(files))

    def add_country(self):
        remaining = [c for c in Faker().get_countries() if c not in self.world.countries]
        if not remaining:
            QMessageBox.information(self, "Ajouter un pays", "Tous les pays sont déjà dans le monde.")
            return
        default = remaining.index("Portugal") if "Portugal" in remaining else 0
        name, ok = QInputDialog.getItem(self, "Ajouter un pays", "Pays à ajouter (mêmes divisions et nombre "
                                        "d'équipes que les autres) :", remaining, default, False)
        if not ok:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.world.add_country(name)
            self.current = (name, 1)
            self.fill_selectors()
            self.refresh_all()
            self.statusBar().showMessage(f"{name} ajouté : {self.world.n_divisions} division(s) de "
                                         f"{self.world.n_teams_per_division} équipes.", 8000)
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Ajout impossible", str(error))
        finally:
            QApplication.restoreOverrideCursor()

    def restart_season(self):
        self.world.start_season()
        self.cup_tab.reset()
        self.refresh_all()
        self.statusBar().showMessage("Saison relancée à la journée 0", 5000)

    def next_season(self):
        if not self.world.finished:
            return
        multi = self.world.n_divisions > 1
        text = ("Les 2 derniers de chaque division montent / descendent d'une division, "
                "puis une nouvelle saison commence." if multi and OPTIONS.relegation else
                "Une nouvelle saison commence (divisions inchangées)." if multi else "Une nouvelle saison commence.")
        if QMessageBox.question(self, "Saison suivante", text + "\nLes coupes interligue de la saison suivante seront "
                                "formées avec les qualifiés de cette saison. Continuer ?") != QMessageBox.StandardButton.Yes:
            return
        entry = self.world.next_season()
        self.cup_tab.reset()
        self.refresh_all()
        self.statusBar().showMessage(f"Saison {self.world.season_number} : {len(entry['promoted'])} promus, "
                                     f"{len(entry['relegated'])} relégués", 8000)

    def rerun_full(self):
        """Après un transfert : on rejoue ce championnat avec les nouveaux effectifs."""
        self.world.start_season()
        self.cup_tab.reset()
        self.advance(None)

    def show_history(self):
        PalmaresDialog(self.world, self).exec()

    def update_status(self):
        w = self.world
        self.day_label.setText(f"Saison {w.season_number}  |  Journée {w.played} / {w.total_days}"
                               + ("  ✔ terminée" if w.finished else ""))
        for a in (self.next_action, self.until_action, self.all_action):
            a.setEnabled(not w.finished)
        self.season_action.setEnabled(w.finished)
        self.country_action.setEnabled(w.played == 0 and len(w.countries) < MAX_COUNTRIES)
        self.country_action.setToolTip("Possible avant le début de la saison (journée 0)")
        self.setWindowTitle(f"Simulation — {len(w.countries)} pays, {w.n_divisions} division(s) — "
                            f"{self.league.label}")

    def refresh_all(self):
        self.update_status()
        for tab in self.all_tabs:
            tab.refresh()

    def open_team(self, team_id: int):
        self.teams_tab.select_team(team_id)
        self.tabs.setCurrentWidget(self.teams_tab)

    def new_league(self):
        dlg = NewLeagueDialog(self.world, self)
        if not dlg.exec():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.world._create(dlg.seed.value(), dlg.selected(), dlg.divisions.value(), dlg.teams.value())
            self.current = (self.world.countries[0], 1)
            self.fill_selectors()
            self.cup_tab.reset()
            self.refresh_all()
        except (ValueError, RuntimeError) as error:
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
    parser.add_argument("--countries", type=int, default=5, help="nombre de pays (1 à 8) si un monde est créé")
    parser.add_argument("--divisions", type=int, default=2, help="divisions par pays (1 à 3)")
    parser.add_argument("--teams", type=int, default=20, help="équipes par division (pair, 8 à 32)")
    parser.add_argument("--new", action="store_true", help="recrée un nouveau monde même s'il en existe déjà un")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if not os.path.exists(args.db):
        QMessageBox.critical(None, "Base introuvable",
                             f"Le fichier {args.db} n'existe pas.\nGénère-le d'abord avec le script de génération.")
        sys.exit(1)
    app.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        world = World.load_or_create(args.db, seed=args.seed, force_new=args.new,
                                     countries=DEFAULT_COUNTRIES[:max(1, min(args.countries, MAX_COUNTRIES))],
                                     n_divisions=args.divisions, n_teams=args.teams)
    except (ValueError, RuntimeError) as error:
        app.restoreOverrideCursor()
        QMessageBox.critical(None, "Création impossible", str(error))
        sys.exit(1)
    app.restoreOverrideCursor()
    window = MainWindow(world)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
