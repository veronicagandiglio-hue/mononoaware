from pathlib import Path
text = Path('genera-markdown.html').read_text(encoding='utf-8').replace('\r\n', '\n')
marker = 'function escHtml (s) {\n  return s.replace(/&/g,\'&amp;\').replace(/</g,\'&lt;\').replace(/>/g,\'&gt;\').replace(/"/g,\'&quot;\');\n}\n\n/* ─────────────────────────────────────────────────────\n   GENERA MARKDOWN\n──────────────────────────────────────────────────── */\n'
print('marker length', len(marker))
print('found', marker in text)
idx = text.find('function escHtml (s) {')
print('idx', idx)
print('text snippet', repr(text[idx:idx+200]))
