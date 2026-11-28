// Minimal static file server for the browser checks: localhost only, a free port,
// a fixed list of file types, and no path outside the served root.
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, resolve, sep } from 'node:path';

const types = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };

export async function serve(root) {
  const base = resolve(root);
  const server = createServer((request, response) => {
    const path = resolve(base, '.' + decodeURIComponent(new URL(request.url, 'http://localhost').pathname));
    if (!path.startsWith(base + sep) || !types[extname(path)]) {
      response.writeHead(404).end();
      return;
    }
    try {
      response.writeHead(200, { 'content-type': types[extname(path)] + '; charset=utf-8', 'cache-control': 'no-store' }).end(readFileSync(path));
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((ready) => server.listen(0, '127.0.0.1', ready));
  return { origin: `http://127.0.0.1:${server.address().port}`, close: () => server.close() };
}
