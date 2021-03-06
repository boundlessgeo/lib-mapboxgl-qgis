from qgis.core import *
from qgis.utils import iface
import os
import re
import codecs
import json
from PyQt4.QtCore import *
from PyQt4.QtGui import QColor, QImage, QPixmap, QPainter
import math
from collections import OrderedDict
from processing import dataobjects

def qgisLayers():
    return [lay for lay in iface.mapCanvas().layers() if lay.type() == lay.VectorLayer]

def projectToMapbox(folder):
    return toMapbox(qgisLayers(), folder)

def layerToMapbox(layer, folder):
    return toMapbox(folder, [layer])   

def toMapbox(qgislayers, folder):
    layers, sprites = createLayers(folder, qgislayers)
    obj = {
        "version": 8,
        "name": "QGIS project",
        "glyphs": "mapbox://fonts/mapbox/{fontstack}/{range}.pbf",
        "sources": createSources(folder, qgislayers),
        "layers": layers
    }
    if sprites:
        obj["sprite"] = "./sprites"
    with open(os.path.join(folder, "mapbox.json"), 'w') as f:
        json.dump(obj, f)

def createLayers(folder, _layers):
    layers = []
    allSprites = {}
    for layer in _layers:
        sprites, style = processLayer(layer)
        layers.extend(style)
        allSprites.update(sprites)
    saveSprites(folder, allSprites)
    
    return layers, sprites

def saveSprites(folder, sprites):
    if sprites:
        height = max([s.height() for s,s2x in sprites.values()])
        width = sum([s.width() for s,s2x in sprites.values()])
        img = QImage(width, height, QImage.Format_ARGB32)
        img.fill(QColor(Qt.transparent))
        img2x = QImage(width * 2, height * 2, QImage.Format_ARGB32)
        img2x.fill(QColor(Qt.transparent))
        painter = QPainter(img)  
        painter.begin(img)
        painter2x = QPainter(img2x)  
        painter2x.begin(img2x)
        spritesheet = {}
        spritesheet2x = {}
        x = 0
        for name, sprites in sprites.iteritems():
            s, s2x = sprites
            painter.drawImage(x, 0, s)
            painter2x.drawImage(x * 2, 0, s2x)
            spritesheet[name] = {"width": s.width(),
                                 "height": s.height(),
                                 "x": x,
                                 "y": 0,
                                 "pixelRatio": 1}
            spritesheet2x[name] = {"width": s2x.width(),
                                 "height": s2x.height(),
                                 "x": x * 2,
                                 "y": 0,
                                 "pixelRatio": 2}
            x += s.width()
        painter.end()
        painter2x.end()
        img.save(os.path.join(folder, "sprites.png"))
        img2x.save(os.path.join(folder, "sprites@2x.png"))
        with open(os.path.join(folder, "sprites.json"), 'w') as f:
            json.dump(spritesheet, f)
        with open(os.path.join(folder, "sprites@2x.json"), 'w') as f:
            json.dump(spritesheet2x, f)

def createSources(folder, layers, precision = 6):
    sources = {}
    layersFolder = os.path.join(folder, "data")
    QDir().mkpath(layersFolder)
    reducePrecision = re.compile(r"([0-9]+\.[0-9]{%s})([0-9]+)" % precision)
    removeSpaces = lambda txt:'"'.join( it if i%2 else ''.join(it.split())
                         for i,it in enumerate(txt.split('"')))
    regexp = re.compile(r'"geometry":.*?null\}')
    for layer in layers:
        if layer.type() == layer.VectorLayer:
            layerName =  safeName(layer.name())
            if folder is not None:
                path = os.path.join(layersFolder, "%s.geojson" % layerName)
                QgsVectorFileWriter.writeAsVectorFormat(layer, path, "utf-8", layer.crs(), 'GeoJson')
                with codecs.open(path, encoding="utf-8") as f:
                    lines = f.readlines()
                with codecs.open(path, "w", encoding="utf-8") as f:
                    for line in lines:
                        line = reducePrecision.sub(r"\1", line)
                        line = line.strip("\n\t ")
                        line = removeSpaces(line)
                        if layer.wkbType()==QGis.WKBMultiPoint:
                            line = line.replace("MultiPoint", "Point")
                            line = line.replace("[ [", "[")
                            line = line.replace("] ]", "]")
                            line = line.replace("[[", "[")
                            line = line.replace("]]", "]")
                        line = regexp.sub(r'"geometry":null', line)
                        f.write(line)
            sources[layerName] = {"type": "geojson",
                                "data": "data/%s.geojson" % layerName
                                }

    return sources

def _toZoomLevel(scale):
    return int(math.log(1000000000 / scale, 2))

def _toScale(level):
    return 1000000000 / (math.pow(2, level))


def _property(s, default=None):
    def _f(x):
        try:
            return float(x.symbolLayer(0).properties()[s])
        except KeyError:
            return default
        except ValueError:
            return str(x.symbolLayer(0).properties()[s])
    return _f

def _colorProperty(s):
    def _f(x):
        try:
            return _getRGBColor(x.symbolLayer(0).properties()[s])
        except KeyError:
            return "rgb(0,0,0)"
    return _f


def _getRGBColor(color):
    try:
        r,g,b,a = color.split(",")
    except:
        color = color.lstrip('#')
        lv = len(color)
        r,g,b = tuple(str(int(color[i:i + lv // 3], 16)) for i in range(0, lv, lv // 3))
    return 'rgb(%s)' % ",".join([r, g, b])


def _fillPatternIcon(x):
    try:
        return x.svgFilePath()
    except:
        return None

def _alpha(x):
    try:
        return x.alpha()
    except:
        return 1

def _lineDash(x):
    #TODO: improve this
    try:
        if x.symbolLayer(0).properties()["line_style"] == "solid":
            return [1]
        else:
            return [3, 3]
    except KeyError:
        return [1]
    
def _iconName(symbol):
    filename, ext = os.path.splitext(os.path.basename(symbol.symbolLayer(0).path()))
    return filename
    
def _convertSymbologyForLayerType(symbols, functionType, layerType, attribute):
    d = {}
    sprites = {}
    if layerType == "symbol":
        if not isinstance(symbols, OrderedDict):
            symbols = {symbols}
        for symbol in symbols.values():
            sl = symbol.symbolLayer(0).clone()
            sl2x = symbol.symbolLayer(0).clone()
            sl2x.setSize(sl2x.size() * 2)
            newSymbol = QgsMarkerSymbolV2()
            newSymbol.appendSymbolLayer(sl)
            newSymbol.deleteSymbolLayer(0)
            newSymbol2x = QgsMarkerSymbolV2()
            newSymbol2x.appendSymbolLayer(sl2x)
            newSymbol2x.deleteSymbolLayer(0)
            img = newSymbol.asImage(QSize(sl.size(), sl.size()))
            img2x = newSymbol2x.asImage(QSize(sl2x.size(), sl2x.size()))
            sprites[_iconName(symbol)] = (img, img2x)
        _setPaintProperty(d, "icon-image", symbols, _iconName, functionType, attribute)
    elif layerType == "circle":
        _setPaintProperty(d, "circle-radius", symbols, _property("size", 1), functionType, attribute)
        _setPaintProperty(d, "circle-color", symbols, _colorProperty("color"), functionType, attribute)
        _setPaintProperty(d, "circle-opacity", symbols, _alpha, functionType, attribute)
        _setPaintProperty(d, "circle-stroke-width", symbols, _property("outline_width", 1), functionType, attribute)
        _setPaintProperty(d, "circle-stroke-color", symbols, _colorProperty("outline_color"), functionType, attribute)
    elif layerType == "line":
        _setPaintProperty(d, "line-width", symbols, _property("line_width", 1), functionType, attribute)
        _setPaintProperty(d, "line-opacity", symbols, _alpha, functionType, attribute)
        _setPaintProperty(d, "line-color", symbols, _colorProperty("line_color"), functionType, attribute)
        _setPaintProperty(d, "line-offset", symbols, _property("offset"), functionType, attribute)
        _setPaintProperty(d, "line-dasharray", symbols, _lineDash, functionType, attribute)
    elif layerType == "fill":
        _setPaintProperty(d, "fill-color", symbols, _colorProperty("color"), functionType, attribute)
        _setPaintProperty(d, "fill-outline-color", symbols, _colorProperty("outline_color"), functionType, attribute)
        _setPaintProperty(d, "fill-pattern", symbols, _fillPatternIcon, functionType, attribute)
        _setPaintProperty(d, "fill-opacity", symbols, _alpha, functionType, attribute)
        _setPaintProperty(d, "fill-translate", symbols, _property("offset"), functionType, attribute)

    return sprites, d

def _setPaintProperty(paint, property, obj, func, funcType, attribute):
    if isinstance(obj, OrderedDict):
        d = {}
        d["property"] = attribute
        d["stops"] = []
        for k,v in obj.iteritems():
            if v.symbolLayerCount() > 0:
                d["stops"].append([k, func(v)])
        d["type"] = funcType
        for element in d["stops"]:
            if element[1] is not None:
                paint[property] = d
                break
    else:
        v = func(obj)
        if v is not None:
            paint[property] = v

def _getLayerType(qgisLayer, symbol):
    if qgisLayer.geometryType() == QGis.Line:
        return "line"
    if qgisLayer.geometryType() == QGis.Polygon:
        return "fill"
    else:
        # Limitation:
        # We take the first symbol if there are categories, and assume all categories use similar renderer
        if isinstance(symbol, OrderedDict):
            symbol = symbol.values()[0]
        if isinstance(symbol.symbolLayer(0), QgsSvgMarkerSymbolLayerV2):
            return "symbol"
        else:
            return "circle"

def processLayer(qgisLayer):
    layers = []
    allSprites = {}
    try:
        layer = {}
        layer["id"] = safeName(qgisLayer.name())
        layer["source"] = safeName(qgisLayer.name())
        if str(qgisLayer.customProperty("labeling/scaleVisibility")).lower() == "true":
            layer["minzoom"]  = _toZoomLevel(float(qgisLayer.customProperty("labeling/scaleMin")))
            layer["maxzoom"]  = _toZoomLevel(float(qgisLayer.customProperty("labeling/scaleMax")))

        renderer = qgisLayer.rendererV2()
        if isinstance(renderer, QgsSingleSymbolRendererV2):
            symbols = renderer.symbol().clone()
            functionType = None
            prop = None
        elif isinstance(renderer, QgsCategorizedSymbolRendererV2):
            symbols = OrderedDict()
            for cat in renderer.categories():
                symbols[cat.value()] = cat.symbol().clone()
            functionType = "categorical"
            prop = renderer.classAttribute()
        elif isinstance(renderer, QgsGraduatedSymbolRendererV2):
            symbols = OrderedDict()
            for ran in renderer.ranges():
                symbols[ran.lowerValue()] = ran.symbol().clone()
            functionType = "interval"
            prop = renderer.classAttribute()
        else:
            return {}, []

        layer["type"] = _getLayerType(qgisLayer, symbols)
        sprites, layer["paint"] = _convertSymbologyForLayerType(symbols, functionType, layer["type"], prop)
        allSprites.update(sprites)
        
    except Exception, e:
        import traceback
        print traceback.format_exc()
        return {}, []

    layers.append(layer)
    if str(qgisLayer.customProperty("labeling/enabled")).lower() == "true":
        layers.append(processLabeling(qgisLayer))
    return sprites, layers

def processLabeling(qgisLayer):
    layer = {}
    layer["id"] = "txt_" + safeName(qgisLayer.name())
    layer["source"] =  safeName(qgisLayer.name())
    layer["type"] = "symbol"

    layer["layout"] = {}
    labelField = qgisLayer.customProperty("labeling/fieldName")
    layer["layout"]["text-field"] = "{%s}" % labelField
    try:
        size = float(qgisLayer.customProperty("labeling/fontSize"))
    except:
        size = 1
    layer["layout"]["text-size"] = size

    layer["paint"] = {}
    r = qgisLayer.customProperty("labeling/textColorR")
    g = qgisLayer.customProperty("labeling/textColorG")
    b = qgisLayer.customProperty("labeling/textColorB")
    color = "rgba(%s, %s, %s, 255)" % (r,g,b)
    layer["paint"]["text-color"] = color

    if str(qgisLayer.customProperty("labeling/bufferDraw")).lower() == "true":
        rHalo = str(qgisLayer.customProperty("labeling/bufferColorR"))
        gHalo = str(qgisLayer.customProperty("labeling/bufferColorG"))
        bHalo = str(qgisLayer.customProperty("labeling/bufferColorB"))
        strokeWidth = str(float(qgisLayer.customProperty("labeling/bufferSize")))
        layer["paint"]["text-halo-color"] = "rgba(%s, %s, %s, 255)" % (rHalo, gHalo, bHalo)
        layer["paint"]["text-halo-width"] =  float(strokeWidth)

    rotation = -1 * float(qgisLayer.customProperty("labeling/angleOffset"))
    layer["layout"]["text-rotate"] = rotation

    offsetX = str(qgisLayer.customProperty("labeling/xOffset"))
    offsetY = str(qgisLayer.customProperty("labeling/yOffset"))

    layer["layout"]["text-offset"] = offsetX + "," + offsetY
    layer["layout"]["text-opacity"] = (255 - int(qgisLayer.layerTransparency())) / 255.0

    # textBaselines = ["bottom", "middle", "top"]
    # textAligns = ["end", "center", "start"]
    # quad = int(layer.customProperty("labeling/quadOffset"))
    # textBaseline = textBaselines[quad / 3]
    # textAlign = textAligns[quad % 3]
    #===========================================================================

    if str(qgisLayer.customProperty("labeling/scaleVisibility")).lower() == "true":
        layer["minzoom"]  = _toZoomLevel(float(qgisLayer.customProperty("labeling/scaleMin")))
        layer["maxzoom"]  = _toZoomLevel(float(qgisLayer.customProperty("labeling/scaleMax")))

    return layer


def safeName(name):
    #TODO: we are assuming that at least one character is valid...
    validChars = '123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_'
    return ''.join(c for c in name if c in validChars).lower()

def _qcolorFromRGBString(color):
    color = "".join([c for c in color if c in "1234567890,"])
    r, g, b = color.split(",")
    return QColor(int(r), int(g), int(b))


def _markerSymbol(outlineColor, outlineWidth, color, size, opacity):
    symbol = QgsMarkerSymbolV2()
    symbolLayer = QgsSimpleMarkerSymbolLayerV2(size = size, color = _qcolorFromRGBString(color))
    symbolLayer.setOutlineColor(_qcolorFromRGBString(outlineColor))
    symbolLayer.setOutlineWidth(outlineWidth)
    symbol.appendSymbolLayer(symbolLayer)
    symbol.deleteSymbolLayer(0)
    symbol.setAlpha(opacity)
    return symbol

def _fillSymbol(color, outlineColor, translate, opacity):
    symbol = QgsFillSymbolV2()
    symbolLayer = QgsSimpleFillSymbolLayerV2()
    symbolLayer.setBorderColor(_qcolorFromRGBString(outlineColor))
    x,y = translate.split(",")
    symbolLayer.setOffset(QPointF(float(x), float(y)))
    symbolLayer.setFillColor(_qcolorFromRGBString(color))
    symbol.appendSymbolLayer(symbolLayer)
    symbol.deleteSymbolLayer(0)
    symbol.setAlpha(opacity)
    return symbol

def _lineSymbol(color, width, dash, offset, opacity):
    symbol = QgsLineSymbolV2()
    symbolLayer = QgsSimpleLineSymbolLayerV2(_qcolorFromRGBString(color), width)
    symbolLayer.setCustomDashVector(dash)
    symbolLayer.setOffset(offset)
    symbol.appendSymbolLayer(symbolLayer)
    symbol.deleteSymbolLayer(0)
    symbol.setAlpha(opacity)
    return symbol

_svgTemplate =  """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
    <!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
    "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
    <svg version="1.1"
    xmlns="http://www.w3.org/2000/svg"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    width="240px" height="240px" viewBox="0 0 240 240">"""
 """</svg>"""
def _svgMarkerSymbol(name, sprites):
    #TODO: see if there is a built-in sprite with that name

    with open(sprites + ".json") as f:
        spritesDict = json.load(f)
    rect = QRect(spritesDict[name]["x"], spritesDict[name]["y"], 
                spritesDict[name]["width"], spritesDict[name]["height"])
    width = spritesDict[name]["width"]
    height = spritesDict[name]["height"]
    image = QImage()
    image.load(sprites + ".png")
    sprite = image.copy(rect)
    pngPath = os.path.join(os.path.dirname(sprites), name + ".png")
    sprite.save(pngPath)
    with open(pngPath, "rb") as f:
        data = f.read()
    base64 = data.encode("base64")
    svgPath = os.path.join(os.path.dirname(sprites), name + ".svg")
    with open(svgPath, "w") as f:
        f.write
    symbol = QgsMarkerSymbolV2()
    symbolLayer = QgsSvgMarkerSymbolLayerV2(svgPath)
    symbol.setSize(max([width, height]))
    symbol.appendSymbolLayer(symbolLayer)
    symbol.deleteSymbolLayer(0)
    return symbol

layerTypes = {QGis.Point: ["circle", "symbol"], QGis.Line: ["line"], QGis.Polygon: ["fill"]}

def setLayerSymbologyFromMapboxStyle(layer, style, sprites):
    if style["type"] not in layerTypes[layer.geometryType()]:
        return

    if style["type"] == "line":
        if isinstance(style["paint"]["line-color"], dict):
            if style["paint"]["line-color"]["type"] == "categorical":
                categories = []
                for i, stop in enumerate(style["paint"]["line-color"]["stops"]):
                    dash = style["paint"]["line-dasharray"]["stops"][i][1]
                    width = style["paint"]["line-width"]["stops"][i][1]
                    offset = style["paint"]["line-offset"]["stops"][i][1]
                    opacity = style["paint"]["line-opacity"]["stops"][i][1]
                    color = stop[1]
                    symbol = _lineSymbol(color, width, dash, offset, opacity)
                    value = stop[0]
                    categories.append(QgsRendererCategoryV2(value, symbol, value))
                renderer = QgsCategorizedSymbolRendererV2(style["paint"]["line-color"]["property"], categories)
                layer.setRendererV2(renderer)
            else:
                ranges = []
                for i, stop in enumerate(style["paint"]["line-color"]["stops"]):
                    dash = style["paint"]["line-dasharray"]["stops"][i][1]
                    width = style["paint"]["line-width"]["stops"][i][1]
                    offset = style["paint"]["line-offset"]["stops"][i][1]
                    opacity = style["paint"]["line-opacity"]["stops"][i][1]
                    color = stop[1]
                    symbol = _lineSymbol(color, width, dash, offset, opacity)
                    min = stop[0]
                    try:
                        max = style["paint"]["line-color"]["stops"][i+1][0]
                    except:
                        max = 100000000000
                    ranges.append(QgsRendererRangeV2(min, max, symbol, str(min) + "-" + str(max)))
                renderer = QgsGraduatedSymbolRendererV2(style["paint"]["line-color"]["property"], ranges)
                layer.setRendererV2(renderer)
        else:
            dash = style["paint"]["line-dasharray"]
            width = style["paint"]["line-width"]
            offset = style["paint"]["line-offset"]
            opacity = style["paint"]["line-opacity"]
            color = style["paint"]["line-color"]
            symbol = _lineSymbol(color, width, dash, offset, opacity)
            layer.setRendererV2(QgsSingleSymbolRendererV2(symbol))
    elif style["type"] == "circle":
        if isinstance(style["paint"]["circle-radius"], dict):
            if style["paint"]["circle-radius"]["type"] == "categorical":
                categories = []
                for i, stop in enumerate(style["paint"]["circle-radius"]["stops"]):
                    outlineColor = style["paint"]["circle-stroke-color"]["stops"][i][1]
                    outlineWidth = style["paint"]["circle-stroke-width"]["stops"][i][1]
                    color = style["paint"]["circle-color"]["stops"][i][1]
                    opacity = style["paint"]["circle-opacity"]["stops"][i][1]
                    radius = stop[1]
                    symbol = _markerSymbol(outlineColor, outlineWidth, color, radius, opacity)
                    value = stop[0]
                    categories.append(QgsRendererCategoryV2(value, symbol, value))
                renderer = QgsCategorizedSymbolRendererV2(style["paint"]["circle-radius"]["property"], categories)
                layer.setRendererV2(renderer)
            else:
                ranges = []
                for i, stop in enumerate(style["paint"]["circle-radius"]["stops"]):
                    outlineColor = style["paint"]["circle-stroke-color"]["stops"][i][1]
                    outlineWidth = style["paint"]["circle-stroke-width"]["stops"][i][1]
                    color = style["paint"]["circle-color"]["stops"][i][1]
                    opacity = style["paint"]["circle-opacity"]["stops"][i][1]
                    radius = stop[1]
                    symbol = _markerSymbol(outlineColor, outlineWidth, color, radius, opacity)
                    min = stop[0]
                    try:
                        max = style["paint"]["circle-radius"]["stops"][i+1][0]
                    except:
                        max = 100000000000
                    ranges.append(QgsRendererRangeV2(min, max, symbol, str(min) + "-" + str(max)))
                renderer = QgsGraduatedSymbolRendererV2(style["paint"]["circle-radius"]["property"], ranges)
                layer.setRendererV2(renderer)
        else:
            outlineColor = style["paint"]["circle-stroke-color"]
            outlineWidth = style["paint"]["circle-stroke-width"]
            color = style["paint"]["circle-color"]
            radius = style["paint"]["circle-radius"]
            opacity = style["paint"]["circle-opacity"]
            symbol = _markerSymbol(outlineColor, outlineWidth, color, radius, opacity)
            layer.setRendererV2(QgsSingleSymbolRendererV2(symbol))
    elif style["type"] == "fill":
        if isinstance(style["paint"]["fill-color"], dict):
            if style["paint"]["fill-color"]["type"] == "categorical":
                categories = []
                for i, stop in enumerate(style["paint"]["fill-color"]["stops"]):
                    outlineColor = style["paint"]["fill-outline-color"]["stops"][i][1]
                    translate = style["paint"]["fill-translate"]["stops"][i][1]
                    opacity = style["paint"]["fill-opacity"]["stops"][i][1]
                    color = stop[1]
                    symbol = _fillSymbol(color, outlineColor, translate, opacity)
                    value = stop[0]
                    categories.append(QgsRendererCategoryV2(value, symbol, value))
                renderer = QgsCategorizedSymbolRendererV2(style["paint"]["fill-color"]["property"], categories)
                layer.setRendererV2(renderer)
            else:
                ranges = []
                for i, stop in enumerate(style["paint"]["fill-color"]["stops"]):
                    outlineColor = style["paint"]["fill-outline-color"]["stops"][i][1]
                    translate = style["paint"]["fill-translate"]["stops"][i][1]
                    opacity = style["paint"]["fill-opacity"]["stops"][i][1]
                    color = stop[1]
                    symbol = _fillSymbol(color, outlineColor, translate, opacity)
                    min = stop[0]
                    try:
                        max = style["paint"]["fill-color"]["stops"][i+1][0]
                    except:
                        max = 100000000000
                    ranges.append(QgsRendererRangeV2(min, max, symbol, str(min) + "-" + str(max)))
                renderer = QgsGraduatedSymbolRendererV2(style["paint"]["fill-color"]["property"], ranges)
                layer.setRendererV2(renderer)
        else:
            outlineColor = style["paint"]["fill-outline-color"]
            translate = style["paint"]["fill-translate"]
            opacity = style["paint"]["fill-opacity"]
            color = style["paint"]["fill-color"]
            symbol = _fillSymbol(color, outlineColor, translate, opacity)
            layer.setRendererV2(QgsSingleSymbolRendererV2(symbol))
    elif style["type"] == "symbol":
        if isinstance(style["paint"]["icon-image"], dict):
            if style["paint"]["icon-image"]["type"] == "categorical":
                categories = []
                for i, stop in enumerate(style["paint"]["icon-image"]["stops"]):
                    symbol = _svgMarkerSymbol(stop[1], sprites)
                    value = stop[0]
                    categories.append(QgsRendererCategoryV2(value, symbol, value))
                renderer = QgsCategorizedSymbolRendererV2(style["paint"]["icon-image"]["property"], categories)
                layer.setRendererV2(renderer)
            else:
                ranges = []
                for i, stop in enumerate(style["paint"]["icon-image"]["stops"]):
                    symbol = _svgMarkerSymbol(stop[1], sprites)
                    min = stop[0]
                    try:
                        max = style["paint"]["icon-image"]["stops"][i+1][0]
                    except:
                        max = 100000000000
                    ranges.append(QgsRendererRangeV2(min, max, symbol, str(min) + "-" + str(max)))
                renderer = QgsGraduatedSymbolRendererV2(style["paint"]["icon-image"]["property"], ranges)
                layer.setRendererV2(renderer)

    layer.triggerRepaint()

def setLayerLabelingFromMapboxStyle(layer, style):
    palyr = QgsPalLayerSettings()
    palyr.readFromLayer(layer)
    palyr.enabled = True
    palyr.fieldName = style["layout"]["text-field"].replace("{", "").replace("}", "")
    offsets = style["layout"]["text-offset"].split(",")
    palyr.xOffset = float(offsets[0])
    palyr.yOffset = float(offsets[0])
    if "minzoom" in style:
        palyr.scaleMin = _toScale(float(style["minzoom"]))
        palyr.scaleMax = _toScale(float(style["maxzoom"]))
        palyr.scaleVisibility = True
        palyr.placement = QgsPalLayerSettings.OverPoint

    #palyr.setDataDefinedProperty(QgsPalLayerSettings.OffsetXY,True,True,str(offsets), "")
    palyr.setDataDefinedProperty(QgsPalLayerSettings.Size,True,True,str(style["layout"]["text-size"]), "")
    palyr.setDataDefinedProperty(QgsPalLayerSettings.Color,True,True,str(style["paint"]["text-color"]), "")

    if "text-halo-color" in style["layout"]:
        palyr.setDataDefinedProperty(QgsPalLayerSettings.BufferColor,True,True,str(style["layout"]["text-halo-color"]), "")
    if "text-halo-width" in style["layout"]:
        palyr.setDataDefinedProperty(QgsPalLayerSettings.BufferSize,True,True,str(style["layout"]["text-halo-width"]), "")
    palyr.writeToLayer(layer)

def openProjectFromMapboxFile(mapboxFile):
    iface.newProject()
    layers = {}
    labels = []
    with open(mapboxFile) as f:
        project = json.load(f)
    if "sprite" in project:
        sprites = os.path.join(os.path.dirname(mapboxFile), project["sprite"])
    else:
        sprites = None
    for layer in project["layers"]:
        source = project["sources"][layer["source"]]["data"]
        path = os.path.join(os.path.dirname(mapboxFile), source)
        if layer["id"].startswith("txt"):
            labels.append(layer)
        else:
            qgislayer = dataobjects.load(path, layer["id"])
            setLayerSymbologyFromMapboxStyle(qgislayer, layer, sprites)
            layers[layer["source"]] = qgislayer
    for labelLayer in labels:
        setLayerLabelingFromMapboxStyle(layers[labelLayer["source"]], labelLayer)
        
        
            