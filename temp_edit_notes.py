from pathlib import Path

path = Path('genera-markdown.html')
text = path.read_text(encoding='utf-8').replace('\r\n', '\n')

search = 'placeholder="Incolla qui il testo tradotto del racconto…"></textarea>\n    </div>\n  </div>\n'
insert_block = '''placeholder="Incolla qui il testo tradotto del racconto…"></textarea>\n      <div style="margin-top:12px; display:flex; flex-wrap:wrap; gap:10px; align-items:center;">\n        <button class="btn btn-sm btn-add" type="button" onclick="insertPopupNoteSnippet()">Inserisci nota popup</button>\n        <span class="field-note">Aggiunge <code>&lt;span class=\"nota\" data-nota=\"...\"&gt;↑&lt;/span&gt;</code> nel punto di inserimento.</span>\n      </div>\n    </div>\n  </div>\n'''
if search not in text:
    raise SystemExit('HTML insert point not found')
text = text.replace(search, insert_block, 1)

marker_start = 'function escHtml (s) {\n'
marker_end = '\n\n/* ─────────────────────────────────────────────────────\n   GENERA MARKDOWN\n──────────────────────────────────────────────────── */\n'
idx = text.find(marker_start)
if idx == -1:
    raise SystemExit('escHtml function not found')
idx_end = text.find(marker_end, idx)
if idx_end == -1:
    raise SystemExit('JS insert end marker not found')
idx_end += len(marker_end)
insert = '''function insertPopupNoteSnippet () {\n  const snippet = '<span class=\"nota\" data-nota=\"Testo della nota popup\">↑</span>';\n  let target = null;\n  if (_mode === 'single') {\n    target = $('f-text-single');\n  } else {\n    const active = document.activeElement;\n    if (active && active.classList && active.classList.contains('chapter-text')) {\n      target = active;\n    } else {\n      target = document.querySelector('.chapter-text');\n    }\n  }\n  if (!target) {\n    return toast('Nessun campo testo disponibile per inserire la nota popup');\n  }\n  const start = target.selectionStart || target.value.length;\n  const end = target.selectionEnd || start;\n  target.value = target.value.slice(0, start) + snippet + target.value.slice(end);\n  target.focus();\n  const pos = start + snippet.length;\n  target.selectionStart = target.selectionEnd = pos;\n  scheduleUpdate();\n  toast('Nota popup inserita nel testo');\n}\n\n'''
text = text[:idx_end] + insert + text[idx_end:]
path.write_text(text.replace('\n', '\r\n'), encoding='utf-8')
print('Updated genera-markdown.html')
