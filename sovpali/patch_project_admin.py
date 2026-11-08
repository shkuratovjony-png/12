from pathlib import Path
p=Path('app.py')
s=p.read_text()
marker="if __name__=='__main__':"
assert s.count(marker)==1, 'Unexpected application entry point'
s=s.replace(marker,"""# Independent project console: no payment routes or state changes.
import project_admin
project_admin.register(app, lambda: psycopg.connect(DATABASE_URL, connect_timeout=7), 'sovpali', console=True)

"""+marker)
p.write_text(s)
