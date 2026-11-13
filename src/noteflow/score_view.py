"""Draw numbered notation on a centered sheet in the workspace."""

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen

from .desktop_theme import COLORS
from PySide6.QtWidgets import QWidget

from .score import KEYS, Score, to_text


class ScoreView(QWidget):
    MARGIN = 36
    PAPER_INSET = 16
    PAPER_MAX_WIDTH = 1080
    note_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.score: Score | None = None
        self.active_note = None
        self._empty_message = "将音频或视频拖到这里"
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow)
        self.setAccessibleName("数字简谱")
        self.setAccessibleDescription(self._empty_message)

    def set_media_available(self, available):
        self._empty_message = "点击「生成简谱」开始识别" if available else "将音频或视频拖到这里"
        if self.score is None:
            self.setAccessibleDescription(self._empty_message)
            self.update()

    def set_score(self, score: Score | None):
        self.score = score
        self.setAccessibleDescription(to_text(score) if score else self._empty_message)
        self._reflow_timer.start()
        self.update()

    def set_active_note(self, note_id):
        if self.active_note != note_id:
            self.active_note = note_id
            self.update()

    def mousePressEvent(self, event):
        if self.score:
            for token, x, y, slot, count in self._layout()[0]:
                if token.note_id and QRectF(x - slot / 2, y - 15, slot * count, 60).contains(event.position()):
                    self.note_clicked.emit(token.note_id)
                    break
        super().mousePressEvent(event)

    def _notation_font(self):
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(16, self.font().pointSizeF() * 1.45))
        return font

    def _paper(self):
        inset = max(self.PAPER_INSET, (self.width() - self.PAPER_MAX_WIDTH) / 2)
        return QRectF(inset, self.PAPER_INSET, self.width() - 2 * inset, self.height() - 2 * self.PAPER_INSET)

    def _layout(self):
        metrics = QFontMetrics(self._notation_font())
        slot = max(27, metrics.horizontalAdvance("♭7") + 8)
        row_height = max(92, metrics.height() + 54)
        paper = self._paper()
        margin = paper.left() + self.MARGIN
        limit = paper.right() - self.MARGIN
        x, y = margin, 106
        tokens, bars = [], []
        for index, measure in enumerate(self.score.measures, 1):
            width = sum(slot * (1 + {960: 1, 1920: 3}.get(token.duration_tick, 0)) for token in measure) + 14
            # Fit a dense measure in a narrow window while retaining whole-bar wrapping.
            scale = min(1.0, max(0.5, (limit - margin) / width))
            if x > margin and x + width * scale > limit:
                x, y = margin, y + row_height
            start = x
            for token in measure:
                count = 1 + {960: 1, 1920: 3}.get(token.duration_tick, 0)
                tokens.append((token, x + slot * scale / 2, y, slot * scale, count))
                x += slot * scale * count
            bars.append((index, start, x + 4 * scale, y))
            x += 14 * scale
        return tokens, bars, y + row_height + self.PAPER_INSET

    def _reflow(self):
        self.setMinimumHeight(self._layout()[2] if self.score else 200)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self._reflow_timer.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(event.rect(), QColor(COLORS["window"]))
        paper = self._paper()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0f1116"))
        painter.drawRoundedRect(paper.translated(0, 3), 6, 6)
        painter.setBrush(QColor("#faf8f2"))
        painter.drawRoundedRect(paper, 6, 6)
        text = QColor("#202638")
        painter.setPen(text)
        if not self.score:
            center = self.rect().center()
            x, y = center.x(), center.y() - 24
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e5e8f7"))
            painter.drawRoundedRect(QRectF(x - 27, y - 35, 54, 54), 14, 14)
            painter.setPen(QPen(QColor("#5363a9"), 2.3))
            painter.drawLine(QPointF(x + 7, y - 24), QPointF(x + 7, y + 3))
            painter.drawLine(QPointF(x + 7, y - 24), QPointF(x + 18, y - 18))
            painter.setBrush(QColor("#5363a9"))
            painter.drawEllipse(QRectF(x - 6, y - 1, 13, 9))
            font = QFont(self.font())
            font.setPixelSize(15)
            painter.setFont(font)
            painter.setPen(QColor("#525b71"))
            painter.drawText(QRectF(0, y + 32, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                             self._empty_message)
            return

        settings = self.score.settings
        start = paper.left() + self.MARGIN
        painter.setPen(QColor("#525b71"))
        painter.drawText(QPointF(start, 52), f"1={KEYS[settings.tonic_pc]}     4/4     BPM {settings.bpm:g}")
        painter.setPen(QColor("#dddde5"))
        painter.drawLine(QPointF(start, 67), QPointF(paper.right() - self.MARGIN, 67))
        tokens, bars, _ = self._layout()
        for index, start, end, y in bars:
            painter.setPen(QColor("#626b7c"))
            painter.drawText(QPointF(start, y - 23), str(index))
            painter.setPen(QColor("#485064"))
            painter.drawLine(QPointF(end, y - 15), QPointF(end, y + 28))

        painter.setPen(text)
        painter.setFont(self._notation_font())
        for index, (token, x, y, slot, count) in enumerate(tokens):
            if token.note_id and token.note_id == self.active_note:
                painter.fillRect(QRectF(x - slot / 2, y - 9, slot * count, 51), QColor("#dce3ff"))
            symbol = f"{token.accidental}{token.degree}"
            painter.drawText(QRectF(x - slot / 2, y, slot, 28), Qt.AlignmentFlag.AlignCenter, symbol)
            for line in range(1, count):
                center = x + slot * line
                painter.drawLine(QPointF(center - 6, y + 15), QPointF(center + 6, y + 15))
            lines = {240: 1, 120: 2}.get(token.duration_tick, 0)
            for line in range(lines):
                baseline = y + 28 + line * 3
                painter.drawLine(QPointF(x - 7, baseline), QPointF(x + 7, baseline))
            for dot in range(abs(token.octave)):
                dot_y = y - 3 - dot * 4 if token.octave > 0 else y + 30 + lines * 3 + dot * 4
                painter.setBrush(text)
                painter.drawEllipse(QPointF(x, dot_y), 1.45, 1.45)
            if token.tie_out:
                _, next_x, next_y, next_slot, _ = tokens[index + 1]
                if next_y == y:
                    self._tie(painter, x + 5, next_x - 5, y - 11)
                else:
                    self._tie(painter, x + 5, x + slot * (count - 0.2), y - 11)
                    self._tie(painter, next_x - next_slot * 0.45, next_x - 4, next_y - 11)

    @staticmethod
    def _tie(painter, start, end, y):
        curve = QPainterPath(QPointF(start, y))
        curve.quadTo((start + end) / 2, y - 10, end, y)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(curve)
