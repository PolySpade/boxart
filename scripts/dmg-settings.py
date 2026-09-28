import os
root = os.getcwd()
files = [os.path.join(root, 'build/BoxArt.app')]
symlinks = {'Applications': '/Applications'}
icon_locations = {'BoxArt.app': (170, 215), 'Applications': (490, 215)}
window_rect = ((180, 160), (660, 420))
background = os.path.join(root, 'Resources/DMG/background.png')
icon = os.path.join(root, 'build/BoxArt.app/Contents/Resources/BoxArt.icns')
icon_size = 96
text_size = 14
show_toolbar = False
show_status_bar = False
show_pathbar = False
show_sidebar = False
default_view = 'icon-view'
format = 'UDZO'
