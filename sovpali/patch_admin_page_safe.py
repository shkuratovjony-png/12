from pathlib import Path
import re

p=Path('app.py')
s=p.read_text(encoding='utf-8')

pattern=r"def page\(body\):\s*return BASE\.format\(nav=\((.*?)\),body=body\)"
m=re.search(pattern,s,re.S)
if m:
    nav_expr=m.group(1)
    repl=("def page(body):\n"
          "    nav = ("+nav_expr+")\n"
          "    return BASE.replace('{nav}', nav).replace('{body}', body)\n")
    s=s[:m.start()]+repl+s[m.end():]
    print('[build] admin page rendering made format-safe', flush=True)
else:
    # Fallback for a one-line or slightly different page() implementation.
    start=s.find('def page(body):')
    end=s.find('\ndef need(', start)
    if start!=-1 and end!=-1:
        block=s[start:end]
        nav_start=block.find('nav=(')
        body_marker=',body=body)'
        if nav_start!=-1 and body_marker in block:
            nav_expr=block[nav_start+4:block.rfind(body_marker)]
            new=("def page(body):\n"
                 "    nav = "+nav_expr+"\n"
                 "    return BASE.replace('{nav}', nav).replace('{body}', body)\n")
            s=s[:start]+new+s[end:]
            print('[build] admin page rendering fixed by fallback', flush=True)
        else:
            raise SystemExit('[build] admin page render target not found')
    else:
        raise SystemExit('[build] page() block not found')

p.write_text(s,encoding='utf-8')
