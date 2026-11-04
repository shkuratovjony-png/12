from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
marker = "if __name__=='__main__':"
pos = s.rfind(marker)
if pos == -1:
    raise SystemExit('[build] main guard not found for GitHub backup endpoint')

route = r'''

@app.get('/internal/github-backup')
def github_backup_export():
    import os as _os
    from flask import after_this_request, request as _request, send_file

    auth = _request.headers.get('Authorization','').strip()
    token = auth[7:].strip() if auth.lower().startswith('bearer ') else ''

    try:
        from backup_secure import create_encrypted_backup_file, verify_github_oidc
        verify_github_oidc(token)
        path, filename = create_encrypted_backup_file()

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
            mimetype='application/octet-stream',
            max_age=0,
        )
    except Exception as exc:
        print(f'[github-backup] denied/failed: {type(exc).__name__}: {exc}', flush=True)
        return ('not found', 404)

'''

s = s[:pos] + route + s[pos:]
p.write_text(s, encoding='utf-8')
print('[build] GitHub OIDC encrypted backup endpoint applied', flush=True)
