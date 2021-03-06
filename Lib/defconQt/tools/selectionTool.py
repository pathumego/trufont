from defconQt.objects.defcon import TAnchor, TComponent
from defconQt.objects.glyphDialogs import AddAnchorDialog, AddComponentDialog
from defconQt.tools.baseTool import BaseTool
from defconQt.util import platformSpecific
from defconQt.util.uiMethods import moveUISelection, removeUISelection
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QPainter, QTransform
from PyQt5.QtWidgets import QMenu, QRubberBand, QStyle, QStyleOptionRubberBand

arrowKeys = (Qt.Key_Left, Qt.Key_Up, Qt.Key_Right, Qt.Key_Down)
navKeys = (Qt.Key_Less, Qt.Key_Greater)


class SelectionTool(BaseTool):
    name = "Selection"
    iconPath = ":/resources/cursor.svg"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._itemTuple = None
        self._oldSelection = set()
        self._rubberBandRect = None
        self._shouldPrepareUndo = False

    # helpers

    def _createAnchor(self, *args):
        widget = self.parent()
        pos = widget.mapToCanvas(widget.mapFromGlobal(self._cachedPos))
        newAnchorName, ok = AddAnchorDialog.getNewAnchorName(widget, pos)
        if ok:
            anchor = TAnchor()
            anchor.x = pos.x()
            anchor.y = pos.y()
            anchor.name = newAnchorName
            self._glyph.appendAnchor(anchor)

    def _createComponent(self, *args):
        widget = self.parent()
        newGlyph, ok = AddComponentDialog.getNewGlyph(widget, self._glyph)
        if ok and newGlyph is not None:
            component = TComponent()
            component.baseGlyph = newGlyph.name
            self._glyph.appendComponent(component)

    def _getSelectedCandidatePoint(self):
        """
        If there is exactly one point selected in the glyph, return it.

        Else return None.
        """

        candidates = set()
        for contour in self._glyph:
            sel = contour.selection
            if len(sel) > 1:
                return None
            elif not len(sel):
                continue
            pt = next(iter(sel))
            candidates.add((pt, contour))
        if len(candidates) == 1:
            return next(iter(candidates))
        return None

    def _moveForEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        dx, dy = 0, 0
        if key == Qt.Key_Left:
            dx = -1
        elif key == Qt.Key_Up:
            dy = 1
        elif key == Qt.Key_Right:
            dx = 1
        elif key == Qt.Key_Down:
            dy = -1
        if modifiers & Qt.ShiftModifier:
            dx *= 10
            dy *= 10
            if modifiers & Qt.ControlModifier:
                dx *= 10
                dy *= 10
        return (dx, dy)

    # actions

    def showContextMenu(self, pos):
        self._cachedPos = pos
        menu = QMenu(self.parent())
        menu.addAction("Add Anchor…", self._createAnchor)
        menu.addAction("Add Component…", self._createComponent)
        menu.exec_(self._cachedPos)
        self._cachedPos = None

    # events

    def keyPressEvent(self, event):
        key = event.key()
        if key == platformSpecific.deleteKey:
            glyph = self._glyph
            # TODO: prune
            glyph.prepareUndo()
            preserveShape = not event.modifiers() & Qt.ShiftModifier
            for anchor in glyph.anchors:
                if anchor.selected:
                    glyph.removeAnchor(anchor)
            for contour in reversed(glyph):
                removeUISelection(contour, preserveShape)
            for component in glyph.components:
                if component.selected:
                    glyph.removeComponent(component)
        elif key in arrowKeys:
            # TODO: prune
            self._glyph.prepareUndo()
            delta = self._moveForEvent(event)
            # TODO: seems weird that glyph.selection and selected don't incl.
            # anchors and components while glyph.move does... see what glyphs
            # does
            hadSelection = False
            for anchor in self._glyph.anchors:
                if anchor.selected:
                    anchor.move(delta)
                    hadSelection = True
            for contour in self._glyph:
                moveUISelection(contour, delta)
                # XXX: shouldn't have to recalc this
                if contour.selection:
                    hadSelection = True
            for component in self._glyph.components:
                if component.selected:
                    component.move(delta)
                    hadSelection = True
            if not hadSelection:
                event.ignore()
        elif key in navKeys:
            pack = self._getSelectedCandidatePoint()
            if pack is not None:
                point, contour = pack
                point.selected = False
                index = contour.index(point)
                offset = int(key == Qt.Key_Greater) or -1
                newPoint = contour.getPoint(index + offset)
                newPoint.selected = True
                contour.postNotification(
                    notification="Contour.SelectionChanged")

    def mousePressEvent(self, event):
        if event.button() & Qt.RightButton:
            self.showContextMenu(event.globalPos())
            return
        widget = self.parent()
        addToSelection = event.modifiers() & Qt.ShiftModifier
        self._origin = event.localPos()
        self._itemTuple = widget.itemAt(self._origin)
        if self._itemTuple is not None:
            itemUnderMouse, parentContour = self._itemTuple
            if not (itemUnderMouse.selected or addToSelection):
                for anchor in self._glyph.anchors:
                    anchor.selected = False
                for component in self._glyph.components:
                    component.selected = False
                self._glyph.selected = False
            itemUnderMouse.selected = True
            if parentContour is not None:
                parentContour.postNotification(
                    notification="Contour.SelectionChanged")
            self._shouldPrepareUndo = True
        else:
            if addToSelection:
                self._oldSelection = self._glyph.selection
            else:
                for anchor in self._glyph.anchors:
                    anchor.selected = False
                for component in self._glyph.components:
                    component.selected = False
                self._glyph.selected = False
        widget.update()

    def mouseMoveEvent(self, event):
        canvasPos = event.localPos()
        widget = self.parent()
        if self._itemTuple is not None:
            if self._shouldPrepareUndo:
                self._glyph.prepareUndo()
                self._shouldPrepareUndo = False
            dx = canvasPos.x() - self._origin.x()
            dy = canvasPos.y() - self._origin.y()
            for anchor in self._glyph.anchors:
                if anchor.selected:
                    anchor.move((dx, dy))
            for contour in self._glyph:
                moveUISelection(contour, (dx, dy))
            for component in self._glyph.components:
                if component.selected:
                    component.move((dx, dy))
            self._origin = canvasPos
        else:
            self._rubberBandRect = QRectF(self._origin, canvasPos).normalized()
            items = widget.items(self._rubberBandRect)
            points = set(items["points"])
            if event.modifiers() & Qt.ShiftModifier:
                points ^= self._oldSelection
            # TODO: fine-tune this more, maybe add optional args to items...
            if event.modifiers() & Qt.AltModifier:
                points = set(pt for pt in points if pt.segmentType)
            if points != self._glyph.selection:
                # TODO: doing this takes more time than by-contour
                # discrimination for large point count
                self._glyph.selection = points
        widget.update()

    def mouseReleaseEvent(self, event):
        self._itemTuple = None
        self._oldSelection = set()
        self._rubberBandRect = None
        self.parent().update()

    def mouseDoubleClickEvent(self, event):
        widget = self.parent()
        self._itemTuple = widget.itemAt(self._origin)
        if self._itemTuple is not None:
            item, parent = self._itemTuple
            if parent is None:
                return
            point, contour = item, parent
            if point.segmentType is not None:
                self._glyph.prepareUndo()
                point.smooth = not point.smooth
            contour.dirty = True

    # custom painting

    def paint(self, painter):
        if self._rubberBandRect is None:
            return
        widget = self.parent()
        # okay, OS-native rubber band does not support painting with
        # floating-point coordinates
        # paint directly on the widget with unscaled context
        widgetOrigin = widget.mapToWidget(self._rubberBandRect.bottomLeft())
        widgetMove = widget.mapToWidget(self._rubberBandRect.topRight())
        option = QStyleOptionRubberBand()
        option.initFrom(widget)
        option.opaque = False
        option.rect = QRectF(widgetOrigin, widgetMove).toRect()
        option.shape = QRubberBand.Rectangle
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setTransform(QTransform())
        widget.style().drawControl(
            QStyle.CE_RubberBand, option, painter, widget)
        painter.restore()
