/* One line is one complete skill, including punctuation inside that skill. */
(function(root){
 'use strict';
 const skills={
  format(values){return values.length?values.join('\n')+'\n':'';},
  parse(value){return [...new Set(value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean))];}
 };
 if(typeof module!=='undefined'&&module.exports)module.exports=skills;else root.RecruitmentSkills=skills;
})(typeof window!=='undefined'?window:globalThis);
