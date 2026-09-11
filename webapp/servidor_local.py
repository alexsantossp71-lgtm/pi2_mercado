# -*- coding: utf-8 -*-
"""Servidor local simples para testar o Dispensa Planejada."""
import http.server
import socketserver
import webbrowser
import os

PORT = 8080
WEBROOT = os.path.dirname(os.path.abspath(__file__))

os.chdir(WEBROOT)

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[Dispensa Planejada] {self.address_string()} {fmt % args}")

with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    url = f"http://127.0.0.1:{PORT}/index.html"
    print(f"Servidor rodando em {url}")
    print("Pressione Ctrl+C para encerrar.")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
