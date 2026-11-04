import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
const server=fileURLToPath(new URL('../../node_modules/@upstash/context7-mcp/dist/index.js',import.meta.url));
const proc=spawn(process.execPath,[server],{stdio:['pipe','pipe','pipe']});
const pending=new Map();let next=0;
const lines=createInterface({input:proc.stdout});
lines.on('line',line=>{try{const data=JSON.parse(line);if(pending.has(data.id)){const {resolve,reject}=pending.get(data.id);pending.delete(data.id);data.error?reject(Error(data.error.message)):resolve(data.result);}}catch{}});
const timer=setTimeout(()=>{console.error('Context7 check timed out.');proc.kill();process.exitCode=1;},25000);
function call(method,params={}){const id=++next;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});proc.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});}
try {
 await call('initialize',{protocolVersion:'2025-03-26',capabilities:{},clientInfo:{name:'talent-radar-install-check',version:'1.0'}});
 proc.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
 const {tools}=await call('tools/list');
 console.log('MCP handshake OK; tools:',tools.map(t=>t.name).join(', '));
 const result=await call('tools/call',{name:'resolve-library-id',arguments:{libraryName:'gsap',query:'GSAP timeline documentation'}});
 if(result.isError)throw Error('Context7 returned an upstream service error.');
 const text=(result.content||[]).filter(x=>x.type==='text').map(x=>x.text).join('\n');
 if(/invalid api key|unauthorized|rate limit exceeded/i.test(text))throw Error('Context7 requires authentication or quota.');
 console.log('Documentation lookup result:',text.slice(0,450));
} catch(error){console.error(error.message);process.exitCode=1;}
finally{clearTimeout(timer);proc.kill();lines.close();}
