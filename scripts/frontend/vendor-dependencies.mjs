import { build } from 'esbuild';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = fileURLToPath(new URL('../../', import.meta.url));
const target = path.join(root, 'ui/static/vendor');
await mkdir(path.join(target, 'maplibre'), {recursive:true});
await mkdir(path.join(target, 'gsap'), {recursive:true});
await build({
  stdin: {contents: `import * as maplibre from 'maplibre-gl'; maplibre.setWorkerUrl('/static/vendor/maplibre/maplibre-gl-worker.mjs'); window.maplibregl = maplibre;`, resolveDir: root, sourcefile:'maplibre-browser-entry.js'},
  bundle:true, format:'iife', minify:true, target:'es2022', legalComments:'eof',
  outfile:path.join(target,'maplibre/maplibre-gl.js'),
});
for (const name of ['maplibre-gl.css','maplibre-gl-worker.mjs','maplibre-gl-shared.mjs'])
  await copyFile(path.join(root,'node_modules/maplibre-gl/dist',name),path.join(target,'maplibre',name));
await copyFile(path.join(root,'node_modules/maplibre-gl/LICENSE.txt'),path.join(target,'maplibre/LICENSE.txt'));
await copyFile(path.join(root,'node_modules/gsap/dist/gsap.min.js'),path.join(target,'gsap/gsap.min.js'));
const gsap = JSON.parse(await readFile(path.join(root,'node_modules/gsap/package.json'),'utf8'));
await writeFile(path.join(target,'gsap/NOTICE.txt'), `GSAP ${gsap.version}\nSource: https://github.com/greensock/GSAP\nLicense: https://gsap.com/standard-license/\n`);
console.log('Prepared pinned MapLibre and GSAP browser assets with license notices.');
