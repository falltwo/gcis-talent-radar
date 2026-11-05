const test=require('node:test'),assert=require('node:assert/strict');
const skills=require('../../ui/static/recruitment-skills.js');
test('skills round trip preserves compound punctuation and 30 long entries',()=>{
 const values=['html、css 與 javascript','需求分析，跨部門溝通',...Array.from({length:28},(_,i)=>`${i}技能${'字'.repeat(70)}`)];
 assert.deepEqual(skills.parse(skills.format(values)),values);
});
test('empty training skills clear defaults and edited values remain separate',()=>{
 assert.deepEqual(skills.parse(skills.format([])),[]);
 assert.deepEqual(skills.parse('CNC\r\n品管\r\nCNC\r\n'),['CNC','品管']);
 assert.deepEqual(skills.parse(skills.format(['html、css'])),['html、css']);
});
