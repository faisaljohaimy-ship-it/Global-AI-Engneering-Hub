import { createServer } from 'node:http';
import { lstat, readFile, realpath } from 'node:fs/promises';
import { extname, isAbsolute, join, relative, resolve, sep } from 'node:path';

export const inside = (root, path) => {
  const rel = relative(root, path);
  return rel !== '' && !rel.startsWith(`..${sep}`) && rel !== '..' && !isAbsolute(rel);
};
const types = { '.html': 'text/html', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };
const csp = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";

export async function serveStudio(inputRoot) {
  const root = await realpath(inputRoot);
  const server = createServer(async (request, response) => {
    try {
      if (!['GET', 'HEAD'].includes(request.method)) { response.writeHead(405).end(); return; }
      const url = new URL(request.url, 'http://127.0.0.1');
      let path = decodeURIComponent(url.pathname);
      if (path === '/motion-studio/') path += 'index.html';
      if (!/^\/(?:motion-studio|packages\/motion-sdk|motion-library\/expansion)\//.test(path)
          || path.includes('\\') || path.includes('\0')
          || path.split('/').some(segment => ['.', '..'].includes(segment))) { response.writeHead(404).end(); return; }
      const file = resolve(root, '.' + path);
      if (!inside(root, file) || !types[extname(file)]) { response.writeHead(404).end(); return; }
      let current = root;
      for (const segment of relative(root, file).split(sep)) {
        current = join(current, segment);
        if ((await lstat(current)).isSymbolicLink()) { response.writeHead(404).end(); return; }
      }
      const stat = await lstat(file);
      if (!stat.isFile() || stat.size > 2_000_000) { response.writeHead(404).end(); return; }
      const data = await readFile(file);
      response.writeHead(200, {
        'content-type': `${types[extname(file)]}; charset=utf-8`,
        'content-security-policy': csp,
        'cache-control': 'no-store',
        'x-content-type-options': 'nosniff',
        'referrer-policy': 'no-referrer',
      });
      response.end(request.method === 'HEAD' ? undefined : data);
    } catch { response.writeHead(404).end(); }
  });
  await new Promise((ready, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', ready); });
  return { root, origin: `http://127.0.0.1:${server.address().port}`, close: () => new Promise((ready, reject) => server.close(error => error ? reject(error) : ready())) };
}
