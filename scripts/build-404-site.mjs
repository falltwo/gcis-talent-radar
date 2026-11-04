// Build the standalone, frontend-only demo. No credentials or database files.
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
let html = await readFile(resolve(root, 'ui/static/recruitment-demo.html'), 'utf8');
// The radar homepage is not part of this standalone deployment.
html = html.replace('<p><a href="/">回到產業人才雷達</a></p>', '');
const out = resolve(root, 'dist/404-jobs');
await mkdir(out, { recursive: true });
await writeFile(resolve(out, 'index.html'), html, 'utf8');
console.log('Built dist/404-jobs/index.html (frontend demo only)');
