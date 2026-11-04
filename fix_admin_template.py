from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
out = []
changed = False
for line in s.splitlines():
    if line.startswith('def page(body): return BASE.format('):
        out.append('def page(body):')
        out.append('    nav=("<nav>❤️ <b>Совпали</b> &nbsp; <a href=\'/admin\'>Главная</a><a href=\'/admin/users\'>Пользователи</a><a href=\'/admin/settings\'>Настройки</a><a href=\'/admin/logout\'>Выйти</a></nav>" if session.get(\'a\') else \'\')')
        out.append("    return BASE.replace('{nav}', nav).replace('{body}', body)")
        changed = True
    else:
        out.append(line)
if changed:
    p.write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('[build] admin template fixed')
else:
    print('[build] admin template already fixed or not found')
