from pathlib import Path
text = Path('genera-markdown.html').read_text(encoding='utf-8').replace('\r\n', '\n')
marker = 'function escHtml (s) {\n  return s.replace(/&/g,\'&amp;\').replace(/</g,\'&lt;\').replace(/>/g,\'&gt;\').replace(/"/g,\'&quot;\');\n}\n\n/* ─────────────────────────────────────────────────────\n   GENERA MARKDOWN\n──────────────────────────────────────────────────── */\n'
idx = text.find('function escHtml (s) {')
real = text[idx:idx+len(marker)]
for i,(a,b) in enumerate(zip(marker, real)):
    if a!=b:
        print('diff at', i, repr(a), repr(b))
        print('marker segment', repr(marker[i-20:i+20]))
        print('real segment', repr(real[i-20:i+20]))
        break
print('marker repr', repr(marker))
print('real repr', repr(real))
