from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
root = Path(__file__).resolve().parent.parent
im = Image.new('RGB', (1320, 840), '#f5f8f9')
d = ImageDraw.Draw(im)
font = '/System/Library/Fonts/Supplemental/Arial.ttf'
bold = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'
def text(y, value, size, color, face=font):
    d.text((660,y), value, font=ImageFont.truetype(face,size), fill=color, anchor='mt')
text(66,'BoxArt',64,'#17343c',bold)
text(150,'Your games. Beautifully covered.',28,'#536c73')
for x in (340,980):
    d.rounded_rectangle((x-126,292,x+126,544),radius=42,fill='#ffffff',outline='#e1e9eb',width=2)
d.line((600,426,720,426),fill='#299b9f',width=6)
d.line((698,404,720,426,698,448),fill='#299b9f',width=6)
text(654,'Drag BoxArt to Applications',32,'#17343c',bold)
text(710,'Then open BoxArt from your Applications folder.',24,'#536c73')
im.resize((660,420),Image.Resampling.LANCZOS).save(root/'Resources/DMG/background.png')
