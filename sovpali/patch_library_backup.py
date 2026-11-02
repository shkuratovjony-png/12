from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
marker = "if __name__=='__main__':"
pos = s.rfind(marker)
if pos == -1:
    raise SystemExit('[build] main guard not found for library backup endpoint')

route = r'''

@app.get('/internal/library-backup/<token>')
def library_backup_export(token):
    import hmac
    import os as _os
    from flask import after_this_request, send_file

    expected = _os.getenv('BACKUP_EXPORT_TOKEN','').strip()
    if not expected or not hmac.compare_digest(token, expected):
        return ('not found', 404)

    try:
        from backup_export import create_backup_file
        path, filename = create_backup_file()

        @after_this_request
        def _cleanup_backup_file(response):
            try:
                _os.unlink(path)
            except OSError:
                pass
            response.headers['Cache-Control'] = 'no-store, max-age=0'
            return response

        return send_file(
            path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/gzip',
            max_age=0,
        )
    except Exception as exc:
        print(f'[backup-export] failed: {type(exc).__name__}: {exc}', flush=True)
        return ('backup failed', 500)

'''

s = s[:pos] + route + s[pos:]
p.write_text(s, encoding='utf-8')
print('[build] protected library backup endpoint applied', flush=True)
