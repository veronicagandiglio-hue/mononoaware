from pathlib import Path
text = Path('genera-markdown.html').read_text(encoding='utf-8').replace('\r\n', '\n')
marker = 'function escHtml (s) {\n  return s.replace(/&/g,\'&amp;\').replace(/</g,\'&lt;\').replace(/>/g,\'&gt;\').replace(/"/g,\'&quot;\');\n}\n\n/* ─────────────────────────────────────────────────────\n   GENERA MARKDOWN\n──────────────────────────────────────────────────── */\n'
idx = text.find('function escHtml (s) {')
print('text snippet:', repr(text[idx:idx+260]))
print('marker repr:', repr(marker))
print('marker found:', marker in text)
print('marker len', len(marker))
print('substring len', len(text[idx:idx+len(marker)]))
print('equal:', marker == text[idx:idx+len(marker)])
