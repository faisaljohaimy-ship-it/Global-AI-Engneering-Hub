// Minimal static file server for the motion library, bound to localhost on a free port.
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, resolve, sep } from 'node:path';

const types = { '.html': 'text/html', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };

export async function serve(root) {
  const server = createServer((request, response) => {
    const path = resolve(root, '.' + decodeURIComponent(new URL(request.url, 'http://localhost').pathname));
    if (!path.startsWith(root + sep) || !types[extname(path)]) {
      response.writeHead(404).end();
      return;
    }
    try {
      response.writeHead(200, { 'content-type': types[extname(path)] + '; charset=utf-8' }).end(readFileSync(path));
    } catch {
      response.writeHead(404).end();
    }
  });
  await new Promise((ready) => server.listen(0, '127.0.0.1', ready));
  return { origin: `http://127.0.0.1:${server.address().port}`, close: () => server.close() };
}
