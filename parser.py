#!/usr/bin/python3

import click
import xml.etree.ElementTree as ET
from xml.dom import minidom
import xmltodict
import svgutils.transform as sg
import sys 
import re
import csv
import svgwrite
import shutil
import zipfile
import glob
import os
import math

MM_TO_PX = 96 / 25.4       # SVGs measure in px but maybe we want mm!
PX_TO_MM = 25.4 / 96       # SVGs measure in px but maybe we want mm!
MM_TO_PX = 96 / 25.4       # SVGs measure in px but maybe we want mm!
PX_TO_MM = 25.4 / 96       # SVGs measure in px but maybe we want mm!
FONT_HEIGHT_PX = 10.5
FONT_CHAR_W = 4

#BOX_HEIGHT = 10
#BOX_WIDTH_PER_CHAR = 5
#LABEL_FONTSIZE = 8
#LABEL_HEIGHTADJUST = 2     # move text down (negative for up)
# SVG is canonically supposed to be 96 DPI, but something along the way
# (maybe it's just Illustrator import) is thinking it's 72.
MM_TO_PT = 72 / 25.4
PT_TO_MM = 25.4 / 72
BOX_HEIGHT = 2.54 * MM_TO_PT  # 0.1 inch to match pin spacing
BOX_WIDTH_PER_CHAR = BOX_HEIGHT / 2
LABEL_FONTSIZE = 6
LABEL_HEIGHTADJUST = 1.75
LABEL_FONT = "Courier New"

# TO DO: make these part of theme?
BOX_STROKE_WIDTH = 0.5
BOX_CORNER_RADIUS = 1.0
ROW_STROKE_WIDTH = 1.0
ROW_STROKE_COLOR = '#404040'

themes = [
    {'type':'Name', 'fill':'#E0E0E0', 'outline':'#808080', 'opacity':1.0, 'inset':0.3, 'font-weight':'bold'},
    {'type':'Power', 'fill':'#FF0000', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'bold'},
    {'type':'GND', 'fill':'#000000', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'bold'},
    {'type':'Control', 'fill':'#A0A0A0', 'outline':'#404040', 'opacity':1.0, 'inset':0.3, 'font-weight':'bold'},
    {'type':'Arduino', 'fill':'#A0FFA0', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'Port', 'fill':'#FFFFCC', 'outline':'#C0C0A0', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'Analog', 'fill':'#FFA000', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'PWM', 'fill':'#C0FFC0', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'UART', 'fill':'#FFC0C0', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'SPI', 'fill':'#C0C0FF', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'I2C', 'fill':'#FFA0FF', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'QT_SCL', 'fill':'#FFFF00', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'bold'},
    {'type':'QT_SDA', 'fill':'#0000FF', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'bold'},
    {'type':'ExtInt', 'fill':'#FF00FF', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'PCInt', 'fill':'#FFC000', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'Misc', 'fill':'#A0A0FF', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    {'type':'Misc2', 'fill':'#C0C0FF', 'outline':'none', 'opacity':1.0, 'inset':0.3, 'font-weight':'normal'},
    ]

# some eagle cad names are not as pretty
conn_renames = [('!RESET', 'RESET'),
                ('D5_5V', 'D5'),
                ('+3V3', '3.3V'),
                ('+5V', '5V')
                ]


# This function digs through the FZP (XML) file and the SVG (also, ironically, XML) to find what
# frtizing calls a connection - these are pads that folks can connect to! they are 'named' by
# eaglecad, so we should use good names for eaglecad nets that will synch with circuitpython names
def get_connections(fzp, svg):
    connections = []

    # check the FPZ for every 'connector' type element
    f = open(fzp)
    xmldict = xmltodict.parse(f.read())
    for c in xmldict['module']['connectors']['connector']:
        c_name = c['@name']     # get the pad name
        c_svg = c['views']['breadboardView']['p']['@svgId']   # and the SVG ID for the pad
        d = {'name': c_name, 'svgid': c_svg}
        connections.append(d)
    #print(connections)

    # ok now we can open said matching svg xml
    xmldoc = minidom.parse(svg)

    # Find all circle/pads
    circlelist = xmldoc.getElementsByTagName('circle')
    for c in circlelist:
        try:
            idval = c.attributes['id'].value   # find the svg id
            cx = c.attributes['cx'].value      # x location
            cy = c.attributes['cy'].value      # y location
            d = next((conn for conn in connections if conn['svgid'] == c.attributes['id'].value), None)
            if d:
                d['cx'] = float(cx)
                d['cy'] = float(cy)
                d['svgtype'] = 'circle'  
        except KeyError:
            pass
    # sometimes pads are ellipses, note they're often transformed so ignore the cx/cy
    ellipselist = xmldoc.getElementsByTagName('ellipse')
    for c in ellipselist:
        try:
            print(c)
            idval = c.attributes['id'].value   # find the svg id
            d = next((conn for conn in connections if conn['svgid'] == c.attributes['id'].value), None)
            if d:
                d['cx'] = None
                d['cy'] = None
                d['svgtype'] = 'ellipse'                
        except KeyError:
            pass
    return connections

def get_circuitpy_aliases(connections, circuitpydef):
    # now check the circuitpython definition file
    pyvar = open(circuitpydef).readlines()
    for line in pyvar:
        #print(line)
        # find the QSTRs
        matches = re.match(r'.*MP_ROM_QSTR\(MP_QSTR_(.*)\),\s+MP_ROM_PTR\(&pin_(.*)\)', line)
        if not matches:
            continue
        #print(matches.group(1), matches.group(2))
        
        for d in connections:
            if d['name'] == matches.group(1):
                if not 'aliases' in d:
                    d['aliases'] = []
                d['aliases'].append(matches.group(2))
    return connections

def get_chip_pinout(connections, pinoutcsv):
    with open(pinoutcsv, mode='r') as infile:
        pinarray = []
        reader = csv.reader(infile)
        csvlist = [row for row in reader]
        header = csvlist.pop(0)
        for pin in csvlist:
            gpioname = pin[0]
            d = {}
            for i,mux in enumerate(pin):
                d[header[i]] = mux
            pinarray.append(d)
        pinmuxes = header
    print("Mux options available: ", pinmuxes)
    return pinarray


def draw_label(dwg, label_text, label_type, box_x, box_y, box_w, box_h):
    theme = next((theme for theme in themes if theme['type'] == label_type), None)
    box_outline = theme['outline']
    box_fill = theme['fill']
    text_color = 'black'
    if (box_fill[0] == '#'):
        red = int(box_fill[1:3], 16)
        green = int(box_fill[3:5], 16)
        blue = int(box_fill[5:7], 16)
        lightness = red * 0.299 + green * 0.587 + blue * 0.114
        if lightness < 128:
            text_color = 'white'
    elif (box_fill == 'black'):
        text_color = 'white'

    box_opacity = theme['opacity']
    weight = theme['font-weight']
    # draw a box
    if 'inset' in theme:
        box_x += float(theme['inset'])
        box_y += float(theme['inset'])
        box_w -= float(theme['inset']) * 2
        box_h -= float(theme['inset']) * 2
    if box_outline != 'none':
        box_x += BOX_STROKE_WIDTH * 0.5 # Inset further for stroke
        box_y += BOX_STROKE_WIDTH * 0.5
        box_w -= BOX_STROKE_WIDTH
        box_h -= BOX_STROKE_WIDTH
    dwg.add(dwg.rect(
        (box_x, box_y),
        (box_w, box_h),
        BOX_CORNER_RADIUS, BOX_CORNER_RADIUS,
        stroke = box_outline,
        stroke_width = BOX_STROKE_WIDTH,
        opacity = box_opacity,
        fill = box_fill
        ))
    dwg.add(dwg.text(
        label_text,
        insert = (box_x+box_w/2, box_y+box_h/2+LABEL_HEIGHTADJUST),
        font_size = LABEL_FONTSIZE,
        font_family = LABEL_FONT,
        font_weight = weight,
        fill = text_color,
        text_anchor = "middle",
        ))

    
def draw_pinlabels_svg(connections):
    dwg = svgwrite.Drawing(filename=str("pinlabels.svg"), profile='tiny', size=(100,100))

    # collect all muxstrings to calculate label widths:
    muxstringlen = {}
    for i, conn in enumerate(connections):
        if not 'mux' in conn:
            continue
        for mux in conn['mux']:
            if not mux in muxstringlen:
                muxstringlen[mux] = 0
            muxstringlen[mux] = max(muxstringlen[mux], len(conn['mux'][mux]))
    #print(muxstringlen)

    # group connections by cx/cy
    tops = sorted([c for c in connections if c['location'] == 'top'], key=lambda k: k['cx'])
    bottoms = sorted([c for c in connections if c['location'] == 'bottom'], key=lambda k: k['cx'])
    rights = sorted([c for c in connections if c['location'] == 'right'], key=lambda k: k['cy'])
    lefts = sorted([c for c in connections if c['location'] == 'left'], key=lambda k: k['cy'])
    others = [c for c in connections if c['location'] == 'unknown']
    #print(connections)

    # A first pass through all the connectors draws the
    # row lines behind the MUX boxes
    for i, conn in enumerate(tops+[None,]+bottoms+[None,]+rights+[None,]+lefts+[None,]+others):
        if conn == None: # Gap between groups
            continue
        box_x = 0
        box_w = 6 * BOX_WIDTH_PER_CHAR # See note later, 1st column width
        first_box_w = box_w
        if 'mux' in conn:
            for mux in conn['mux']:
                if not conn['mux'][mux]:
                    continue
                box_w = (muxstringlen[mux]+1) * BOX_WIDTH_PER_CHAR
                if conn['location'] in ('top', 'right', 'unknown'):
                    box_x += box_w
                if conn['location'] in ('bottom', 'left'):
                    box_x -= box_w
        line_y = (i + 0.5) * BOX_HEIGHT
        if conn['location'] in ('top', 'right', 'unknown'):
            dwg.add(dwg.line(start=(-4, line_y), end=(box_x + box_w * 0.5, line_y), stroke=ROW_STROKE_COLOR, stroke_width = ROW_STROKE_WIDTH, stroke_linecap='round'));
        if conn['location'] in ('bottom', 'left'):
            dwg.add(dwg.line(start=(first_box_w + 4, line_y), end=(box_x + box_w * 0.5, line_y), stroke=ROW_STROKE_COLOR, stroke_width = ROW_STROKE_WIDTH, stroke_linecap='round'));

    # pick out each connection
    for i, conn in enumerate(tops+[None,]+bottoms+[None,]+rights+[None,]+lefts+[None,]+others):
        if conn == None:
            continue  # a space!
        #print(conn)

        # start with the pad name
        box_x = 0
        box_y = BOX_HEIGHT * i
        # First-column boxes are all this rigged width for now
        box_w = 6 * BOX_WIDTH_PER_CHAR
        box_h = BOX_HEIGHT

        name_label = conn['name']

        # clean up some names!

        label_type = 'Name'
        if name_label in ("3.3V", "5V", "VBAT", "VBUS", "VHI"):
            label_type = 'Power'
        if name_label in ("GND"):
            label_type = 'GND'
        if name_label in ("EN", "RESET", "SWCLK", "SWC", "SWDIO", "SWD"):
            label_type = 'Control'
        if name_label in ('SCL', 'SCL1', 'SCL0') and conn['svgtype'] == 'ellipse':
            # special stemma QT!
            label_type = 'QT_SCL'
        if name_label in ('SDA', 'SDA1', 'SDA0') and conn['svgtype'] == 'ellipse':
            # special stemma QT!
            label_type = 'QT_SDA'

        # Draw the first-column box (could be power pin or Arduino pin #)
        draw_label(dwg, name_label, label_type, box_x, box_y, box_w, box_h)
        if conn['location'] in ('top', 'right', 'unknown'):
            box_x += box_w

        # power pins don't have muxing, its cool!
        if not 'mux' in conn:
            continue
        for mux in conn['mux']:
            label = conn['mux'][mux]
            if not label:
                continue
            if mux == 'GPIO':  # the underlying pin GPIO name
                label_type = 'Port'
            elif mux == 'SPI':  # SPI ports
                label_type = 'SPI'
            elif mux == 'I2C':  # I2C ports
                label_type = 'I2C'
            elif mux == 'UART':  # UART ports
                label_type = 'UART'
            elif mux == 'PWM':  # PWM's
                label_type = 'PWM'
            elif mux == 'ADC':  # analog ins
                label_type = 'Analog'
            else:
                continue

            box_w = (muxstringlen[mux]+1) * BOX_WIDTH_PER_CHAR

            if conn['location'] in ('top', 'right', 'unknown'):
                draw_label(dwg, label, label_type, box_x, box_y, box_w, box_h)
                box_x += box_w
            if conn['location'] in ('bottom', 'left'):
                box_x -= box_w
                draw_label(dwg, label, label_type, box_x, box_y, box_w, box_h)

    dwg.save()


@click.argument('pinoutcsv')
@click.argument('circuitpydef')
@click.argument('FZPZ')
@click.command()
def parse(fzpz, circuitpydef, pinoutcsv):
    # fzpz are actually zip files!
    shutil.copyfile(fzpz, fzpz+".zip")
    # delete any old workdir
    shutil.rmtree('workdir')
    # unzip into the work dir
    with zipfile.ZipFile(fzpz+".zip", 'r') as zip_ref:
        zip_ref.extractall('workdir')
    fzpfilename = glob.glob(r'workdir/*.fzp')[0]
    svgfilename = glob.glob(r'workdir/svg.breadboard*.svg')[0]
    os.remove(fzpz+".zip")

    # get the connections dictionary
    connections = get_connections(fzpfilename, svgfilename)

    # rename any that need it
    for conn in connections:
        for rename in conn_renames:
            if conn['name'] == rename[0]:
                conn['name'] = rename[1]

    # find the 'true' GPIO pine via the circuitpython file
    connections = get_circuitpy_aliases(connections, circuitpydef)

    # open and parse the pinout mapper CSV
    pinarray = get_chip_pinout(connections, pinoutcsv)

    # get SVG width and height
    bb_sg = sg.fromfile(svgfilename)
    bb_root = bb_sg.getroot()
    svg_width = bb_sg.width
    svg_height = bb_sg.height
    if "in" in svg_width:
        svg_width = 25.4 * float(svg_width[:-2]) * MM_TO_PX
    else:
        raise RuntimeError("Dont know units of width!", svg_width)
    if "in" in svg_height:
        svg_height = 25.4 * float(svg_height[:-2]) * MM_TO_PX
    else:
        raise RuntimeError("Dont know units of width!", svg_height)
    
    print("Width, Height in px: ", svg_width, svg_height)
    
    # Create a new SVG as a copy!
    newsvg = sg.SVGFigure()
    newsvg.set_size(("%dpx" % svg_width, "%dpx" % svg_height))    
    #print(newsvg.get_size())
    # DO NOT SCALE THE BREADBOARD SVG. We know it's 1:1 size.
    # If things don't align, issue is in the newly-generated pin table SVG.
    #bb_root.rotate(90)
    #bb_root.moveto(0, 0, 1.33)
    newsvg.append(bb_root)
    newsvg.save("output.svg")

    # try to determine whether its top/bottom/left/right
    sh = svg_height * 0.75  # fritzing scales everything by .75 which is confusing!
    sw = svg_width * 0.75  # so get back to the size we think we are
    #print("scaled w,h", sw, sh)
    for conn in connections:
        if not conn['cy']:
            conn['location'] = 'unknown'
        elif conn['cy'] < 10:
            conn['location'] = 'top'
        elif conn['cy'] > sh-10:
            conn['location'] = 'bottom'
        elif conn['cx'] > sw-10:
            conn['location'] = 'right'
        elif conn['cx'] < 10:
            conn['location'] = 'left'
        else:
            conn['location'] = 'unknown'
        print(conn)
                
        # add muxes to connections
        if not 'aliases' in conn:
            continue
        for alias in conn['aliases']:
            # find muxes next
            muxes = next((pin for pin in pinarray if pin['GPIO'] == alias), None)
            conn['mux'] = muxes
    draw_pinlabels_svg(connections)

    newsvg.save("output.svg")




if __name__ == '__main__':
    parse()
