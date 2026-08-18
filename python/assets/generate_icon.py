"""Gera o icone do projeto (icon.ico + icon.png) do zero com PIL - sem usar
nenhum logo/asset de terceiros, so formas geometricas simples (circulo + duas
setas em arco formando o simbolo de sync). Roda uma vez em dev; os arquivos
gerados ja ficam versionados em python/assets/, nao precisa rodar de novo a
nao ser que queira mudar o desenho.

Uso: python assets/generate_icon.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent
SIZE = 1024
BG = (37, 99, 235, 255)      # azul solido (combina com o tema padrao do customtkinter)
FG = (255, 255, 255, 255)    # branco


def draw_sync_glyph(size=SIZE):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    margin = size * 0.06
    d.ellipse([margin, margin, size - margin, size - margin], fill=BG)

    cx = cy = size / 2
    r = size * 0.30
    stroke = size * 0.085
    box = [cx - r, cy - r, cx + r, cy + r]

    # dois arcos de 140 graus, opostos, com folga entre eles -> le como duas
    # flechas girando (simbolo classico de "sync"/"refresh").
    d.arc(box, start=20, end=160, fill=FG, width=int(stroke))
    d.arc(box, start=200, end=340, fill=FG, width=int(stroke))

    head_len = stroke * 2.0
    head_half_width = stroke * 1.05

    def arrow_head(angle_deg):
        theta = math.radians(angle_deg)
        px, py = cx + r * math.cos(theta), cy + r * math.sin(theta)
        # tangente na direcao de avanco (sentido horario, angulo crescente)
        tx, ty = -math.sin(theta), math.cos(theta)
        # radial (perpendicular a tangente, usado pra abrir a base do triangulo)
        rx, ry = math.cos(theta), math.sin(theta)

        tip = (px + head_len * tx, py + head_len * ty)
        base1 = (px + head_half_width * rx, py + head_half_width * ry)
        base2 = (px - head_half_width * rx, py - head_half_width * ry)
        d.polygon([tip, base1, base2], fill=FG)

    arrow_head(160)
    arrow_head(340)

    return img


def main():
    img = draw_sync_glyph()
    img.save(OUT_DIR / "icon.png")

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(OUT_DIR / "icon.ico", format="ICO", sizes=ico_sizes)
    print(f"gerado: {OUT_DIR / 'icon.png'} e {OUT_DIR / 'icon.ico'}")


if __name__ == "__main__":
    main()
