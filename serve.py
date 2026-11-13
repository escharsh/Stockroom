"""Local WSGI entry point. Configuration comes from environment variables."""
import os
import sys
import webbrowser
from waitress import create_server
from app import create_app

if __name__ == '__main__':
    host = os.environ.get('STOCKROOM_HOST', '127.0.0.1')
    port = int(os.environ.get('STOCKROOM_PORT', '5000'))
    server = create_server(create_app(), host=host, port=port, threads=4)
    print(f'Stockroom is running at http://{host}:{port}', flush=True)
    print('Press Ctrl+C to stop.', flush=True)
    if '--open' in sys.argv:
        webbrowser.open(f'http://127.0.0.1:{port}')
    server.run()
